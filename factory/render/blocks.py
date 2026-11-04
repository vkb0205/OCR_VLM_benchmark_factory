"""Turn validated content into semantic blocks, HTML fragments and SVG assets."""
from dataclasses import dataclass, field
from html import escape
import re

from factory.content.numbers import format_vnd
from factory.content.schema import FONT
from factory.contract.extract import parse_html, table_html
from factory.contract.models import Block
from factory.contract.models.docir import (ChartContent, EquationContent, EquationInlineSpan, FigureContent,
                                         FootnoteMarkSpan, MarkContent, TableContent, TextContent, TextSpan)
from factory.render.marks import PALETTES, chart_svg, logo_svg, seal_svg, signature_svg, styled
from factory.render.academic import figure_svg, spans_html, table_fragment

SIZES = {'a4': (210, 297), 'a4_landscape': (297, 210), 'a3': (297,420), 'a3_landscape': (420,297), 'letter': (215.9,279.4), 'letter_landscape': (279.4,215.9), 'legal': (215.9,355.6), 'legal_landscape': (355.6,215.9)}


@dataclass
class Filled:
    blocks: dict[str, Block] = field(default_factory=dict)
    inner: dict[str, str] = field(default_factory=dict)
    tables: dict[str, tuple[str, list[str]]] = field(default_factory=dict)
    slot_of: dict[str, dict] = field(default_factory=dict)
    assets: dict[str, bytes] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


def text_html(text):
    return escape(text).replace('\n', '<br>')


NUMBER_CELL = re.compile(r'^\(?-?[0-9]{1,3}(?:[.,][0-9]{3})+\)?$')


def cells(tag, values):
    """Table cells; amounts like 1.650.000.000 get class "num" so a narrow column never breaks them."""
    return ''.join(
        f'<{tag} class="num">{escape(str(v))}</{tag}>' if tag == 'td' and NUMBER_CELL.match(str(v).strip())
        else f'<{tag}>{escape(str(v))}</{tag}>'
        for v in values)


def _academic_spans(spans):
    result = []
    for span in spans:
        if span['type'] == 'text':
            result.append(TextSpan(text=span['text']))
        elif span['type'] == 'equation_inline':
            result.append(EquationInlineSpan(latex=span['latex']))
        elif span['type'] == 'footnote_mark':
            result.append(FootnoteMarkSpan(text=span['text'], target=span.get('target')))
    return result


def _academic_text(spans):
    return ''.join(span.text if span.type != 'equation_inline' else f'${span.latex}$' for span in spans)


