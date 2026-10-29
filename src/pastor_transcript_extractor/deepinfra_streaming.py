"""OpenAI SSE assembly with JSON-aware loop cancellation; no provider credentials persisted."""
from dataclasses import dataclass
import json
from time import monotonic
from .evidence_requests import WireResponse, wire


class WhitespaceLoop(ValueError):
    pass


@dataclass
class JSONWhitespaceDetector:
    threshold: int = 256
    in_string: bool = False
    escaped: bool = False
    consecutive: int = 0

    def __post_init__(self):
        if type(self.threshold) is not int or self.threshold<1:raise ValueError('Whitespace threshold must be a positive integer')

    def feed(self,text):
        for char in text:
            if self.in_string:
                self.consecutive=0
                if self.escaped:self.escaped=False
                elif char=='\\':self.escaped=True
                elif char=='"':self.in_string=False
            elif char=='"':self.in_string=True;self.consecutive=0
            elif char in ' \t\r\n':
                self.consecutive+=1
                if self.consecutive>self.threshold:raise WhitespaceLoop('JSON whitespace loop detected')
            else:self.consecutive=0


def events(lines,check=None):
    """SSE data records; comments and event framing are not generated content."""
    data=[]
    for line in lines:
        if check:check()
        if not line:
            if data:yield '\n'.join(data);data=[]
        elif line.startswith('data:'):data.append(line[5:].lstrip(' '))
    if data:yield '\n'.join(data)


def attempt(spec,client,headers,*,threshold,deadline,clock=monotonic):
    """Close the response before returning any cancellation/incomplete record."""
    started=clock();detector=JSONWhitespaceDetector(threshold);parts=[];reasoning=[];usage={}
    finish=None;done=False;status=200;service_tier='standard';model=None;refusal=None;tools=[];first=None;error=None;cancelled=False
    response=None
    try:
        remaining=deadline-clock()
        if remaining<=0:raise TimeoutError('DeepInfra stream deadline exceeded')
        # The caller-facing request remains unchanged; both HTTP attempts get
        # precisely this same body, including the original temperature/schema.
        body={**spec.body,'stream':True}
        with client.stream('POST','https://api.deepinfra.com/v1/openai/chat/completions',headers=headers,json=body,timeout=remaining) as response:
            status=response.status_code
            if status!=200:raise ValueError(f'DeepInfra HTTP {status}')
            def check_deadline():
                if clock()>=deadline:raise TimeoutError('DeepInfra stream deadline exceeded')
            for event in events(response.iter_lines(),check_deadline):
                if clock()>=deadline:raise TimeoutError('DeepInfra stream deadline exceeded')
                if event=='[DONE]':done=True;break
                chunk=json.loads(event)
                if not isinstance(chunk,dict):raise ValueError('Invalid DeepInfra SSE chunk')
                if chunk.get('error'):raise ValueError('DeepInfra SSE error')
                if chunk.get('model'):
                    if chunk['model']!=spec.body['model']:raise ValueError('Resolved DeepInfra stream model differs')
                    model=chunk['model']
                if chunk.get('service_tier'):service_tier=chunk['service_tier']
                if chunk.get('usage') is not None:
                    if not isinstance(chunk['usage'],dict):raise ValueError('Invalid streamed usage')
                    usage=chunk['usage']
                choices=chunk.get('choices',[])
                if not isinstance(choices,list) or len(choices)>1:raise ValueError('Invalid streamed choice inventory')
                if not choices:continue
                choice=choices[0]
                if not isinstance(choice,dict):raise ValueError('Invalid streamed choice')
                if choice.get('index',0)!=0:raise ValueError('Unexpected streamed choice index')
                delta=choice.get('delta',{})
                if not isinstance(delta,dict):raise ValueError('Invalid streamed delta')
                text=delta.get('content')
                if text is not None:
                    if not isinstance(text,str):raise ValueError('Invalid streamed content')
                    if text and first is None:first=clock()-started
                    parts.append(text);detector.feed(text)
                for key in ('reasoning_content','thinking','reasoning'):
                    if delta.get(key):reasoning.append(str(delta[key]))
                if delta.get('refusal'):refusal=delta['refusal']
                if delta.get('tool_calls'):tools.extend(delta['tool_calls'])
                if choice.get('finish_reason') is not None:finish=choice['finish_reason']
    except WhitespaceLoop as exc:
        cancelled=True;error=str(exc)
    except (ValueError,KeyError,TypeError,OSError,TimeoutError) as exc:error=str(exc)
    except Exception as exc:
        # httpx transport errors are recorded without credentials/request headers.
        import httpx
        if not isinstance(exc,httpx.HTTPError):raise
        error=type(exc).__name__
    finally:
        if response is not None:response.close()
    if model is None and error is None:error='Missing DeepInfra streamed model identity'
    usage_final=done and finish is not None and error is None
    complete=done and finish=='stop' and error is None
    if not complete and error is None:error='Incomplete DeepInfra stream: missing DONE or stop'
    provider_finish=finish
    if not complete:finish='pte_whitespace_loop' if cancelled else 'pte_incomplete_stream'
    raw=dict(model=model,service_tier=service_tier,choices=[dict(index=0,finish_reason=finish,message=dict(role='assistant',content=''.join(parts),reasoning_content=''.join(reasoning),refusal=refusal,tool_calls=tools))],usage=usage)
    telemetry=dict(cancelled=cancelled,outcome='cancelled_whitespace_loop' if cancelled else 'complete' if complete else 'incomplete',error=error,
        elapsed_seconds=round(clock()-started,6),first_content_seconds=first,content_characters=sum(map(len,parts)),consecutive_whitespace=detector.consecutive,
        threshold=threshold,usage=usage,usage_final=usage_final,usage_available=type(usage.get('prompt_tokens')) is int and type(usage.get('completion_tokens')) is int,
        connection_closed=response is None or response.is_closed,finish_reason=finish,provider_finish_reason=provider_finish)
    return WireResponse(status,wire(raw)),telemetry


