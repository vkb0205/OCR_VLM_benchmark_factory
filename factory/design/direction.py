"""Seeded independent design axes and code-built academic styles."""
import random
from pathlib import Path
import yaml
from factory.paths import ROOT
from factory.design.backbone import default_plan, validate_plan
from factory.design.fonts import registry

AXES = {
 'size': ('a4','letter','a3','a4_landscape'),
 'grid': ('single','equal','asymmetric','three','wide_margin'),
 'title': ('banner','stack','abstract_box','classic','sidebar','masthead'),
 'base': (9,10,11), 'leading': (1.25,1.4,1.55),
 'heading': ('numbered','small_caps','run_in','ruled','band'),
 'accent': ('#174d64','#753528','#345737','#583e76','#222222'),
 'accent_use': ('rules','headings','table','none'),
 'table': ('booktabs','zebra','grid','header_fill'),
 'caption': ('italic','ruled','compact'),
 'frame': ('left','center','right'), 'figures': ('here','top_column','next_page'),
 'density': ('tight','airy'),
}

def distance(a,b):
    return sum(a.get(k)!=b.get(k) for k in AXES) + (a.get('fonts')!=b.get('fonts'))


def draw(seed, archive=(), *, config=None, content_id=None):
    configuration=yaml.safe_load((ROOT/'configs/design.yaml').read_text(encoding='utf-8'))
    settings=configuration.get('direction',{})
    recent=list(archive)[-settings.get('history',12):]
    recent=[r.get('design_spec',r).get('direction',r.get('direction',{})) for r in recent]
    rng=random.Random(seed)
    fonts=registry()
    names=[f['name'] for f in fonts] if isinstance(fonts[0],dict) else [f.name for f in fonts]
    for _ in range(1000):
        d={k:rng.choice(v) for k,v in AXES.items()}
        d['fonts']=rng.sample(names,2)
        if d['grid']=='three': d['size']='a3'
        if recent and d['fonts']==recent[-1].get('fonts'): continue
        if any(d['title']==old.get('title') for old in recent[-settings.get('title_repeat_gap',5):]): continue
        if settings.get('reject_same_grid_title',True) and any(all(d[k]==old.get(k) for k in ('grid','title')) for old in recent): continue
        if all(sum(d.get(k)==old.get(k) for k in AXES)<=settings.get('max_matches',7) for old in recent):
            if config is not None and content_id:
                from factory.design.novelty import fingerprint, same_content_conflict, nearest
                plan,_=build(d,config)
                rows=[r.get('design_spec',r) for r in archive]
                fp=fingerprint(plan,d)
                if same_content_conflict(content_id,fp,rows): continue
                neighbour=nearest(fp,rows)
                if neighbour and neighbour[0] < configuration.get('novelty',{}).get('struct_min',0.15): continue
            return d
    raise ValueError('unable to draw a sufficiently different direction')


