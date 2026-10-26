"""Mechanical binding facts for model-authored corrections; never select or repair."""
from copy import deepcopy
import re

VERSION='binding-feedback-facts-v1'


def _at(value,path):
    if not path.startswith('$'): raise ValueError('Invalid diagnostic path')
    rest=path[1:]
    while rest:
        match=re.match(r'\.([A-Za-z_][A-Za-z_0-9]*)|\[(\d+)\]',rest)
        if match is None: raise ValueError('Invalid diagnostic path')
        value=value[match[1]] if match[1] is not None else value[int(match[2])]
        rest=rest[match.end():]
    return value


def enrich(errors,reading,window):
    """Retain every error; append complete literal matches or saved node facts."""
    texts,mapping=window.target();text=texts['target_text'];result=deepcopy(errors)
    for error in result:
        try:
            value=_at(reading,error['path'])
            if error['code']=='literal' and isinstance(value,dict) and set(value)=={'source_field','text'}:
                quote=value['text'];matches=[];cursor=0
                if value['source_field']=='target_text' and quote:
                    while (start:=text.find(quote,cursor))>=0:
                        end=start+len(quote);left=max(0,start-80);right=min(len(text),end+80)
                        matches.append(dict(start=start,end=end,context_start=left,context_end=right,
                            context=text[left:right],blocks=[dict(block_id=b['block_id'],
                                local_start=max(start,b['start'])-b['start'],local_end=min(end,b['end'])-b['start'],
                                target_sha256=b['target_sha256']) for b in mapping if start<b['end'] and end>b['start']]))
                        cursor=start+1  # Include overlapping occurrences, exactly as the compiler does.
                error['mechanical_details']=dict(version=VERSION,source_field=value['source_field'],literal_text=quote,
                    coordinate_system='Unicode character offsets in complete declared target; end exclusive',
                    occurrence_count=len(matches),matches=matches,exhaustive=True,selected_match=None,
                    limitation='All literal matches are shown in source order. None is selected or semantically endorsed; inspected context may need expansion.')
            elif error['code']=='reference':
                claim_path=re.match(r'^\$\.claims\[\d+\]',error['path'])
                if not claim_path: continue
                claim=_at(reading,claim_path[0]);nodes=claim['evidence_nodes'];prop=claim['proposition']['node_id']
                facts=dict(version=VERSION,proposition_node_id=prop,
                    available_nodes=[dict(node_id=n['node_id'],role=n['role']) for n in nodes],
                    available_nodes_origin='Saved model output; roles are not independent semantic judgments',selected_node_id=None)
                if re.fullmatch(r'\$\.claims\[\d+\]\.qualifications\[\d+\]',error['path']):
                    facts.update(referenced_node_id=value['node_id'],
                        referenced_node_is_defined=any(n['node_id']==value['node_id'] for n in nodes),
                        referenced_node_roles=[n['role'] for n in nodes if n['node_id']==value['node_id']],
                        required_role='qualification',applies_to=value['applies_to'],required_applies_to=prop,
                        applies_to_matches=value['applies_to']==prop,nonempty_reading=bool(value['reading']))
                elif isinstance(value,str):
                    facts.update(referenced_node_id=value,referenced_node_is_defined=any(n['node_id']==value for n in nodes))
                error['mechanical_details']=facts
        except (ValueError,KeyError,IndexError,TypeError):
            # Unrecognized errors remain verbatim; they are never dropped or repaired.
            continue
    return result
