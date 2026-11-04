"""Cross-statement financial-report invariants and cash-flow corrections."""
from factory.content.numbers import solve


def apply(config, clean, statements):
    if 'B03_table' not in statements or 'B01_table' not in statements:
        return
    cash=statements['B01_table']['values'].get('110',[0,0])
    metadata=statements['B03_table']
    given={row['code']:list(row['values']) for row in clean['B03_table']['rows']}
    changes=[]
    opening=list(given.get('60',[0,0]))
    given['60']=[cash[1],opening[1]]
    if given['60']!=opening:
        changes.append({'code':'60','written':opening,'printed':list(given['60']),
                        'reason':'B03.60 current = B01.110 prior'})
    originals={code:list(given.get(code,[0,0])) for code in ('16','17')}
    given['16']=[max(0,value) for value in originals['16']]
    given['17']=[min(0,value) for value in originals['17']]
    amounts,_,_=solve(config.statements['B03'],given)
    for period in (0,1):
        gap=cash[period]-amounts['70'][period]
        given['16' if gap>=0 else '17'][period]+=gap
    for code,before in originals.items():
        if given[code]!=before:
            changes.append({'code':code,'written':before,'printed':list(given[code]),
                            'reason':'B03.70 = B01.110 in both periods; receipt >= 0, payment <= 0'})
    amounts,included,log=solve(config.statements['B03'],given)
    log.extend(changes)
    metadata.update(values=amounts,included=sorted(included),adjustments=log)