def transport(spec,*,key,timeout,threshold=256,maximum_attempts=1,before_attempt=None,after_attempt=None,client_factory=None,clock=monotonic):
    import httpx
    if maximum_attempts not in (1,2):raise ValueError('At most one stream recovery retry')
    JSONWhitespaceDetector(threshold)
    factory=client_factory or (lambda:httpx.Client(timeout=timeout,follow_redirects=False,trust_env=False,transport=httpx.HTTPTransport(retries=0)))
    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
    started=clock();deadline=started+timeout;records=[];last=None
    for index in range(1,maximum_attempts+1):
        if clock()>=deadline:
            if last is not None:break
            raise TimeoutError('DeepInfra stream deadline exceeded before attempt')
        if before_attempt:before_attempt(index)
        # Closing the client as well as the response closes the underlying pool
        # before an identical recovery attempt can open another connection.
        with factory() as client:last,record=attempt(spec,client,headers,threshold=threshold,deadline=deadline,clock=clock)
        record.update(attempt=index,connection_closed=True)
        records.append(record)
        if after_attempt:after_attempt(index,last,record)
        if not record['cancelled']:break
    raw=json.loads(last.text)
    raw['_pte_transport']=dict(version='deepinfra-qwen-stream-v1',attempts=records,total_elapsed_seconds=round(clock()-started,6),retry_outcome='not_needed' if not records[0]['cancelled'] else 'recovered' if len(records)==2 and records[-1]['outcome']=='complete' else 'exhausted' if len(records)==2 else 'blocked_by_budget_or_deadline')
    return WireResponse(last.status_code,wire(raw))


def usage_records(store,logical_attempt,receipt):
    """Read authenticated-by-digest physical attempt journals, including crash tails."""
    from .pastor_evidence import digest
    from . import deepinfra_requests as provider
    folder=store.root/'stream-attempts'/logical_attempt['request_fingerprint']
    reservations=sorted(folder.glob('*/reservation.json'),key=lambda p:int(p.parent.name))
    if not reservations:return None
    records=[]
    for index,path in enumerate(reservations,1):
        saved=json.loads(path.read_text());version=saved['request_version']
        base=version.removesuffix('-stream-v1') if version in provider.DEEPINFRA_QWEN_STREAM_VERSIONS else version
        maximum=2 if provider.reserved_usd(version)==2*provider.reserved_usd(base) else 1
        if (index>maximum or saved['attempt']!=index or saved['request_fingerprint']!=logical_attempt['request_fingerprint']
            or saved['reserved_usd']!=str(provider.reserved_usd(base))):raise ValueError('Streaming reservation journal differs')
        if receipt is not None and version!=receipt['request']['version']:raise ValueError('Streaming journal request version differs')
        telemetry=path.parent/'telemetry.json'
        if not telemetry.exists():records.append(dict(usage={},outcome='unknown'));continue
        record=json.loads(telemetry.read_text());raw_wire=json.loads((path.parent/'wire.json').read_text())
        if record['wire_digest']!=digest(raw_wire):raise ValueError('Corrupt streaming usage evidence')
        if json.loads(raw_wire['text'])['usage']!=record['usage']:raise ValueError('Stream usage metadata differs')
        records.append(record)
    if receipt is not None:
        root=store.root/'wire-responses'/(logical_attempt['request_fingerprint']+'.json')
        if root.exists():
            raw_wire=json.loads(root.read_text())
            if digest(raw_wire)!=receipt.get('wire_response_digest'):raise ValueError('Corrupt final streaming response')
            recorded=json.loads(raw_wire['text']).get('_pte_transport',{}).get('attempts')
            if recorded!=records:raise ValueError('Final stream attempt inventory differs')
    return records
