import asyncio,json,sys,tempfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'OCR_VLM_benchmark_factory')]
from app.server import main
from app.server.schema import DecisionWrite,VerdictWrite,Correction,OrderWrite
from factory.runner.export import export
from factory.runner.reviews import report
async def check():
 folders=list(main.scan().items());created=[]
 try:
  for i,((subset,docid),folder) in enumerate(folders):
   path=main.reviews.review_path(folder);assert not path.exists(),'Existing review would be overwritten';created.append(path)
   doc=main.document(subset,docid)
   for page in doc.manifest.pages:
    main.reviews.write(folder,subset,doc.manifest.page_count,page.index,DecisionWrite(version=0,reviewer='export-check',decision='rejected' if i==4 else 'approved'))
   if i==0:
    b=doc.boxes.pages[0].blocks[0];poly=list(b.poly);poly[0]+=1;poly[6]+=1
    main.reviews.write(folder,subset,doc.manifest.page_count,1,VerdictWrite(version=1,reviewer='export-check',verdict='box_off',fix=Correction(poly=poly,cat='title',attrs={'text_background':'single_color'})),b.id)
    reversed_order=[b.id for b in reversed(doc.boxes.pages[0].blocks)]
    main.reviews.write(folder,subset,doc.manifest.page_count,1,OrderWrite(version=2,reviewer='export-check',order=reversed_order))
    expected=poly;corrected=(subset,docid,b.id)
  with tempfile.TemporaryDirectory(prefix='gt-reviewed-export-') as temp:
   result=await export(main.RUN,Path(temp),True);assert result==0
   pages=json.loads((Path(temp)/'dataset.json').read_text(encoding='utf-8'))
   assert len({p['page_info']['image_path'].split('_p')[0] for p in pages})==4
   matches=[d for p in pages if p['page_info']['image_path'].startswith(corrected[0]+'__') for d in p['layout_dets'] if d['factory']['block_id']==corrected[2]]
   assert matches[0]['poly']==expected and matches[0]['category_type']=='title'
   assert matches[0]['attribute']['text_background']=='single_colored'
   first=next(p for p in pages if p['page_info']['image_path'].startswith(corrected[0]+'__'))
   assert [b['factory']['block_id'] for b in first['layout_dets']]==reversed_order
   assert not any('zz_rejected__' in p['page_info']['image_path'] for p in pages)
   print('PASS: 3 plain approved, 1 corrected approved, 1 rejected; corrected polygon/category in dataset.json; rejected omitted; '+str(len(pages))+' pages')
   print(report(main.RUN))
 finally:
  for p in created:
   if p.exists():p.unlink()
with tempfile.TemporaryDirectory(prefix='gt-review-fixtures-') as temporary:
 original=main.RUN
 fixture=Path(temporary)
 for subset in ['en_long','en_medium','vi_long','vi_short']:
  shutil.copytree(original/subset/'documents',fixture/subset/'documents')
 shutil.copytree(original/'vi_short/documents',fixture/'zz_rejected/documents')
 main.RUN=fixture
 try: asyncio.run(check())
 finally: main.RUN=original
