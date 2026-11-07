"""Atomic JSON persistence with optimistic page versions."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from threading import RLock
from fastapi import HTTPException
from .schema import Review, PageReview, BlockReview

lock = RLock()

def digest(folder):
    h=hashlib.sha256()
    for name in ['document.json','content.json','pagination.json']:
        h.update((folder/name).read_bytes())
    return h.hexdigest()

def review_path(folder):
    return folder.parents[2]/'reviews'/(folder.name+'.json')

def read(folder, subset, count):
    path=review_path(folder)
    review=Review.model_validate_json(path.read_text(encoding='utf-8')) if path.exists() else Review(subset=subset,doc_id=folder.name,bundle_hash=digest(folder))
    stale=review.bundle_hash!=digest(folder)
    decisions=[p.decision for p in review.pages.values()]
    review.status='todo' if stale else 'rejected' if 'rejected' in decisions else 'flagged' if 'flagged' in decisions or any(b.verdict=='text_wrong' for p in review.pages.values() for b in p.blocks.values()) else 'approved' if len(decisions)==count and all(d=='approved' for d in decisions) else 'in_review' if review.history else 'todo'
    return review,stale

def write(folder, subset, count, n, payload, block_id=None):
    with lock:
        review,stale=read(folder,subset,count)
        if stale: raise HTTPException(409,'Bundle changed: this review is stale')
        page=review.pages.setdefault(str(n),PageReview())
        if page.version!=payload.version: raise HTTPException(409,'Page changed in another tab. Reload before saving.')
        now=datetime.now(timezone.utc).isoformat()
        if block_id:
            page.blocks[block_id]=BlockReview(verdict=payload.verdict,fix=payload.fix,note=payload.note,by=payload.reviewer,at=now)
        elif hasattr(payload,'order'):
            page.order=payload.order
        else:
            page.decision=payload.decision;page.note=payload.note;page.by=payload.reviewer;page.at=now
        page.version+=1
        review.history.append(dict(page=n,block_id=block_id,at=now,**payload.model_dump()))
        from factory.runner.reviews import status
        review.status=status(review,count)
        path=review_path(folder);path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8') as stream:
            stream.write(review.model_dump_json(indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)
        return read(folder,subset,count)[0]
