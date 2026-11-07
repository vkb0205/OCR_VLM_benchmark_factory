import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'OCR_VLM_benchmark_factory'))
from factory.browser.browser import Browser
async def main():
 async with Browser() as b:
  page=await b.chromium.new_page(viewport={'width':1440,'height':900})
  await page.goto('http://127.0.0.1:8765')
  await page.get_by_text('en_long',exact=True).click()
  await page.wait_for_selector('.sheet svg polygon')
  await page.screenshot(path='app/checks/viewer.png')
  assert await page.locator('.sheet svg polygon').count()>0
  await page.keyboard.press('Tab');await page.keyboard.press('j')
  await page.wait_for_function("document.querySelector('header').textContent.includes('Page 2 /')")
  print('PASS: viewer loads, polygons drawn, Tab and J navigate')
asyncio.run(main())
