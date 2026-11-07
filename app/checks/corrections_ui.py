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
   svg=await p.locator('.sheet svg').bounding_box()
   async with p.expect_response(lambda r:r.request.method=='PUT'):
    await p.keyboard.down('Shift');await p.mouse.move(svg['x']+30,svg['y']+30);await p.mouse.down();await p.mouse.move(svg['x']+180,svg['y']+70);await p.mouse.up();await p.keyboard.up('Shift')
   async with p.expect_response(lambda r:r.request.method=='PUT'):
    await p.get_by_label('Category correction').fill('title');await p.get_by_label('Category correction').press('Tab')
   async with p.expect_response(lambda r:r.request.method=='PUT'):
    await p.locator('.blocklist button').first.drag_to(p.locator('.blocklist button').nth(2))
   saved=httpx.get('http://127.0.0.1:8766/api/docs/en_long/academic_paper_000001').json()['review']['pages']['1']
   assert saved['order'] and any(b['fix'] and b['fix']['poly'] and b['fix']['cat']=='title' for b in saved['blocks'].values())
   await p.reload();await p.get_by_text('en_long',exact=True).click();await p.wait_for_selector('.sheet svg polygon')
   assert await p.locator('.blocklist button code').first.text_content()==('1 · '+saved['order'][0])
   print('PASS: Shift+drag box, category edit, drag reading order persist across browser reload')
   proc.kill();proc.wait();proc=start()
 finally:
  proc.kill();proc.wait()
  if review.exists():review.unlink()
asyncio.run(main())
