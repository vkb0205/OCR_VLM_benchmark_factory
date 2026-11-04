"""Normalize and validate content, without HTML or layout."""
from dataclasses import dataclass, field
from pathlib import Path
from copy import deepcopy
import math
import re
import struct

from factory.contract.extract import normalize
from factory.content.numbers import solve, format_vnd
from factory.content.config import TypeConfig
from factory.content.rules import apply_document_rules

FONT = Path(__file__).resolve().parents[1] / 'render/fonts/NotoSerif-Regular.ttf'

# Words that announce invented content; real documents never say them.
META_WORDS = re.compile(r'\b(fictional|fictitious|illustrative|synthetic|placeholder|lorem ipsum|hư cấu)\b', re.I)


def strip_meta_words(value: str) -> str:
    """Drop meta words in code; the model often keeps them through repairs."""
    def drop(match):
        start = match.start()
        before = value[:start].rstrip()
        sentence_start = not before or before[-1] in '.:;!?(\n"\''
        return '\x00' if sentence_start else ''
    out = META_WORDS.sub(drop, value)
    out = re.sub(r'\x00\s*(\w)', lambda m: m.group(1).upper(), out).replace('\x00', '')
    return re.sub(r'\s{2,}', ' ', re.sub(r'\s+([,.;:)])', r'\1', out)).strip()


