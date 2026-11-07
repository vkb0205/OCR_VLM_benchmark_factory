"""Local, subset-scoped bundle viewer."""
import os
import json
import base64
import mimetypes
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image
from factory.contract.models import DocumentManifest, DocIR, Pagination, Boxes, LintReport
from factory.contract.extract import parse_html
from factory.contract.taxonomy import Taxonomy
from .schema import Review, VerdictWrite, DecisionWrite, OrderWrite
from . import reviews

ROOT = Path(__file__).resolve().parents[2]
RUN = Path(os.environ.get('GT_RUN', ROOT / 'OCR_VLM_benchmark_factory/out/uniqueness_phase0_attempt3')).resolve()
app = FastAPI(title='GT Review', version='0.1.0')

class Document(BaseModel):
    subset: str
    manifest: DocumentManifest
    content: DocIR
    pagination: Pagination
    boxes: Boxes
    lint: LintReport | None
    review: Review
    stale: bool
    spec: dict
    trace: dict

class Page(BaseModel):
    document: Document
    index: int
    image_width: int
    image_height: int
    size_matches: bool
    attributes: dict[str, str]

def scan():
    return {(('root' if p.parent.parent.parent.parent==RUN else p.parent.parent.parent.parent.relative_to(RUN).as_posix()), p.parent.name): p.parent
            for p in RUN.glob('**/documents/*/*/document.json')}

def folder(subset: str, doc_id: str):
    match = scan().get((subset, doc_id))
    if match is None: raise HTTPException(404, 'Unknown subset/document')
    return match

def load(path, model):
    return model.model_validate_json(path.read_text(encoding='utf-8'))

def document(subset, doc_id):
    p = folder(subset, doc_id)
    manifest = load(p / 'document.json', DocumentManifest)
    if manifest.contract_version not in {'0.2.0', '0.3.0'} or manifest.taxonomy_version != Taxonomy().version:
        raise HTTPException(422, 'Unsupported contract or taxonomy')
    review, stale = reviews.read(p, subset, manifest.page_count)
    return Document(spec=json.loads((p/"spec.json").read_text(encoding="utf-8")), trace=json.loads((p/"trace.json").read_text(encoding="utf-8")), review=review, stale=stale, subset=subset, manifest=manifest, content=load(p/'content.json', DocIR),
                    pagination=load(p/'pagination.json', Pagination), boxes=load(p/'extra/boxes.json', Boxes),
                    lint=load(p/'extra/lint.json', LintReport) if (p/'extra/lint.json').exists() else None)

@app.get('/api/runs', response_model=list[str])
def runs():
    output=ROOT/'OCR_VLM_benchmark_factory/out'
    return sorted({str(RUN),*(str(p) for p in output.iterdir() if p.is_dir() and not p.name.startswith('.'))})

@app.get('/api/docs', response_model=list[Document])
def docs(type: str='', status: str='', lang: str='', layout: str='', lint: str='', reviewer: str='', sort: str='lint'):
    result=[document(*key) for key in sorted(scan())]
    result=[d for d in result if (not type or d.manifest.doc_type==type) and (not status or d.review.status==status)
            and (not lang or d.content.lang==lang) and (not layout or d.manifest.attributes.get('layout')==layout)
            and (not lint or bool(d.lint and d.lint.findings)==(lint=='issues'))
            and (not reviewer or any(h.get('reviewer')==reviewer for h in d.review.history))]
    return sorted(result,key=lambda d: (-(len(d.lint.findings) if d.lint else 0),d.subset,d.manifest.doc_id) if sort=='lint' else (d.subset,d.manifest.doc_id))

@app.get('/api/docs/{subset}/{doc_id}', response_model=Document)
def get_doc(subset: str, doc_id: str):
    return document(subset, doc_id)

@app.get('/api/docs/{subset}/{doc_id}/pages/{n}', response_model=Page)
def get_page(subset: str, doc_id: str, n: int):
    doc = document(subset, doc_id)
    entry = next((p for p in doc.manifest.pages if p.index == n), None)
    if entry is None: raise HTTPException(404, 'Unknown page')
    p = folder(subset, doc_id)
    with Image.open(p / 'images' / f'page_{n:03}.png') as image: w, h = image.size
    box = next(b for b in doc.boxes.pages if b.index == n)
    body = next(node for node in parse_html((p / entry.file).read_text(encoding='utf-8')).walk() if node.tag == 'body')
    return Page(document=doc, index=n, image_width=w, image_height=h,
                size_matches=(w,h)==(box.image_width,box.image_height), attributes=body.attrs)

@app.get('/api/docs/{subset}/{doc_id}/pages/{n}/image')
def image(subset: str, doc_id: str, n: int):
    get_page(subset, doc_id, n)
    return FileResponse(folder(subset, doc_id)/'images'/f'page_{n:03}.png')

