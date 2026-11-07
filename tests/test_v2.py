from factory.content.language import choose_language,leakage
from factory.design.draws import draws,design_seed
from factory.content.config import load_config
from factory.content.schema import validate_content
from factory.content.pool import mixed_case
from factory.render.blocks import SIZES
from pathlib import Path
import json

def test_fixture():
    config=load_config().documents['financial_report']
    values=json.loads(Path('tests/fixtures/financial_report_content.json').read_text(encoding="utf-8"))['values']
    validate_content(config,values,lang='vi',variables={k:v[0] for k,v in config.variables.items()})
def test_balance():
    counts={'vi':0,'en':0}
    for seed in range(100):counts[choose_language(counts,seed)]+=1
    assert counts=={'vi':50,'en':50}
    assert leakage('The company and the auditors are working with the board prospectively.','vi')
def test_draws_and_pool():
    assert draws(1)==draws(1)!=draws(2)
    assert design_seed(1,0)!=design_seed(1,1)
    assert mixed_case('CÔNG TY CỔ PHẦN AN BÌNH')[1]=='An Bình'
    assert mixed_case('CÔNG TY AN BÌNH')[1]=='An Bình'
    assert SIZES['legal']==(215.9,355.6)

def test_design_rejects_off_draw_and_copied_ledger(tmp_path):
    from factory.design.checks import check
    d=draws(99);spec={'seed':99,'draws':d,'skipped':[]}
    for name,nums in d.items():
        options=[f'{name} option {i}' for i in range(10)];index=int(round(nums[0],4)*10)
        spec[name]={'options':options,'index':index,'chosen':options[index],'details':{}}
    spec['style'].update(palette=['#ffffff','#111111','#1155aa'],fonts=['Example Head','Example Body'])
    spec['orientation']['pages']={'page_001':'a4'}
    (tmp_path/'design_spec.json').write_text(json.dumps(spec), encoding="utf-8")
    (tmp_path/'design').mkdir()
    (tmp_path/'design/design.html').write_text('<section class="page" data-size="a4"></section>', encoding="utf-8")
    (tmp_path/'pages').mkdir()
    assert check(tmp_path)==[]
    assert any('too similar to a recent design' in p for p in check(tmp_path,[spec]))
    spec['layout']['index']=(spec['layout']['index']+1)%10
    (tmp_path/'design_spec.json').write_text(json.dumps(spec), encoding="utf-8")
    warnings=[]
    assert check(tmp_path,warnings=warnings)==[] and any('does not follow' in w for w in warnings)

def test_chart_forms():
    from factory.render.marks import chart_svg
    from xml.etree import ElementTree
    for form in ['hbar','grouped_column','dot','lollipop','area','stacked_bar']:
        svg=chart_svg({'chart_type':form,'labels':['2024','2025'],'series':[{'name':'Revenue','values':[1,2]}]})
        assert ElementTree.fromstring(svg).tag.endswith('svg')

def test_language_number_formats():
    from factory.content.numbers import format_vnd,parse_vnd
    for lang,text in [('vi','(1.234.567)'),('en','(1,234,567)')]:
        assert format_vnd(-1234567,lang)==text
        assert parse_vnd(text,lang)==-1234567


def test_written_amounts_and_empty_cells_are_fixed_locally():
    from factory.content.schema import amount, cell, number
    assert [amount(x) for x in ['425000000', '1.234.567', '1,234,567', '(12.000)', 7.0]] == [
        425000000, 1234567, 1234567, -12000, 7]
    assert amount('12,5') == '12,5' and amount(5.5) == 5.5   # still rejected by the type check
    assert number('3.5') == 3.5 and cell('') == '-' and cell(None) == '-'