def build(direction, config):
    d=direction; plan=default_plan(config)
    size=d['size']
    # Three-column measures need a wider sheet.
    if d['grid']=='three': size='a3'
    for role,p in plan['roles'].items():
        p['size']=size; p['body_font_size_pt']=d['base']
        grid=d['grid'] if role in ('body','references') else ('wide_margin' if d['grid']=='wide_margin' else 'single')
        widths={'single':[100],'equal':[48,48],'asymmetric':[58,38],
                'three':[30,30,30],'wide_margin':[78]}[grid]
        offset=(100-sum(widths)-4*(len(widths)-1))/2
        regions=[]
        for i,w in enumerate(widths):
            regions.append({'name':'body' if i==0 else f'column_{i+1}','chain':i+1,
                            'box':{'x':f'{offset}%','y':'0%','w':f'{w}%','h':'100%'}})
            offset+=w+4
        p['regions']=regions; p['flow']['chains']=list(range(1,len(widths)+1))
        p['float_defaults']['policy']=d['figures']
    if d['title'] in ('abstract_box','sidebar'):
        plan['roles']['title_page']['keep_slot_groups']=True
    validate_plan(plan,config)
    head,body=d['fonts']; accent=d['accent'] if d['accent_use']!='none' else '#222222'
    css=f'''body{{font-family:"{body}";font-size:{d['base']}pt;line-height:{d['leading']};color:#222}}
    [data-gt-cat="title"],[data-gt-cat="section_header"]{{font-family:"{head}"}}
    [data-slot="title"]{{font-family:"{head}";font-size:25pt;line-height:1.15;margin:0 0 6mm}}
    [data-gt-cat="section_header"]{{font-weight:700;margin-top:4mm}}
    table{{border-collapse:collapse;width:100%;font-size:8pt}}th,td{{padding:1.2mm}}
    figure,svg{{max-width:100%}}[data-gt-cat^="caption"]{{font-size:8pt}}
    header,footer,.page-number{{text-align:{d['frame']}}}
    .display-equation,.factory-math{{font-size:8pt!important}}
    p{{overflow-wrap:anywhere;margin-bottom:{'2' if d['density']=='tight' else '4'}mm}}
    '''
    title_fill=accent if d['accent_use']=='headings' else '#222222'
    rule_ink=accent if d['accent_use']=='rules' else '#222222'
    table_ink=accent if d['accent_use']=='table' else '#222222'
    title_styles={
      'banner':f'background:{title_fill};color:white;padding:6mm',
      'stack':'border-left:3mm solid '+rule_ink+';padding-left:5mm;max-width:85%',
      'abstract_box':'border-bottom:1mm solid '+rule_ink+';padding-bottom:5mm',
      'classic':'text-align:center;padding:8mm 6mm',
      'sidebar':'border-left:12mm solid '+rule_ink+';padding-left:6mm',
      'masthead':'border-top:3mm double '+rule_ink+';border-bottom:1mm solid '+rule_ink+';padding:5mm 0',
    }
    css+='[data-slot="title"]{'+title_styles[d['title']]+'}'
    if d['title'] in ('abstract_box','sidebar'):
        left,right = ('37%','59%') if d['title']=='abstract_box' else ('31%','65%')
        css+=f'.role-title_page [data-region="body"]{{display:grid!important;grid-template-columns:{left} {right};column-gap:4%;align-content:start}}'
        css+='.role-title_page [data-slot]{overflow-wrap:anywhere}.role-title_page [data-slot="title"]{grid-column:1 / -1}'
        css+='.role-title_page [data-slot="authors"]{grid-column:1;grid-row:2}.role-title_page [data-slot="affiliations"]{grid-column:1;grid-row:3}'
        css+='.role-title_page [data-slot="abstract"]{grid-column:2;grid-row:2 / span 2}.role-title_page [data-slot="keywords"]{grid-column:2;grid-row:4}'
    if d['title']=='abstract_box': css+='[data-slot="abstract"]{background:#f1f1f1;padding:5mm;border:0.3mm solid #555}'
    if d['heading']=='ruled': css+=f'[data-gt-cat="section_header"]{{border-bottom:.4mm solid {rule_ink}}}'
    if d['heading']=='band': css+=f'[data-gt-cat="section_header"]{{background:{title_fill};color:white;padding:2mm}}'
    if d['heading']=='small_caps': css+='[data-gt-cat="section_header"]{font-variant:small-caps;letter-spacing:.08em}'
    if d['heading']=='run_in': css+='[data-gt-cat="section_header"]{font-style:italic;margin-bottom:0}'
    if d['accent_use']=='headings' and d['heading']!='band': css+=f'[data-gt-cat="section_header"]{{color:{accent}}}'
    if d['table']=='grid': css+='th,td{border:.2mm solid #555}'
    elif d['table']=='zebra': css+='tbody tr:nth-child(even){background:#efefef}'
    elif d['table']=='header_fill': css+=f'th{{background:{table_ink};color:white}}'
    else: css+='thead{border-top:.5mm solid #222;border-bottom:.25mm solid #222}tbody{border-bottom:.5mm solid #222}'
    if d['caption']=='italic': css+='[data-gt-cat^="caption"]{font-style:italic}'
    if d['caption']=='ruled': css+='[data-gt-cat^="caption"]{border-top:.2mm solid #555;padding-top:2mm}'
    if d['accent_use']=='rules': css+=f'section.page>header{{border-bottom:.2mm solid {accent}}}'
    if d['accent_use']=='table' and d['table']!='header_fill': css+=f'thead{{border-color:{accent}}}th{{color:{accent}}}'
    return plan,css

