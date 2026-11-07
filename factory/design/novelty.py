"""Local structural fingerprints; visual embeddings are deliberately excluded."""
from math import sqrt

def fingerprint(plan, direction, measured=None):
    roles={role:{'size':p['size'],'regions':[r['box'] for r in p['regions']],
                 'font_size':p.get('body_font_size_pt')} for role,p in plan['roles'].items()}
    return {'roles':roles,'title':direction.get('title'),'fonts':direction.get('fonts'),
            'leading':direction.get('leading'),'table':direction.get('table'),
            'measured':measured or {}}

def arrangement(fp):
    return {role:{k:v for k,v in p.items() if k in ('size','regions')} for role,p in fp.get('roles',{}).items()}

def structural_distance(a,b):
    keys=('roles','title','fonts','leading','table')
    return sum(a.get(k)!=b.get(k) for k in keys)/len(keys)

def nearest(candidate,archive):
    rows=[(structural_distance(candidate,row.get('fingerprint',{})),row) for row in archive if row.get('fingerprint')]
    return min(rows,key=lambda pair:pair[0]) if rows else None

def same_content_conflict(content_id,candidate,archive):
    return any(row.get('content_id')==content_id and arrangement(candidate)==arrangement(row.get('fingerprint',{})) for row in archive if row.get('fingerprint'))

async def measure(folder,browser):
    """Confirm structural evidence from title and first body page after geometry passes."""
    import json
    from pathlib import Path
    folder=Path(folder)
    pages=json.loads((folder/'document.json').read_text(encoding='utf-8'))['pages']
    found={}
    for role in ('title_page','body'):
        entry=next((p for p in pages if p['role']==role),None)
        if not entry:continue
        async with browser.page(folder/entry['file']) as (page,_,__):
            found[role]=await page.evaluate('''() => {
                const box=n=>{const r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height].map(v=>Math.round(v*25.4/96*100)/100)};
                return {regions:[...document.querySelectorAll('[data-region]')].map(box),
                  slots:[...document.querySelectorAll('[data-slot]')].map(n=>({slot:n.dataset.slot,box:box(n)})),
                  bodyFont:getComputedStyle(document.body).fontFamily,
                  size:getComputedStyle(document.body).fontSize,leading:getComputedStyle(document.body).lineHeight};
            }''')
    return found
