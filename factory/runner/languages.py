"""Language accounting over accepted ground truth."""
import json
from collections import defaultdict

def stats(output):
    result={}
    for path in sorted((output/'documents').glob('*/*/document.json')):
        spec=json.loads((path.parent/'spec.json').read_text());doc=json.loads(path.read_text());ir=json.loads((path.parent/'content.json').read_text())
        key=spec['doc_type'];lang=spec['lang'];row=result.setdefault(key,{}).setdefault(lang,dict(documents=0,pages=0,blocks=0,characters=0,words=0));row['documents']+=1;row['pages']+=doc['page_count']
        for block in ir.get('blocks',[]):
            content=block.get('content',{});text=''.join(span.get('text','') for span in content.get('spans',[]))
            if content.get('kind')=='table':
                from factory.contract.extract import parse_html,extract_text
                text=extract_text(parse_html(content['html']))
            if not text:continue
            row['blocks']+=1;row['characters']+=len(text);row['words']+=len(text.split())
    overall={}
    for languages in result.values():
        for lang,row in languages.items():
            aggregate=overall.setdefault(lang,{key:0 for key in row})
            for key,value in row.items():aggregate[key]+=value
    result['_overall']=overall
    return result

def balance_problems(report):
    errors=[]
    for name,languages in report.items():
        vi=languages.get('vi',{}).get('characters',0);en=languages.get('en',{}).get('characters',0);total=vi+en
        if total and not .45<=vi/total<=.55:errors.append(f'{name}: Vietnamese character share {vi/total:.1%} outside 45–55%')
    return errors
