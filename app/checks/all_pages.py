import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'OCR_VLM_benchmark_factory'))
from factory.browser.browser import Browser
from PIL import Image,ImageDraw
async def main():
 captures=[];count=0
 async with Browser() as b:
  p=await b.chromium.new_page(viewport={'width':1440,'height':900})
  await p.goto('http://127.0.0.1:8765')
  docs=await (await p.request.get('http://127.0.0.1:8765/api/docs')).json()
  for d in docs:
   await p.goto('http://127.0.0.1:8765');await p.get_by_text(d['subset'],exact=True).click()
   for entry in d['manifest']['pages']:
    if entry['index'] > 1:
     async with p.expect_response(lambda r: r.url.endswith('/pages/'+str(entry['index']))):
      await p.locator('nav button').nth(entry['index']-1).click()
    await p.wait_for_function('document.querySelector(".sheet img")?.complete')
    await p.wait_for_selector('.sheet svg polygon')
    expected=len(next(x for x in d['boxes']['pages'] if x['index']==entry['index'])['blocks'])
    await p.wait_for_function('(n)=>document.querySelectorAll(".sheet svg polygon").length===n',arg=expected)
    target=f"app/checks/{d['subset']}_{entry['index']:03}.png"
    await p.locator('.sheet').screenshot(path=target);captures.append(target);count+=1
  async def mismatch(route):
   response=await route.fetch();data=await response.json();data['size_matches']=False;data['image_width']+=1
   await route.fulfill(response=response,json=data)
  await p.route('**/pages/1',mismatch)
  await p.locator('nav button').first.click();await p.get_by_role('alert').wait_for()
  assert await p.locator('.sheet svg').count()==0
  print(f'PASS: {count} UI pages, expected polygon counts, mismatch shows alert and zero SVG')
 sheet=Image.new('RGB',(8*210,4*320),'#ddd')
 for i,path in enumerate(captures):
  im=Image.open(path);im.thumbnail((200,300));sheet.paste(im,((i%8)*210,(i//8)*320));ImageDraw.Draw(sheet).text(((i%8)*210,(i//8)*320+300),Path(path).stem,fill='black')
 sheet.save('app/checks/all_pages.png')
asyncio.run(main())