class ContentError(ValueError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__('\n'.join(self.problems))


def font_coverage(path: Path = FONT) -> set[int]:
    """Code points mapped by the font's format-4 cmap."""
    data = path.read_bytes()
    tables = {struct.unpack_from(">4s", data, 12 + i * 16)[0]: struct.unpack_from(">I", data, 20 + i * 16)[0]
              for i in range(struct.unpack_from(">H", data, 4)[0])}
    cmap, coverage = tables[b"cmap"], set()
    for i in range(struct.unpack_from(">H", data, cmap + 2)[0]):
        platform, _, offset = struct.unpack_from(">HHI", data, cmap + 4 + i * 8)
        start = cmap + offset
        if platform not in (0, 3) or struct.unpack_from(">H", data, start)[0] != 4:
            continue
        n = struct.unpack_from(">H", data, start + 6)[0] // 2
        ends = struct.unpack_from(f">{n}H", data, start + 14)
        starts = struct.unpack_from(f">{n}H", data, start + 16 + 2 * n)
        deltas = struct.unpack_from(f">{n}h", data, start + 16 + 4 * n)
        ranges_at = start + 16 + 6 * n
        ranges = struct.unpack_from(f">{n}H", data, ranges_at)
        for j in range(n):
            for char in range(starts[j], ends[j] + 1):
                if ranges[j]:
                    glyph = struct.unpack_from(">H", data, ranges_at + j * 2 + ranges[j] + 2 * (char - starts[j]))[0]
                    glyph = (glyph + deltas[j]) % 65536 if glyph else 0
                else:
                    glyph = (char + deltas[j]) % 65536
                if glyph:
                    coverage.add(char)
    return coverage


COVERAGE = font_coverage()



@dataclass
class Content:
    config: TypeConfig
    values: dict
    statements: dict = field(default_factory=dict)
    lang: str | None = None
    pool_entry: str | None = None

    @property
    def block_lang(self):
        if self.lang in {'vi','en'}:
            return self.lang
        return self.config.lang

    def field_lang(self, field_config):
        if field_config.lang == 'other':
            if self.lang == 'vi':
                return 'en'
            if self.lang == 'en':
                return 'vi'
            raise ContentError([f'{field_config.id}: lang=other requires a vi or en document'])
        return field_config.lang or self.block_lang


AMOUNT = re.compile(r'^\(?-?[0-9]{1,3}(?:([.,\s])[0-9]{3})?(?:\1[0-9]{3})*\)?$|^\(?-?[0-9]+\)?$')


def amount(x):
    """Whole VND amount from an int, an integral float or a written number like "1.234.567" or "(12)".

    Anything else is returned unchanged so the type check reports it.
    """
    if type(x) is int:
        return x
    if type(x) is float and math.isfinite(x) and x.is_integer():
        return int(x)
    if isinstance(x, str):
        written = x.strip().replace('\u00a0', ' ')
        if written and AMOUNT.match(written):
            negative = written.startswith('(') or written.startswith('-')
            digits = re.sub(r'[^0-9]', '', written)
            return -int(digits) if negative else int(digits)
    return x


def number(x):
    """Chart value: numbers pass, numeric strings are converted, anything else is returned unchanged."""
    if isinstance(x, str):
        try:
            return float(x.strip().replace(',', ''))
        except ValueError:
            return x
    return x


PLAIN_AMOUNT = re.compile(r'^\(?-?[0-9]{5,}\)?$')


def amount_cell(x, lang):
    """A body cell holding a bare amount ("1650000000") is printed as in the statements: 1.650.000.000 / 1,650,000,000.

    Four-digit numbers are left alone (they are usually years).
    """
    text = cell(x)
    written = text.strip()
    if type(x) is int or PLAIN_AMOUNT.match(written) or (AMOUNT.match(written) and len(re.sub(r'[^0-9]', '', written)) >= 5):
        value = amount(text.strip())
        if type(value) is int:
            return format_vnd(value, 'en' if lang == 'en' else 'vi') if value else '0'
    return text


def cell(x):
    """Table cell text; empty cells print as a dash, as in printed financial tables."""
    return '-' if x is None or not str(x).strip() else str(x)


def check_chart(v, text):
    if not isinstance(v, dict) or not isinstance(v.get('labels'), list) or not isinstance(v.get('series'), list):
        raise ValueError('chart labels and series must be lists')
    for series in v['series']:
        if isinstance(series, dict) and isinstance(series.get('values'), list):
            series['values'] = [number(x) for x in series['values']]
    if v['chart_type'] not in {'bar','line','donut'} or not v['labels'] or not 1 <= len(v['series']) <= 3 or any(len(s['values']) != len(v['labels']) or any(type(x) not in (int,float) or not math.isfinite(x) or x < 0 for x in s['values']) for s in v['series']):
        raise ValueError('chart needs finite non-negative values, one per label, and 1-3 series')
    v['labels'] = [text(x) for x in v['labels']]
    for series in v['series']:
        series['name'] = text(series['name'])
    if v.get('unit'): v['unit'] = text(v['unit'])
    return v


def validate_content(config, values, lang=None, variables=None):
    document_lang=lang or config.lang
    if document_lang not in {'vi','en','en_vi_mixed'}:
        raise ContentError([f'Unsupported document language {document_lang!r}'])
    problems, clean, statements = [], {}, {}
    if not isinstance(values, dict):
        raise ContentError(['values must be an object'])
    known = {f.id for f in config.fields}
    problems += [f'Unknown field {key}' for key in values if key not in known]

    def text(value):
        if not isinstance(value, str) or not normalize(value):
            raise ValueError('text must be a non-empty string')
        value = normalize(value)
        missing = sorted({c for c in value if ord(c) not in COVERAGE and not c.isspace()})
        if missing:
            raise ValueError(f'characters {"".join(missing)!r} are not in the font')
        value = strip_meta_words(value)
        if not value:
            raise ValueError('text must say something besides words like fictional or illustrative')
        return value

    for f in config.fields:
        if f.kind == 'signature':
            clean[f.id] = None
            continue
        v = deepcopy(values.get(f.id))
        if f.optional and (v is None or v == '' or v == []):
            clean[f.id] = None
            continue
        try:
            if v is None or v == '' or v == []:
                raise ValueError('Missing value for slot ' + f.id)
            if f.kind == 'text':
                if f.many:
                    if not isinstance(v, list) or not f.many[0] <= len(v) <= f.many[1]:
                        raise ValueError(f'give a list of {f.many[0]}-{f.many[1]} strings')
                    v = [text(x) for x in v]
                else:
                    v = text(v)
            elif f.kind == 'table':
                header, rows = v['header'], v['rows']
                if not isinstance(header, list) or not header or not isinstance(rows, list) or not rows or any(not isinstance(row,list) or len(row) != len(header) for row in rows):
                    raise ValueError('every row needs exactly the header cell count')
                v = {'header': [text(cell(x)) for x in header], 'rows': [[text(amount_cell(x, document_lang)) for x in row] for row in rows]}
            elif f.kind == 'notes':
                if not isinstance(v, list) or not 8 <= len(v) <= 14:
                    raise ValueError('notes needs 8–14 sections')
                for section in v:
                    section['title'] = text(section['title'])
                    paragraphs = section['paragraphs']
                    if not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= 3:
                        raise ValueError('each note needs 1–3 paragraphs')
                    section['paragraphs'] = [text(x) for x in paragraphs]
                    table = section['table']
                    if table is not None:
                        header, rows = table['header'], table['rows']
                        if not isinstance(header, list) or not header or not isinstance(rows, list) or not rows or any(not isinstance(r, list) or len(r) != len(header) for r in rows):
                            raise ValueError('every note table row needs the header cell count')
                        section['table'] = {'header': [text(cell(x)) for x in header], 'rows': [[text(amount_cell(x, document_lang)) for x in r] for r in rows]}
                    if section.get('chart') is not None:
                        section['chart'] = check_chart(section['chart'], text)
                        section['chart']['caption'] = text(section['chart']['caption'])
                if sum(x['table'] is not None for x in v) * 2 < len(v):
                    raise ValueError('at least half of notes need a table')
            elif f.kind == 'kpis':
                if not isinstance(v, list) or not 4 <= len(v) <= 6:
                    raise ValueError('kpis needs 4–6 items')
                for item in v:
                    item['label'], item['unit'] = text(item['label']), text(item['unit'])
                    if type(item['value']) not in (str, int):
                        raise ValueError('KPI value must be an integer or string')
                    if isinstance(item['value'], str): item['value'] = text(item['value'])
                    source = item.get('source')
                    statement_labels={'doanh thu','doanh thu thuần','doanh thu bán hàng','lợi nhuận sau thuế','tổng tài sản','vốn chủ sở hữu'}
                    if not source and item['label'].casefold() in statement_labels and item['unit'].casefold() in {'vnd','vnđ','đồng'}:
                        raise ValueError('statement figure KPI requires source')
                    if source is not None and (not isinstance(source, str) or not re.fullmatch(r'B0[123]\.[0-9]+', source)):
                        raise ValueError('invalid KPI source')
            elif f.kind == 'authors':
                from factory.content.article import check_authors
                v = check_authors(v, text)
            elif f.kind == 'references':
                from factory.content.article import check_references
                v = check_references(v, text)
            elif f.kind == 'article':
                from factory.content.article import check_article
                v = check_article(v, text)
            elif f.kind == 'statement':
                if not isinstance(v, dict) or not isinstance(v.get('rows'), list) or not v['rows']:
                    raise ValueError('statement rows must be a non-empty list')
                given, notes = {}, {}
                catalog = {str(c) for c, _, _ in config.statements[f.lines]['lines']}
                for row in v['rows']:
                    code, amounts = str(row['code']), row['values']
                    if isinstance(amounts, list):
                        amounts = row['values'] = [amount(x) for x in amounts]
                    if code not in catalog:
                        raise ValueError('unknown line code ' + code)
                    if code in given:
                        raise ValueError('duplicate line code ' + code)
                    if not isinstance(amounts,list) or len(amounts) != 2 or any(type(x) is not int for x in amounts):
                        raise ValueError(f'line {code} needs two integer VND values')
                    given[code] = amounts
                    notes[code] = text(str(row.get('note',''))) if row.get('note') else ''
                    if notes[code] and not re.fullmatch(r'([IVX]{1,4}\.)?\d{1,2}(\.\d{1,2})?', notes[code]):
                        raise ValueError(f'line {code}: note must be a note number such as 5, 5.2 or V.01, not {notes[code]!r}')
                amounts, included, log = solve(config.statements[f.lines], given)
                statements[f.id] = {'values': amounts, 'included': sorted(included), 'notes': notes, 'adjustments': log}
            elif f.kind == 'chart':
                v = check_chart(v, text)
            elif f.kind == 'seal':
                v = {'text': text(v['text']).upper()}
                if len(v['text']) > 40: raise ValueError('seal text must be under 40 characters')
            elif f.kind == 'figure':
                v['description'] = text(v['description'])
                if v['motif'] not in {'circle','leaf','diamond','waves','blocks'}: raise ValueError('unknown logo motif')
            if f.kind in {'chart','figure'} and v.get('colors') is not None:
                colors = v['colors']
                if not isinstance(colors,list) or len(colors) < 2 or any(not isinstance(c,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in colors):
                    raise ValueError('colors need at least two #rrggbb colors')
            clean[f.id] = v
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            problems.append(f'{f.id}: {exc}')
    if problems: raise ContentError(problems)
    selected_variables = variables or {key: choices[0] for key, choices in config.variables.items() if choices}
    apply_document_rules(config,clean,statements,variables=selected_variables,lang=document_lang)
    for item in clean.get('kpis', []):
        if item.get('source'):
            statement, code = item['source'].split('.')
            source = statements.get(statement + '_table', {}).get('values', {})
            if code not in source:
                raise ContentError(['kpis: unknown source ' + item['source']])
            item['value'] = source[code][0]
            item['unit'] = 'VND'
    return Content(config, clean, statements, document_lang)
