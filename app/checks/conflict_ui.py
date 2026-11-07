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
   other=await browser.chromium.new_page();await other.goto('http://127.0.0.1:8766');await other.get_by_text('en_long',exact=True).click();await other.wait_for_selector('.sheet svg polygon')
   async with p.expect_response(lambda r:r.request.method=='PUT'):await p.keyboard.press('1')
   async with other.expect_response(lambda r:r.request.method=='PUT') as response:await other.keyboard.press('2')
   assert (await response.value).status==409
   await other.get_by_role('alert').wait_for()
   assert 'another tab' in await other.get_by_role('alert').text_content()
   await p.goto('http://127.0.0.1:8766');await p.get_by_role('button',name='Exports',exact=True).click()
   await p.get_by_role('heading',name='Export review').wait_for()
   await p.get_by_role('button',name='Lint failures',exact=True).click()
   await p.get_by_role('heading',name='Lint failures').wait_for()
   print('PASS: two tabs get visible 409 conflict; Lint and Export screens render')
 finally:
  proc.kill();proc.wait()
  if review.exists():review.unlink()
asyncio.run(main())