def _academic_article(content, filled, field_config, body, rng, add):
    """Build semantic child blocks for the article field; fill adds final GT labels."""
    from factory.content.article import WORDS
    from factory.contract.extract import table_html

    words = WORDS[content.lang if content.lang in {'vi', 'en'} else content.config.lang]
    fragments = []

    def ident(source, index, prefix):
        if source:
            return 'paper_' + source.replace(':', '_')
        return f'paper_{prefix}_{index:02}'

    def text_block(bid, category, spans, tag='p', parent=None, attrs=None, cls=''):
        models = _academic_spans(spans)
        rendered = spans_html(spans)
        class_attr = f' class="{escape(cls, quote=True)}"' if cls else ''
        inner = f'<{tag}{class_attr} data-block="{escape(bid, quote=True)}">{rendered}</{tag}>'
        add(bid, TextContent(spans=models), inner, cat=category, parent=parent, attrs=attrs)
        return inner

    for index, element in enumerate(body, 1):
        kind = element['type']
        bid = ident(element.get('id'), index, kind)
        if kind == 'heading':
            spans = element['resolved_spans']
            fragments.append(text_block(bid, 'section_header', spans, tag=f'h{element["level"]}'))
        elif kind == 'paragraph':
            fragments.append(text_block(bid, 'text_block', element['resolved_spans']))
        elif kind == 'list':
            tag = 'ol' if element['ordered'] else 'ul'
            parts = [f'<{tag} class="paper-list">']
            for item_index, spans in enumerate(element['item_spans'], 1):
                item_id = f'{bid}_item_{item_index}'
                item_html = spans_html(spans)
                add(item_id, TextContent(spans=_academic_spans(spans)),
                    f'<li data-block="{escape(item_id, quote=True)}">{item_html}</li>', cat='list_item')
                parts.append(filled.inner[item_id])
            parts.append(f'</{tag}>')
            fragments.append(''.join(parts))
        elif kind == 'equation':
            latex = element['latex']
            escaped = escape(latex, quote=True)
            inner = f'<div class="display-equation" data-block="{escape(bid, quote=True)}"><span class="factory-display-math" data-formula="{escaped}"></span></div>'
            add(bid, EquationContent(latex=latex), inner, cat='equation_isolated')
            fragments.append(inner)
            if element.get('numbered'):
                caption_id = bid + '_number'
                label = f'({element["number"]})'
                add(caption_id, TextContent(spans=[TextSpan(text=label)]),
                    f'<div class="equation-number" data-block="{escape(caption_id, quote=True)}">{escape(label)}</div>',
                    cat='caption_equation', parent=bid)
                fragments.append(filled.inner[caption_id])
        elif kind == 'table':
            caption_id = bid + '_caption'
            caption = element['caption_printed']
            prefix = caption[:-len(element['caption'])] if element['caption'] else caption
            cap_spans = [{'type': 'text', 'text': prefix}, *element['caption_spans']]
            fragments.append(text_block(caption_id, 'caption_table', cap_spans, cls='paper-caption', parent=bid))
            table_inner, rows = table_fragment(element)
            header_section = table_inner.split('</thead>', 1)[0] + '</thead>'
            header_rows = re.findall(r'<tr>.*?</tr>', header_section)
            table_markup = f'<table class="paper-table table-{element["table_style"]}" data-block="{escape(bid, quote=True)}" data-frame="fewer_line" data-start="0" data-end="{len(rows)}">{table_inner}</table>'
            parsed = parse_html(table_markup)
            canonical = table_html(parsed)
            add(bid, TableContent(html=canonical, header_rows=len(element['header'])), table_markup,
                cat='table', attrs={'frame_type': 'fewer_line'})
            filled.tables[bid] = (''.join(header_rows), rows)
            fragments.append(table_markup)
            if element.get('note'):
                note_id = bid + '_note'
                note_spans = element.get('note_spans') or [{'type': 'text', 'text': element['note_visible']}]
                fragments.append(text_block(note_id, 'footnote', note_spans, cls='table-note', parent=bid))
        elif kind == 'chart':
            caption_id = bid + '_caption'
            caption = element['caption_printed']
            prefix = caption[:-len(element['caption'])] if element['caption'] else caption
            fragments.append(text_block(caption_id, 'caption_chart', [{'type': 'text', 'text': prefix}, *element['caption_spans']], cls='paper-caption', parent=bid))
            data = {'chart_type': element['chart_type'], 'labels': element['labels'], 'series': element['series'],
                    'x_label': element.get('x_label'), 'y_label': element.get('y_label'),
                    'legend_position': element.get('legend_position', 'outside'),
                    'gridlines': element.get('gridlines', True), 'academic': True}
            add(bid, ChartContent(chart_type=data['chart_type'], data=data), chart_svg(data), cat='chart')
            fragments.append(f'<figure class="paper-chart" data-block="{escape(bid, quote=True)}">{chart_svg(data)}</figure>')
        elif kind == 'figure':
            caption_id = bid + '_caption'
            caption = element['caption_printed']
            prefix = caption[:-len(element['caption'])] if element['caption'] else caption
            fragments.append(text_block(caption_id, 'caption_figure', [{'type': 'text', 'text': prefix}, *element['caption_spans']], cls='paper-caption', parent=bid))
            svg = figure_svg(rng, element)
            asset = f'assets/{bid}.svg'
            filled.assets[asset.removeprefix('assets/')] = svg.encode('utf-8')
            add(bid, FigureContent(asset=asset, description=element['description']),
                f'<figure class="paper-figure" data-block="{escape(bid, quote=True)}"><img src="{escape(asset, quote=True)}" alt=""></figure>',
                cat='figure')
            fragments.append(filled.inner[bid])
        elif kind == 'code':
            lines = list(element['lines'])
            code_spans = []
            if element.get('caption'):
                prefix = element['caption_printed'][:-len(element['caption'])] if element['caption'] else ''
                code_spans.extend([TextSpan(text=prefix), *_academic_spans(element.get('caption_spans', [{'type': 'text', 'text': element['caption']}]))])
                code_spans.append(TextSpan(text='\n'))
            code_spans.append(TextSpan(text='\n'.join(lines)))
            output = _academic_text(code_spans)
            code_html = escape(output).replace('\n', '<br>')
            add(bid, TextContent(spans=code_spans),
                f'<pre class="paper-code" data-block="{escape(bid, quote=True)}"><code>{code_html}</code></pre>', cat='code_block')
            fragments.append(filled.inner[bid])
        elif kind == 'box':
            spans = [{'type': 'text', 'text': element['title'] + ' '}, *element['text_spans']]
            fragments.append(text_block(bid, 'text_block', spans, tag='aside', attrs={'style': 'callout'}, cls='paper-callout ' + element['kind']))

    for footnote in content.values.get('_academic_footnotes', []):
        bid = footnote['id']
        visible = f'{footnote["number"]}. {footnote["text"]}'
        add(bid, TextContent(spans=[TextSpan(text=visible)]),
            f'<p data-block="{escape(bid, quote=True)}"><sup>{footnote["number"]}.</sup> {escape(footnote["text"])}</p>',
            cat='footnote')
        fragments.append(filled.inner[bid])
    filled.inner[field_config.id] = ''.join(fragments)


