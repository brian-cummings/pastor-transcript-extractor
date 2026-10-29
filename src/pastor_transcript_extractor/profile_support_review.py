"""Provider-free reverse-coverage packet; never runtime analytical evidence."""
from pathlib import Path
import json
from . import profile_analysis_support as core
from .profile_support_validation import file_hash
from .pastor_evidence import EvidenceArtifactStore as Store


def sources(record,out):
    out=Path(out);summaries=[]
    for source in record['source_identity']:
        path=Path(source['source_path'])
        if file_hash(path)!=source['source_sha256']:raise ValueError('Review source changed')
        raw=json.loads(path.read_text());window=raw['sermon_window'];start=window['start_seconds'];end=window['end_seconds']
        segments=[dict(index=i,**{k:s[k] for k in ('start_seconds','end_seconds','text')}) for i,s in enumerate(raw['segments']) if s['end_seconds']>start and s['start_seconds']<end]
        topic=core.resolve_topic_analysis_artifact(raw['classification']);eligible=[b for b in topic['blocks'] if b['projection_eligibility']['eligible']]
        observed={o['block_id'] for o in record['observations'] if o['video_id']==source['video_id']}
        chunks={}
        for segment in segments:chunks.setdefault(max(0,int((segment['start_seconds']-start)//600)),[]).append(segment)
        files=[]
        for n,rows in sorted(chunks.items()):
            stem=f"video-{source['video_id']}-part-{n+1:02d}"
            packet=dict(stage='assistant_source_review_only',runtime_evidence=False,source=source,sermon_window=dict(start_seconds=start,end_seconds=end),segments=rows,concatenation='Markdown joins original segment text with spaces; JSON preserves individual source indexes and timing. No quotations or semantic observations are created.')
            Store(out).write_immutable(stem+'.json',packet)
            (out/(stem+'.md')).write_text(f"# Video {source['video_id']} · part {n+1}\n\n{source['title']}\n\nSource segments {rows[0]['index']}–{rows[-1]['index']}; {rows[0]['start_seconds']}–{rows[-1]['end_seconds']} seconds.\n\n"+' '.join(s['text'] for s in rows)+'\n')
            files.append(dict(path=str(out/(stem+'.md')),sha256=file_hash(out/(stem+'.md')),segment_count=len(rows)))
        summaries.append(dict(video_id=source['video_id'],source_path=str(path),source_sha256=source['source_sha256'],sermon_start=start,sermon_end=end,segment_count=len(segments),text_characters=sum(len(s['text']) for s in segments),eligible_block_ids=[b['block_id'] for b in eligible],materialized_block_ids=sorted(observed),unmaterialized_eligible_blocks=sorted({b['block_id'] for b in eligible}-observed),review_files=files))
    report=dict(status='PREPARED_SOURCE_REVIEW_NOT_PERFORMED',runtime_evidence=False,sources=summaries,limitation='Covers existing declared sermon windows as text only; no audio accuracy, excluded recording material, other sermons or independent human validation. Text boundary-crossing segments are retained intact.')
    Store(out).write_immutable('source-review-inventory.json',report)
    return report
