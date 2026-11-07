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
   for n in range(1,11):
    await p.wait_for_selector('.sheet svg polygon')
    async with p.expect_response(lambda r:r.request.method=='PUT' and '/blocks/' in r.url):await p.keyboard.press('1')
    async with p.expect_response(lambda r:r.request.method=='PUT' and r.url.endswith('/decision')):await p.keyboard.press('a')
    if n<10:
     async with p.expect_response(lambda r:r.url.endswith('/pages/'+str(n+1))):await p.keyboard.press('j')
   proc.kill();proc.wait();proc=start()
   data=httpx.get('http://127.0.0.1:8766/api/docs/en_long/academic_paper_000001').json()
   assert data['review']['status']=='approved' and len(data['review']['history'])==20
   print('PASS: 10 pages reviewed using keyboard, 20 changes survive forced server termination and fresh process')
 finally:
  proc.kill();proc.wait()
  if review.exists():review.unlink()
asyncio.run(main())