def test_kpis_wait_for_statements_and_notes_problems_route_to_note_fields():
    import random
    from factory.agent import DocumentAgent
    from factory.content.config import load_config

    class Trace: events = []; doc_id = 'x'
    class Ctx: trace = Trace(); llm = None; rng = random.Random(1)
    config = load_config().documents['financial_report'].for_lang('vi')
    variables = {key: choices[0] for key, choices in config.variables.items()} | {'lang': 'vi'}
    agent = DocumentAgent(config, variables, Ctx(), 'vi', 1, [], doc_type='financial_report')
    kpis = [{'label': 'Doanh thu thuần', 'value': 1, 'unit': 'VND', 'source': 'B02.10'}]
    assert agent._kpi_waiting(kpis, {})
    assert not agent._kpi_waiting(kpis, {'B02_table': {}})
    notes = agent.pool.config['notes']
    routed = agent._error_fields([f'{notes}: text must be a non-empty string'], agent.requested_ids)
    assert list(routed) == ['note_tables']


def test_design_spelling_is_fixed_locally():
    from factory.content.config import load_config
    from factory.contract.models import DesignSpec
    from factory.contract.taxonomy import Taxonomy
    from factory.design.tidy import label_category, tidy_design
    config = load_config().documents['financial_report'].for_lang('vi')
    known = set(Taxonomy().text)
    assert label_category('document_title', known) == 'title'
    assert label_category('running_footer', known) == 'footer'
    assert label_category('taxonomy_category', known) == 'text_block'
    html = ('<section class="page" data-size="a4"><h1 data-label="report_title" onclick="x">T</h1>'
            '<div data-slot="B01_table"></div><table data-slot="B02_table" data-frame="grid"></table></section>')
    fixed, notes = tidy_design(html, config, Taxonomy(), seed=1)
    assert 'data-label="title"' in fixed and 'onclick' not in fixed
    assert fixed.count('<table') == 2 and 'data-frame="grid"' not in fixed and len(notes) == 8
    spec = DesignSpec.model_validate({'layout': {}, 'style': {}, 'orientation': {},
                                      'reading_order': {'details': 'DOM order', 'reordered_block_ids': None}})
    assert spec.reading_order.details == {'rule': 'DOM order'}


def test_loose_style_moves_into_head():
    from factory.content.config import load_config
    from factory.contract.taxonomy import Taxonomy
    from factory.design.tidy import tidy_design
    config = load_config().documents['financial_report'].for_lang('vi')
    html = '<style>.page{display:flex}</style><section class="page" data-size="a4"></section>'
    fixed, notes = tidy_design(html, config, Taxonomy())
    assert fixed.startswith('<!doctype html><html><head><meta charset="utf-8"><style>.page{display:flex}</style></head>')
    assert '<body><section class="page"' in fixed and fixed.count('<style') == 1
    whole = '<!doctype html><html><head><style>a{}</style></head><body><section class="page"></section></body></html>'
    assert tidy_design(whole, config, Taxonomy())[0] == whole


def test_amounts_follow_document_language():
    from factory.content.schema import amount_cell
    from factory.render import marks
    assert amount_cell('1650000000', 'vi') == '1.650.000.000'
    assert amount_cell('1.650.000.000', 'en') == '1,650,000,000'
    assert amount_cell('(250000000)', 'en') == '(250,000,000)'
    assert amount_cell('2024', 'en') == '2024' and amount_cell('Raw materials', 'vi') == 'Raw materials'
    token = marks.LANG.set('en')
    try:
        assert marks.number(1900.5) == '1,900.5'
    finally:
        marks.LANG.reset(token)
    assert marks.number(1900.5) == '1.900,5'


def test_long_chart_text_stays_inside():
    from factory.render.marks import chart_svg
    svg = chart_svg({'chart_type': 'bar', 'labels': ['Raw materials', 'Work in progress', 'Finished goods',
                                                     'Packaging and supplies', 'Other'],
                     'series': [{'name': 'Packaging and supplies expenditure', 'values': [1, 2, 3, 4, 5]}]})
    assert '<tspan' in svg and 'y="14">Packaging and supplies expenditure' in svg
