import asyncio,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'OCR_VLM_benchmark_factory')]
from factory.browser.browser import Browser
import httpx
run=ROOT/'OCR_VLM_benchmark_factory/out/uniqueness_phase0_attempt3'
review=run/'en_long/reviews/academic_paper_000001.json'
assert not review.exists(),'Refusing to replace an existing review'
def start():
 proc=subprocess.Popen([sys.executable,'-m','uvicorn','app.server.main:app','--port','8766'],cwd=ROOT,env={**os.environ,'GT_RUN':str(run)},stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
 for _ in range(100):
  try:
   if httpx.get('http://127.0.0.1:8766/api/docs').status_code==200:return proc
  except httpx.ConnectError:pass
  time.sleep(.1)
 raise RuntimeError('server failed to start')
async def main():
 proc=start()
 try:
  async with Browser() as browser:
   p=await browser.chromium.new_page();await p.goto('http://127.0.0.1:8766');await p.get_by_text('en_long',exact=True).click()
   await p.wait_for_selector('.sheet svg polygon')
   import io
   from PIL import Image
   response=httpx.get('http://127.0.0.1:8766/api/docs/en_long/academic_paper_000001/pages/1')
   data=response.json();w=data['image_width'];h=data['image_height']
   data['image_width']=w*2
   pagebox=data['document']['boxes']['pages'][0];pagebox['image_width']=w*2
   pagebox['blocks']=[dict(block,poly=[v+w if i%2==0 else v for i,v in enumerate(block['poly'])]) for block in pagebox['blocks']]
   data['document']['manifest']['pages'][0]['kind']='spread'
   image=Image.open(io.BytesIO(httpx.get('http://127.0.0.1:8766/api/docs/en_long/academic_paper_000001/pages/1/image').content))
   spread=Image.new('RGB',(w*2,h),'white');spread.paste(image,(w,0));out=io.BytesIO();spread.save(out,format='PNG')
   await p.route('**/pages/1',lambda route:route.fulfill(json=data))
   await p.route('**/pages/1/image',lambda route:route.fulfill(body=out.getvalue(),content_type='image/png'))
   await p.reload();await p.get_by_text('en_long',exact=True).click();await p.wait_for_selector('.sheet svg polygon')
   assert await p.locator('.sheet svg').get_attribute('viewBox')==f'0 0 {w*2} {h}'
   first=await p.locator('.sheet svg polygon').first.get_attribute('points')
   assert float(first.strip().split(',')[0])>w
   await p.screenshot(path='app/checks/spread.png')
   print('PASS: synthetic spread keeps 2:1 width and correctly shifts polygons to the right leaf')
 finally:
  proc.kill();proc.wait()
  if review.exists():review.unlink()
asyncio.run(main())
