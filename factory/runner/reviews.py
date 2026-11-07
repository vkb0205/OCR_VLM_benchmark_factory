"""Read-only review selection for export and CLI reports."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from factory.contract.models.review import Review

def bundle_hash(folder):
    h=hashlib.sha256()
    for name in ['document.json','content.json','pagination.json']:h.update((folder/name).read_bytes())
    return h.hexdigest()

def load_review(folder):
    path=folder.parents[2]/'reviews'/(folder.name+'.json')
    if not path.exists():return None
    review=Review.model_validate_json(path.read_text(encoding='utf-8'))
    if review.doc_id!=folder.name or review.bundle_hash!=bundle_hash(folder):return None
    return review

def status(review,count):
    if not review:return 'todo'
    decisions=[p.decision for p in review.pages.values()]
    if 'rejected' in decisions:return 'rejected'
    if 'flagged' in decisions or any(b.verdict=='text_wrong' for p in review.pages.values() for b in p.blocks.values()):return 'flagged'
    if len(decisions)==count and all(d=='approved' for d in decisions):return 'approved'
    return 'in_review' if review.history else 'todo'

def report(root):
    counts=Counter();verdicts=Counter();categories=Counter()
    for manifest in sorted(root.glob('**/documents/*/*/document.json')):
        folder=manifest.parent;data=json.loads(manifest.read_text(encoding='utf-8'));review=load_review(folder)
        counts[status(review,data['page_count'])]+=1
        if review:
            content=json.loads((folder/'content.json').read_text(encoding='utf-8'))
            cats={b['id']:b['cat'] for b in content['blocks']}
            for p in review.pages.values():
                for bid,b in p.blocks.items():verdicts[b.verdict]+=1;categories[cats.get(bid,'unknown')]+=1
    return dict(statuses=dict(counts),verdicts=dict(verdicts),categories=dict(categories))
