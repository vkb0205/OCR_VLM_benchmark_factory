"""Occupied semantic-block area within the page's content rectangle."""
import math
from statistics import median


def union_area(rectangles):
    """Exact rectangle union; overlapping marks never inflate page fill."""
    if not rectangles: return 0.0
    xs=sorted({x for a,_,b,_ in rectangles for x in (a,b)})
    area=0.0
    for left,right in zip(xs,xs[1:]):
        spans=sorted((top,bottom) for x,top,end,bottom in rectangles if x<right and end>left)
        length=0; end=-math.inf
        for top,bottom in spans:
            length+=max(0,bottom-max(top,end));end=max(end,bottom)
        area+=(right-left)*length
    return area


async def page_fill(folder,manifest,browser):
    results=[]
    for i,entry in enumerate(manifest.pages):
        async with browser.page(folder/entry.file) as (page,blocked,failed):
            if blocked or failed: raise ValueError('Page-fill assets failed')
            boxes=await page.evaluate('''() => {
              const main=document.querySelector('main'), r=main.getBoundingClientRect();
              const rect=x=>[x.left,x.top,x.right,x.bottom];
              return {main:rect(r),blocks:[...main.querySelectorAll('[data-gt-id]')].map(e=>rect(e.getBoundingClientRect()))};
            }''')
        l,t,r,b=boxes['main']
        rectangles=[(max(l,x),max(t,y),min(r,z),min(b,w)) for x,y,z,w in boxes['blocks'] if min(r,z)>max(l,x) and min(b,w)>max(t,y)]
        fraction=union_area(rectangles)/((r-l)*(b-t))
        section_end=i==len(manifest.pages)-1 or manifest.pages[i+1].role!=entry.role
        excluded=entry.role in {'cover','signature','signatures'} or section_end
        results.append({'index':entry.index,'role':entry.role,'fill':round(fraction,6),'eligible':not excluded,
            'body_eligible':entry.role not in {'cover','signature','signatures'},'section_end':section_end,
            'exclusion':'cover/signatures' if entry.role in {'cover','signature','signatures'} else 'section_end' if section_end else None})
    return results


def distribution(pages):
    def stats(rows):
        xs=sorted(x['fill'] for x in rows)
        if not xs:return {'count':0}
        return {'count':len(xs),'min':xs[0],'p10':xs[int((len(xs)-1)*.1)],'median':median(xs),'p90':xs[int((len(xs)-1)*.9)],'max':xs[-1],
            'at_least_50':sum(x>=.5 for x in xs),'at_least_50_fraction':sum(x>=.5 for x in xs)/len(xs),
            'below_30':sum(x<.3 for x in xs),
            'at_least_60':sum(x>=.6 for x in xs),'at_least_60_fraction':sum(x>=.6 for x in xs)/len(xs),
            'bins':{'0–20%':sum(x<.2 for x in xs),'20–40%':sum(.2<=x<.4 for x in xs),'40–60%':sum(.4<=x<.6 for x in xs),'60–80%':sum(.6<=x<.8 for x in xs),'80–100%':sum(x>=.8 for x in xs)}}
    return {'all_pages':stats(pages),'eligible_pages':stats([x for x in pages if x['eligible']]),
            'body_pages':stats([x for x in pages if x.get('body_eligible',x.get('role') not in {'cover','signature','signatures'})])}