async def check_rendered(folder, direction, browser):
    """Measure the hard typographic axes on actual rendered text and title slots."""
    import json
    manifest=json.loads((Path(folder)/'document.json').read_text(encoding='utf-8'))
    problems=[]
    all_colors=[]
    for entry in manifest['pages']:
        async with browser.page(Path(folder)/entry['file']) as (page,blocked,failed):
            data=await page.evaluate('''() => {
              const title=document.querySelector('[data-slot="title"]');
              const texts=[...document.querySelectorAll('[data-gt-cat="text_block"]')];
              const heads=[...document.querySelectorAll('[data-gt-cat="section_header"], [data-slot="title"]')];
              const t=title?getComputedStyle(title):null;
              return {body:texts.map(n=>getComputedStyle(n).fontFamily),
                heading:heads.map(n=>getComputedStyle(n).fontFamily),
                front:(()=>{const a=document.querySelector('[data-slot=authors]'),b=document.querySelector('[data-slot=abstract]');return a&&b?{a:a.getBoundingClientRect().toJSON(),b:b.getBoundingClientRect().toJSON(),display:getComputedStyle(a.parentElement).display}:null})(),
                title:t?{background:t.backgroundColor,align:t.textAlign,left:parseFloat(t.borderLeftWidth),top:parseFloat(t.borderTopWidth),bottom:parseFloat(t.borderBottomWidth)}:null,
                editorial:[...document.querySelectorAll('[data-slot=title],[data-gt-cat=section_header],header,footer,th,td')].flatMap(n=>{const s=getComputedStyle(n);return [s.color,s.backgroundColor,s.borderTopColor,s.borderLeftColor,s.borderBottomColor,s.borderRightColor]}),
                colors:[...document.querySelectorAll('*')].flatMap(n=>{const s=getComputedStyle(n);return [s.color,s.backgroundColor,s.borderTopColor,s.borderLeftColor,s.borderBottomColor,s.borderRightColor]})};
            }''')
        all_colors.extend(data['colors'])
        for role,index in [('body',1),('heading',0)]:
            if data[role] and not all(direction['fonts'][index].lower() in f.lower() for f in data[role]):
                problems.append(f"direction: {role} font changed on page {entry['index']}")
        rgb=tuple(int(direction['accent'][i:i+2],16) for i in (1,3,5))
        accent='rgb('+', '.join(map(str,rgb))+')'
        if direction['accent_use']=='none':
            import re
            for color in data['editorial']:
                nums=re.findall(r'[\d.]+',color)
                if len(nums)>=3 and len(set(nums[:3]))>1 and (len(nums)<4 or nums[3]!='0'):
                    problems.append('direction: editorial accent must be absent')
                    break
        t=data['title']
        if t:
            kind=direction['title']
            valid={'banner':t['background']!='rgba(0, 0, 0, 0)',
                   'classic':t['align']=='center','stack':t['left']>0,
                   'sidebar':t['left']>35,'masthead':t['top']>0 and t['bottom']>0,
                   'abstract_box':t['bottom']>0}[kind]
            if kind in ('sidebar','abstract_box'):
                f=data['front']
                valid=valid and bool(f) and f['display']=='grid' and f['a']['right']<=f['b']['left']+2 and f['b']['top']<f['a']['bottom']
            if not valid: problems.append('direction: title-block treatment changed')
    if direction['accent_use']!='none' and accent not in all_colors:
        problems.append('direction: accent missing')
    return problems
