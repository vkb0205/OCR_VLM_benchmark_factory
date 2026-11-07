import pytest
from factory.content.config import load_config
from factory.design.direction import draw, build, distance
from factory.design.novelty import fingerprint,nearest,same_content_conflict


def test_direction_seed_archive_rejection_and_geometry():
    c=load_config().documents['academic_paper'].for_lang('en')
    archive=[]
    for seed in range(1,13):
        d=draw(seed,archive)
        assert d==draw(seed,archive)
        assert all(distance(d,r['direction'])>=7 for r in archive)
        assert all(d['title'] != r['direction']['title'] for r in archive[-5:])
        assert all(tuple(d[k] for k in ('grid','title'))!=tuple(r['direction'][k] for k in ('grid','title')) for r in archive)
        assert all(d['title'] != r['direction']['title'] for r in archive[-5:])
        plan,css=build(d,c)
        assert d['fonts'][0] in css
        archive.append({'direction':d})


def test_structural_nearest_and_same_content():
    c=load_config().documents['academic_paper'].for_lang('en')
    d=draw(1);p,_=build(d,c);fp=fingerprint(p,d)
    row={'content_id':'paper_01','fingerprint':fp}
    assert nearest(fp,[row])==(0,row)
    assert same_content_conflict('paper_01',fp,[row])
    assert not same_content_conflict('paper_02',fp,[row])


def test_long_paragraph_overflows_vertically_without_phantom_columns(tmp_path):
    import asyncio
    from factory.browser.browser import Browser
    from factory.design.backbone import REGION_BASE_CSS
    path=tmp_path/'region.html'
    path.write_text('<style>'+REGION_BASE_CSS+'</style><section class="page"><main style="width:100mm;height:80mm"><div data-region="body" style="left:0;top:0;width:100%;height:100%"><p>'+('Research measurements and uncertainty. '*180)+'</p></div></main></section>',encoding='utf-8')
    async def check():
        async with Browser() as browser:
            async with browser.page(path) as (page,_,__):
                result=await page.evaluate("""() => {
                    const p=document.querySelector('p'),r=p.parentElement.getBoundingClientRect(),b=p.getBoundingClientRect();
                    return {fragments:p.getClientRects().length,right:b.right<=r.right+1,tall:b.bottom>r.bottom};
                }""")
                assert result=={'fragments':1,'right':True,'tall':True}
    asyncio.run(check())


@pytest.mark.parametrize('restore_previous',[False,True])
def test_eight_turn_cap_accepts_or_restores_passing_bundle(tmp_path,monkeypatch,restore_previous):
    import asyncio
    from types import SimpleNamespace as NS
    from factory.design import coder
    target=tmp_path/'bundle';target.mkdir()
    (target/'state.txt').write_text('failed latest' if restore_previous else 'passing',encoding='utf-8')
    if restore_previous:
        backup=target.parent/(target.name+'_last_passing');backup.mkdir()
        (backup/'state.txt').write_text('passing',encoding='utf-8')
    accepted=object()
    class Session:
        def __init__(self,agent,content,spec,folder):
            self.target=folder;self.passed=not restore_previous;self.result=accepted
            self.last_passing_result=accepted;self.last_passing_reply='accepted design'
            self.last_problems='latest failed'
    class OfflineTools:
        turns=0
        async def tool_turn(self,*args):
            self.turns+=1
            result=NS(provider='offline',model='fixture',tokens_in=0,tokens_out=0,cost_usd=0,tokens_cached=0,tokens_reasoning=0)
            return NS(result=result,calls=[],message={'role':'assistant','content':'no edits'})
    llm=OfflineTools()
    agent=NS(ctx=NS(llm=llm,trace=NS(events=[])),doc_type='financial_report',system='',
             _design_prompt=lambda *args:'design task\nJSON',latest_design_reply='failed design')
    content=NS(config=NS(design={}))
    monkeypatch.setattr(coder,'DesignSession',Session)
    assert asyncio.run(coder.design_with_tools(agent,content,NS(doc_id='offline'),target)) is accepted
    assert llm.turns==8
    assert (target/'state.txt').read_text(encoding='utf-8')=='passing'
    if restore_previous: assert agent.latest_design_reply=='accepted design'


def test_hue_and_sheet_size_do_not_rescue_repeated_layout():
    from copy import deepcopy
    first=draw(1)
    archive=[]
    for size in ('a4','letter','a3','a4_landscape'):
        old=deepcopy(first);old['size']=size;old['accent']='#000000'
        archive.append({'direction':old})
    result=draw(1,archive)
    assert (result['grid'],result['title']) != (first['grid'],first['title'])


@pytest.mark.parametrize('count', [1, 2, 4, 7])
def test_diagram_types_preserve_every_label_with_distinct_topology(count):
    from random import Random
    from xml.etree import ElementTree as ET
    from factory.render.academic import figure_svg
    labels = [f'Module {i}' for i in range(count)]
    svgs = {}
    for kind in ('flowchart', 'pipeline', 'architecture', 'block_diagram'):
        svg = figure_svg(Random(1), {'figure_type': kind, 'labels': labels})
        root = ET.fromstring(svg)
        texts = [''.join(n.itertext()) for n in root.iter('{http://www.w3.org/2000/svg}text')]
        assert all(label in texts for label in labels)
        svgs[kind] = svg
    assert len(set(svgs.values())) == 4
    assert '<circle' in svgs['block_diagram']
    assert '<ellipse' in svgs['pipeline']
    assert 'stroke-dasharray' in svgs['architecture']
    if count > 2:
        assert '>Yes</text>' in svgs['flowchart']
        assert '>No</text>' in svgs['flowchart']
