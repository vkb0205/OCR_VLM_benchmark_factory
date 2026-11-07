import tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from fastapi.testclient import TestClient
from app.server import main
with tempfile.TemporaryDirectory() as temp:
 original=main.reviews.review_path
 main.reviews.review_path=lambda f:Path(temp)/f.parents[2].name/'reviews'/(f.name+'.json')
 c=TestClient(main.app);docs=c.get('/api/docs').json();d=docs[0];base=f"/api/docs/{d['subset']}/{d['manifest']['doc_id']}"
 for n in range(1,d['manifest']['page_count']+1):
  bid=d['boxes']['pages'][n-1]['blocks'][0]['id']
  payload=dict(version=0,reviewer='test',verdict='correct',note='persist')
  assert c.put(f'{base}/pages/{n}/blocks/{bid}',json=payload).status_code==200
  assert c.put(f'{base}/pages/{n}/blocks/{bid}',json=payload).status_code==409
  assert c.put(f'{base}/pages/{n}/decision',json=dict(version=1,reviewer='test',decision='approved')).status_code==200
 bid=d['boxes']['pages'][0]['blocks'][0]['id']
 poly=[10,10,100,10,100,40,10,40]
 assert c.put(f'{base}/pages/1/blocks/{bid}',json=dict(version=2,reviewer='test',verdict='box_off',fix=dict(poly=poly,cat='title',attrs={}))).status_code==200
 order=[b['id'] for b in reversed(d['boxes']['pages'][0]['blocks'])]
 assert c.put(f'{base}/pages/1/order',json=dict(version=3,reviewer='test',order=order)).status_code==200
 persisted=TestClient(main.app).get(base).json()['review']['pages']['1']
 assert persisted['blocks'][bid]['fix']['poly']==poly and persisted['order']==order
 fresh=TestClient(main.app).get(base).json();assert fresh['review']['status']=='approved'
 assert len(fresh['review']['history'])==2*d['manifest']['page_count']+2
 assert len({main.reviews.review_path(main.folder(d['subset'],d['manifest']['doc_id'])) for d in docs})==4
 print('PASS: 10 pages, 20 durable changes, 10 stale-version conflicts, approved derived status, 4 subset-isolated files')
 main.reviews.review_path=original