@app.get('/api/docs/{subset}/{doc_id}/pages/{n}/html', response_class=HTMLResponse)
def html(subset: str, doc_id: str, n: int):
    doc = document(subset, doc_id)
    entry = next((p for p in doc.manifest.pages if p.index == n), None)
    if entry is None: raise HTTPException(404)
    bundle=folder(subset,doc_id)
    path=bundle/entry.file
    def resource(value, base):
        if value.startswith(('data:','#')): return value
        target=(base/value).resolve()
        if not target.is_relative_to(bundle.resolve()) or not target.is_file(): return ''
        mime=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        data=target.read_bytes()
        if mime=='text/css':
            css=data.decode('utf-8')
            css=re.sub(r'url\([\"\']?([^\)\"\']+)[\"\']?\)',lambda m:'url('+resource(m[1],target.parent)+')',css)
            data=css.encode('utf-8')
        return 'data:'+mime+';base64,'+base64.b64encode(data).decode('ascii')
    source=path.read_text(encoding='utf-8')
    source=re.sub(r'url\([\"\']?([^\)\"\']+)[\"\']?\)',lambda m:'url('+resource(m[1],path.parent)+')',source)
    source=re.sub(r'(src|href)=[\"\']([^\"\']+)[\"\']',lambda m:m[1]+'="'+resource(m[2],path.parent)+'"',source)
    return HTMLResponse(source,
                        headers={'Content-Security-Policy': "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:"})

@app.put('/api/docs/{subset}/{doc_id}/pages/{n}/blocks/{block_id}', response_model=Review)
def verdict(subset: str, doc_id: str, n: int, block_id: str, payload: VerdictWrite):
    page=get_page(subset,doc_id,n)
    if block_id not in {b.id for p in page.document.boxes.pages if p.index==n for b in p.blocks}: raise HTTPException(404,'Unknown block')
    if payload.fix:
        if payload.fix.cat and payload.fix.cat not in Taxonomy().blocks: raise HTTPException(422,'Unknown category')
        if payload.fix.attrs and any(not Taxonomy().valid_attribute('block',k,v) for k,v in payload.fix.attrs.items()): raise HTTPException(422,'Invalid attributes')
        if payload.fix.poly:
            q=payload.fix.poly
            if any(not 0<=v<=(page.image_width if i%2==0 else page.image_height) for i,v in enumerate(q)): raise HTTPException(422,'Box outside page')
            if q[0]>=q[4] or q[1]>=q[5]: raise HTTPException(422,'Empty box')
    return reviews.write(folder(subset,doc_id),subset,page.document.manifest.page_count,n,payload,block_id)

@app.put('/api/docs/{subset}/{doc_id}/pages/{n}/decision', response_model=Review)
def decision(subset: str, doc_id: str, n: int, payload: DecisionWrite):
    page=get_page(subset,doc_id,n)
    return reviews.write(folder(subset,doc_id),subset,page.document.manifest.page_count,n,payload)

@app.put('/api/docs/{subset}/{doc_id}/pages/{n}/order', response_model=Review)
def order_write(subset: str, doc_id: str, n: int, payload: OrderWrite):
    page=get_page(subset,doc_id,n)
    ids={b.id for p in page.document.boxes.pages if p.index==n for b in p.blocks}
    if len(payload.order)!=len(ids) or set(payload.order)!=ids: raise HTTPException(422,'Order must contain every page block exactly once')
    return reviews.write(folder(subset,doc_id),subset,page.document.manifest.page_count,n,payload)

@app.get('/api/taxonomy', response_model=dict)
def taxonomy(): return Taxonomy().data

class ExportSummary(BaseModel):
    reviews: list[Review]
    approved: list[str]

@app.get('/api/export', response_model=ExportSummary)
def export_summary():
    documents=docs()
    return ExportSummary(reviews=[d.review for d in documents],approved=[d.subset+'/'+d.manifest.doc_id for d in documents if d.review.status=='approved' and not d.stale])

@app.post('/api/export', response_model=ExportSummary)
def export_manifest():
    summary=export_summary()
    destination=RUN/'reviews';destination.mkdir(exist_ok=True)
    temporary=destination/'manifest.tmp'
    temporary.write_text(summary.model_dump_json(indent=2)+'\n',encoding='utf-8')
    temporary.replace(destination/'manifest.json')
    return summary

@app.get('/api/stats', response_model=dict[str,int])
def stats():
    documents=docs()
    return {status:sum(d.review.status==status for d in documents) for status in ['todo','in_review','approved','flagged','rejected']}

web = ROOT / 'app/web/dist'
if web.exists(): app.mount('/', StaticFiles(directory=web, html=True), name='web')