def build_blocks(content, rng):
    filled = Filled()
    for f in content.config.fields:
        sid, kind, value = f.id, f.kind, content.values[f.id]
        if f.optional and value is None:
            continue
        slot = f.model_dump(exclude_none=True)

        def add(bid, body, inner=None, *, cat=None, parent=None, lang=None, attrs=None):
            text_cats = {'text_block', 'title', 'section_header', 'reference', 'footnote', 'header',
                         'footer', 'page_number', 'caption_table', 'caption_figure', 'caption_chart',
                         'caption_equation', 'list_item', 'code_block'}
            block_lang = lang or (content.field_lang(f) if kind in {'text', 'notes', 'kpis', 'authors', 'references', 'article'} else None)
            filled.blocks[bid] = Block(id=bid, cat=cat or f.cat, section=f.section,
                parent=f.parent if parent is None else parent, lang=block_lang if (cat or f.cat) in text_cats else None,
                attrs=attrs or {}, content=body)
            filled.slot_of[bid] = slot
            if inner is not None: filled.inner[bid] = inner

        def colors():
            return value.get('colors') or PALETTES[rng.randrange(len(PALETTES))]

        if kind=='text':
            if content.config.document_type == 'academic_paper' and sid in {'abstract', 'abstract_alt', 'keywords', 'keywords_alt', 'acknowledgement'}:
                from factory.content.article import WORDS
                label_key = 'abstract' if sid.startswith('abstract') else 'keywords' if sid.startswith('keywords') else 'acknowledgement'
                label_lang = content.field_lang(f)
                label = WORDS[label_lang][label_key]
                add(f'{sid}_heading', TextContent(spans=[TextSpan(text=label)]), text_html(label),
                    cat='section_header', lang=label_lang)
            for i,text in enumerate(value if f.many else [value],1):
                add(f'{sid}_{i}' if f.many else sid, TextContent(spans=[TextSpan(text=text)]),text_html(text))
        elif kind == 'authors':
            for index, author in enumerate(value, 1):
                markers = ', '.join(str(number) for number in author['affiliations'])
                display = author['name'] + f' ({markers})'
                if author.get('email'):
                    display += ', ' + author['email']
                add(f'{sid}_{index}', TextContent(spans=[TextSpan(text=display)]), text_html(display))
        elif kind == 'references':
            from factory.content.article import WORDS
            label = WORDS[content.block_lang]['references']
            add(f'{sid}_heading', TextContent(spans=[TextSpan(text=label)]), text_html(label), cat='section_header')
            for index, reference in enumerate(value, 1):
                add(f'{sid}_{index}', TextContent(spans=[TextSpan(text=reference['text'])]),
                    text_html(reference['text']), cat='reference')
        elif kind == 'article':
            _academic_article(content, filled, f, value, rng, add)
        elif kind in {'notes', 'kpis'}:
            def text_block(bid, text, cat='text_block', parent=None):
                add(bid, TextContent(spans=[TextSpan(text=text)]), text_html(text))
                filled.blocks[bid].cat = cat
                filled.blocks[bid].parent = parent
                filled.blocks[bid].lang = f.lang or content.block_lang
            for i, item in enumerate(value, 1):
                bid = f'{sid}_{i}'
                if kind == 'kpis':
                    value_text = format_vnd(item['value'],content.lang or 'vi') if type(item['value']) is int else item['value']
                    text_block(bid, f"{item['label']}: {value_text} {item['unit']}")
                    continue
                text_block(bid, item['title'], 'section_header')
                for j, paragraph in enumerate(item['paragraphs'], 1):
                    text_block(f'{bid}_p{j}', paragraph, parent=bid)
                if item['table'] is not None:
                    tid = f'{bid}_table'
                    table = item['table']
                    head = '<tr>' + cells('th', table['header']) + '</tr>'
                    rows = ['<tr>' + cells('td', r) + '</tr>' for r in table['rows']]
                    filled.tables[tid] = (head, rows)
                    add(tid, TableContent(html=table_html(parse_html(f'<table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>')), header_rows=1))
                    filled.blocks[tid].cat = 'table'
                    filled.blocks[tid].parent = bid
                if item.get('chart') is not None:
                    chart = item['chart']
                    cid = f'{bid}_chart'
                    data = {'chart_type': chart['chart_type'], 'labels': chart['labels'], 'unit': chart.get('unit', ''),
                            'series': [{'name': s['name'], 'values': [float(x) for x in s['values']]} for s in chart['series']]}
                    data, chart_colors = styled(data, chart.get('colors') or PALETTES[rng.randrange(len(PALETTES))])
                    add(cid, ChartContent(chart_type=data['chart_type'], data=data), chart_svg(data, chart_colors))
                    filled.blocks[cid].cat, filled.blocks[cid].parent = 'chart', bid
                    text_block(f'{cid}_caption', chart['caption'], 'caption_chart', cid)
        elif kind in {'table','statement'}:
            if kind=='statement':
                spec=content.config.statements[f.lines]
                metadata=content.statements[sid]
                totals={formula.split('=')[0].strip() for formula in spec.get('formulas',[])}
                rows, row_meta, cell_map = [], [], []
                for code,level,label in spec['lines']:
                    if code not in metadata['included']: continue
                    amounts=metadata['values'][code]
                    values=[label,code,metadata['notes'].get(code,'')]+[format_vnd(v,content.lang or 'vi') for v in amounts]
                    cls=f'level-{level}'+(' total' if code in totals else '')
                    rows.append(f'<tr class="{cls}">'+cells('td',values)+'</tr>')
                    row_meta.append({'code':code,'level':level,'is_total':code in totals})
                    for period,amount in enumerate(amounts):
                        cell_map.append({'block':sid,'row':len(rows)-1,'column':3+period,'code':code,'period':period,'value':amount})
                head='<tr>'+cells('th',f.columns)+'</tr>'
                filled.extra.setdefault('statements',{})[sid]={'values':metadata['values'],'rows':row_meta,'cells':cell_map,'adjustments':metadata['adjustments']}
            else:
                head='<tr>'+cells('th',value['header'])+'</tr>'
                rows=['<tr>'+cells('td',row)+'</tr>' for row in value['rows']]
            filled.tables[sid]=(head,rows)
            add(sid,TableContent(html=table_html(parse_html(f'<table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>')),header_rows=1))
        elif kind=='chart':
            data={'chart_type':value['chart_type'],'labels':value['labels'],
                'series':[{'name':s['name'],'values':[float(v) for v in s['values']]} for s in value['series']], 'unit':value.get('unit','')}
            data,chart_colors=styled(data,colors())
            add(sid,ChartContent(chart_type=data['chart_type'],data=data),chart_svg(data,chart_colors))
        elif kind=='figure':
            filled.assets[f'{sid}.svg']=logo_svg(rng,value['motif'],styled({'chart_type':'logo'},colors())[1][:2]).encode()
            add(sid,FigureContent(asset=f'assets/{sid}.svg',description=value['description']))
        elif kind=='signature':
            svg=signature_svg(rng)
            filled.assets[f'{sid}.svg']=svg.encode()
            add(sid,MarkContent(asset=f'assets/{sid}.svg'),svg)
        elif kind=='seal':
            svg=seal_svg(value['text'])
            filled.assets[f'{sid}.svg']=svg.encode()
            add(sid,MarkContent(asset=f'assets/{sid}.svg',value=value['text']),svg)
    return filled
