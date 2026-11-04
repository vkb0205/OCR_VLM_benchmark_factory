import asyncio,json
from pathlib import Path
from datetime import datetime,timezone
from random import Random
from types import SimpleNamespace
from factory.content.config import load_config
from factory.content.schema import validate_content
from factory.contract.taxonomy import Taxonomy
from factory.contract.models import Trace
from factory.contract.models import SourceContent
from factory.contract.models.spec import DocSpec
from factory.runner.context import Context
from factory.browser.browser import Browser
from factory.design.agent import render_design
from factory.design.draws import draws
from factory.agent import DesignReply
from factory.contract.extract import parse_html
async def run_design(tmp_path):
 c=load_config().documents['financial_report'];v={k:x[0] for k,x in c.variables.items()};content=validate_content(c,json.loads(Path('tests/fixtures/financial_report_content.json').read_text())['values'],variables=v,lang='vi')
 d=draws(99);design={'skipped':[]}
 for name,nums in d.items():
  opts=[f'{name} option {i}' for i in range(10)];index=int(round(nums[0],4)*10);design[name]={'options':opts,'index':index,'chosen':opts[index],'details':{}}
 design['style'].update(palette=['#ffffff','#111111','#1155aa'],fonts=['Noto Serif','Be Vietnam Pro'])
 html=Path('designs/financial_report/default.html').read_text()
 sections=[node for node in parse_html(html).walk() if node.tag=='section' and 'page' in node.attrs.get('class','').split()]
 design['orientation']['pages']={f'page_{i:03}':node.attrs.get('data-size','a4') for i,node in enumerate(sections,1)}
 async with Browser() as b:
  trace=Trace(doc_id='financial_report_000999',factory_version='2',started=datetime.now(timezone.utc))
  ctx=Context(Random(1),None,b,Taxonomy(),trace)
  spec=DocSpec(doc_id='financial_report_000999',doc_type='financial_report',seed=1,variables=v,design_seed=99)
  renderer=SimpleNamespace(ctx=ctx,ledger_entries=[])
  await render_design(renderer,content,spec,tmp_path/'bundle',DesignReply(design_spec=design,css=__import__('re').search(r'<style>(.*?)</style>',html,__import__('re').S).group(1),pages={'B01':{'size':'a4','order':['B01_table'],'frame':'full_line'}}))
  assert (tmp_path/'bundle/design/design_spec.json').exists()

def test_fake_design_render_loop(tmp_path):
    asyncio.run(run_design(tmp_path))

def test_export_fixture_image_sizes(tmp_path):
    import shutil
    from factory.runner.export import export
    async def run():
        await run_design(tmp_path)
        bundle=tmp_path/'documents/financial_report/financial_report_000999'
        bundle.parent.mkdir(parents=True)
        shutil.move(str(tmp_path/'bundle'),str(bundle))
        fixture=json.loads(Path('tests/fixtures/financial_report_content.json').read_text())
        source=SourceContent(variables=fixture.get('variables',{}),lang='vi',pool_entry=None,values=fixture['values'])
        (bundle/'source_content.json').write_text(source.model_dump_json(indent=2)+'\n')
        assert await export(tmp_path,tmp_path/'dataset',allow_imbalance=True)==0
        assert (tmp_path/'dataset/dataset.json').exists()
    asyncio.run(run())
