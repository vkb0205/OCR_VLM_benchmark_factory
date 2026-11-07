"""Academic paper content shapes, markup parsing and language-dependent labels."""
import json
from copy import deepcopy
import math
import re
import subprocess
from functools import lru_cache
from pathlib import Path

KATEX = Path(__file__).resolve().parents[1] / 'render/vendor/katex/katex.min.js'
CHECKER = Path(__file__).with_name('latex_check.js')

WORDS = {
    'vi': {'fig': 'Hình', 'tab': 'Bảng', 'alg': 'Thuật toán', 'abstract': 'Tóm tắt', 'keywords': 'Từ khóa',
           'references': 'Tài liệu tham khảo', 'acknowledgement': 'Lời cảm ơn', 'note': 'Ghi chú', 'and': 'và',
           'et_al': 'và cs.'},
    'en': {'fig': 'Figure', 'tab': 'Table', 'alg': 'Algorithm', 'abstract': 'Abstract', 'keywords': 'Keywords',
           'references': 'References', 'acknowledgement': 'Acknowledgements', 'note': 'Note', 'and': 'and',
           'et_al': 'et al.'},
}
ELEMENTS = {'heading', 'paragraph', 'list', 'equation', 'table', 'chart', 'figure', 'code', 'box'}
FLOATS = {'table': 'tab', 'chart': 'fig', 'figure': 'fig', 'code': 'alg'}
CHARTS = {'bar', 'grouped_bar', 'stacked_bar', 'line', 'scatter', 'histogram', 'area', 'box', 'donut'}
FIGURES = {'flowchart', 'pipeline', 'block_diagram', 'architecture', 'image_panel', 'multi_panel'}
BOXES = {'definition', 'theorem', 'lemma', 'remark', 'example'}
MARKUP = re.compile(r'\$([^$]+)\$|\\cite\{([^}]*)\}|\\ref\{([^}]*)\}|\\fn\{([^}]*)\}')
LENGTH_WORDS = {'short': 900, 'medium': 1600, 'long': 2600}
LATEX_COMMANDS = {
    'begin', 'end', 'frac', 'dfrac', 'tfrac', 'sqrt', 'sum', 'prod', 'int', 'partial', 'nabla',
    'hat', 'widehat', 'bar', 'overline', 'tilde', 'vec', 'mathbf', 'mathrm', 'mathbb', 'mathcal',
    'text', 'operatorname', 'left', 'right', 'langle', 'rangle', 'cdot', 'times', 'pm', 'mp',
    'le', 'leq', 'ge', 'geq', 'neq', 'approx', 'sim', 'propto', 'infty', 'log', 'ln', 'exp',
    'min', 'max', 'median', 'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'theta', 'lambda',
    'mu', 'sigma', 'rho', 'pi', 'eta', 'ldots', 'Delta', 'Gamma', 'Lambda', 'Omega', 'Phi', 'Sigma', 'Theta',
}
TEXT_GLYPHS = re.compile(r'^[A-Za-z0-9 .,;:!?()+\-=%/]*$')


@lru_cache(maxsize=4096)
def _latex_errors(items):
    result = subprocess.run(['node', str(CHECKER), str(KATEX)], input=json.dumps(list(items)),
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('KaTeX checker failed: ' + result.stderr.strip()[-300:])
    return tuple(json.loads(result.stdout))


def latex_problems(items):
    """Return KaTeX strict-mode errors; ASCII is required for math source."""
    items = tuple((latex, bool(display)) for latex, display in items)
    problems = [f'LaTeX must be ASCII: {latex!r}' for latex, _ in items if not latex.isascii()]
    for latex, _ in items:
        commands = set(re.findall(r'\\([A-Za-z]+)', latex))
        unknown = sorted(commands - LATEX_COMMANDS)
        if unknown:
            problems.append(f'LaTeX {latex!r}: commands are not allowed: {", ".join("\\" + name for name in unknown)}')
        text_arguments = re.findall(r'\\text\{([^{}]*)\}', latex)
        if re.search(r'\\text\{[^}]*\{', latex) or any(not TEXT_GLYPHS.fullmatch(value) for value in text_arguments):
            problems.append(f'LaTeX {latex!r}: \\text contains characters outside the supported math-font set')
    if items:
        problems += [f'LaTeX {latex!r}: {error}' for (latex, _), error in zip(items, _latex_errors(items)) if error]
    return problems


def cell(value, text):
    """Normalize a table cell: a string or {text, colspan, rowspan}."""
    if isinstance(value, dict):
        if set(value) - {'text', 'colspan', 'rowspan', 'bold'} or 'text' not in value:
            raise ValueError('table cells accept text, colspan, rowspan and optional bold')
        span = {}
        for key in ('colspan', 'rowspan'):
            raw = value.get(key, 1)
            if type(raw) is not int or not 1 <= raw <= 12:
                raise ValueError('cell spans must be integers from 1 to 12')
            span[key] = raw
        bold = value.get('bold', False)
        if type(bold) is not bool:
            raise ValueError('cell bold must be boolean')
        content = text(str(value['text']))
        if '$' in content:
            raise ValueError('math in table cells is not supported')
        return {'text': content, **span, 'bold': bold}
    content = text(str(value))
    if '$' in content:
        raise ValueError('math in table cells is not supported')
    return {'text': content, 'colspan': 1, 'rowspan': 1, 'bold': False}


def grid_width(rows):
    """Check a rectangular row/column grid with non-overlapping spans."""
    if not rows:
        raise ValueError('table grid must have rows')
    occupied = set()
    for r, row in enumerate(rows):
        if not isinstance(row, list) or not row:
            raise ValueError('table rows must be non-empty lists')
        c = 0
        for item in row:
            while (r, c) in occupied:
                c += 1
            for dr in range(item['rowspan']):
                for dc in range(item['colspan']):
                    pos = (r + dr, c + dc)
                    if pos in occupied:
                        raise ValueError('table cells overlap')
                    occupied.add(pos)
            c += item['colspan']
    if any(r >= len(rows) for r, _ in occupied):
        raise ValueError('a rowspan runs past the table')
    width = max(c for _, c in occupied) + 1
    for r in range(len(rows)):
        columns = {c for rr, c in occupied if rr == r}
        if columns != set(range(width)):
            raise ValueError('table rows have holes or different widths')
    return width


def check_authors(value, text):
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError('authors needs 1-8 people')
    out = []
    for index, author in enumerate(value, 1):
        if not isinstance(author, dict) or not isinstance(author.get('name'), str):
            raise ValueError(f'author {index} needs a name')
        affiliations = author.get('affiliations')
        if not isinstance(affiliations, list) or not affiliations or any(type(i) is not int or i < 1 for i in affiliations):
            raise ValueError('each author needs affiliation numbers starting at 1')
        email = author.get('email')
        if email is not None and (not isinstance(email, str) or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[a-z]{2,}', email)):
            raise ValueError('invalid author email')
        corresponding = author.get('corresponding', False)
        if type(corresponding) is not bool:
            raise ValueError('corresponding must be boolean')
        out.append({'name': text(author['name']), 'affiliations': affiliations,
                    'email': email, 'corresponding': corresponding})
    if sum(author['corresponding'] for author in out) != 1:
        raise ValueError('exactly one corresponding author')
    return out


def check_references(value, text):
    if not isinstance(value, list) or not 8 <= len(value) <= 45:
        raise ValueError('references needs 8-45 entries')
    out = []
    for index, reference in enumerate(value, 1):
        if not isinstance(reference, dict) or not isinstance(reference.get('text'), str) or not isinstance(reference.get('cite'), str):
            raise ValueError(f'reference {index} needs formatted text and a citation name')
        out.append({'text': text(reference['text']), 'cite': text(reference['cite'])})
    return out


def check_article(value, text):
    """Validate and normalize the typed body shape; cross-references are separate rules."""
    if not isinstance(value, list) or not value:
        raise ValueError('body must be a non-empty list of elements')
    out, ids = [], set()
    for number, element in enumerate(value, 1):
        kind = element.get('type') if isinstance(element, dict) else None
        if kind not in ELEMENTS:
            raise ValueError(f'element {number}: unknown type {kind!r}')
        where = f'element {number} ({kind})'
        try:
            item = {'type': kind}
            ident = element.get('id')
            id_required = kind in {'table', 'chart', 'figure'} or kind == 'equation' and bool(element.get('numbered', True))
            if kind == 'code' and ident is not None or id_required:
                prefix = 'eq' if kind == 'equation' else FLOATS[kind]
                if not isinstance(ident, str) or not re.fullmatch(prefix + r':[a-z0-9_-]+', ident):
                    raise ValueError(f'{where}: id must look like {prefix}:name')
                if ident in ids:
                    raise ValueError(f'{where}: duplicate id {ident}')
                ids.add(ident)
                item['id'] = ident

            if kind == 'heading':
                if type(element.get('level')) is not int or element['level'] not in (1, 2, 3):
                    raise ValueError(f'{where}: level must be 1, 2 or 3')
                item.update(level=element['level'], text=text(element['text']))
            elif kind == 'paragraph':
                item['text'] = text(element['text'])
            elif kind == 'list':
                list_items = element.get('items')
                if not isinstance(list_items, list) or not 2 <= len(list_items) <= 10:
                    raise ValueError(f'{where}: 2-10 items')
                if type(element.get('ordered', False)) is not bool:
                    raise ValueError(f'{where}: ordered must be boolean')
                item.update(ordered=element.get('ordered', False), items=[text(part) for part in list_items])
            elif kind == 'equation':
                latex = element.get('latex')
                if not isinstance(latex, str) or not latex.strip():
                    raise ValueError(f'{where}: latex required')
                if type(element.get('numbered', True)) is not bool:
                    raise ValueError(f'{where}: numbered must be boolean')
                item.update(latex=latex.strip(), numbered=element.get('numbered', True))
            elif kind == 'table':
                try:
                    header = [[cell(value, text) for value in row] for row in element['header']]
                    rows = [[cell(value, text) for value in row] for row in element['rows']]
                    if not 1 <= len(header) <= 4 or not 2 <= len(rows) <= 40:
                        raise ValueError('needs 1-4 header rows and 2-40 body rows')
                    width = grid_width(header)
                    if grid_width(rows) != width:
                        raise ValueError('body width differs from header width')
                    if type(element.get('landscape', False)) is not bool:
                        raise ValueError('landscape must be boolean')
                    table_style = element.get('table_style', 'three_line')
                    if table_style not in {'three_line', 'full_grid', 'shaded_header'}:
                        raise ValueError('table_style must be three_line, full_grid or shaded_header')
                    item.update(caption=text(element['caption']), header=header, rows=rows,
                                note=text(element['note']) if element.get('note') else None,
                                landscape=element.get('landscape', False), table_style=table_style)
                except (KeyError, TypeError) as exc:
                    raise ValueError(f'{where}: invalid table shape ({exc})') from exc
            elif kind == 'chart':
                item.update(check_chart(element, text, where), caption=text(element['caption']))
            elif kind == 'figure':
                figure_type = element.get('figure_type')
                if figure_type not in FIGURES:
                    raise ValueError(f'{where}: figure_type must be one of {sorted(FIGURES)}')
                panels = element.get('panels') or []
                if figure_type == 'multi_panel':
                    if not isinstance(panels, list) or not 2 <= len(panels) <= 4:
                        raise ValueError(f'{where}: multi_panel needs 2-4 single panels')
                    normalized_panels = []
                    for panel in panels:
                        if not isinstance(panel, dict) or panel.get('figure_type') not in FIGURES - {'multi_panel'}:
                            raise ValueError(f'{where}: each panel needs a supported single-panel figure_type')
                        normalized_panels.append({'figure_type': panel['figure_type'],
                                                  'description': text(panel['description']),
                                                  'labels': [text(label) for label in panel.get('labels', [])]})
                    panels = normalized_panels
                labels = element.get('labels', [])
                if not isinstance(labels, list):
                    raise ValueError(f'{where}: labels must be a list')
                labels = [text(label) for label in labels]
                if figure_type in {'block_diagram', 'architecture', 'flowchart', 'pipeline'} and not 3 <= len(labels) <= 10:
                    raise ValueError(f'{where}: diagrams need 3-10 short box labels')
                if any(len(label) > 28 for label in labels):
                    raise ValueError(f'{where}: box labels must be at most 28 characters')
                item.update(figure_type=figure_type, caption=text(element['caption']),
                            description=text(element['description']), labels=labels, panels=panels)
            elif kind == 'code':
                lines = element.get('lines')
                if not isinstance(lines, list) or not 3 <= len(lines) <= 30 or any(not isinstance(line, str) or len(line) > 90 for line in lines):
                    raise ValueError(f'{where}: 3-30 lines of at most 90 characters')
                if not isinstance(element.get('language', 'pseudocode'), str):
                    raise ValueError(f'{where}: language must be a string')
                item.update(language=element.get('language', 'pseudocode'),
                            caption=text(element['caption']) if element.get('caption') else None,
                            lines=[line.rstrip() for line in lines])
            elif kind == 'box':
                if element.get('kind') not in BOXES:
                    raise ValueError(f'{where}: box kind must be one of {sorted(BOXES)}')
                item.update(kind=element['kind'], title=text(element['title']), text=text(element['text']))
            out.append(item)
        except KeyError as exc:
            raise ValueError(f'{where}: missing required field {exc.args[0]}') from exc
        except (TypeError, ValueError) as exc:
            if str(exc).startswith(where + ':'):
                raise
            raise ValueError(f'{where}: {exc}') from exc
    return out


def normalize_chart(element):
    """Coerce numeric strings and discard unusable optional uncertainty data.

    Nonfinite measurements remove their entire aligned category (or scatter point),
    never invent a measurement or shift a label onto a different observation.
    Other malformed values remain for the validator to reject with ownership.
    """
    element = deepcopy(element)
    series = element.get('series')
    labels = element.get('labels')
    kind = element.get('chart_type')
    if not isinstance(series, list) or not isinstance(labels, list):
        return element

    def numeric(value):
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
        return value

    def nonfinite(value):
        return type(value) in (int, float) and not math.isfinite(value)

    aligned = kind != 'scatter' and bool(series)
    invalid = set()
    for source in series:
        if not isinstance(source, dict):
            aligned = False
            continue
        key = 'points' if kind == 'scatter' else 'stats' if kind == 'box' else 'values'
        values = source.get(key)
        if not isinstance(values, list):
            aligned = False
            continue
        if key == 'stats':
            stat_keys = ('min', 'q1', 'median', 'q3', 'max')
            values = [[row[k] for k in stat_keys] if isinstance(row, dict) and set(row) == set(stat_keys) else row
                      for row in values]
        if key in {'points', 'stats'}:
            values = [[numeric(v) for v in row] if isinstance(row, list) else row for row in values]
        else:
            values = [numeric(v) for v in values]
        source[key] = values
        if key == 'points':
            source[key] = [row for row in values if not isinstance(row, list) or not any(nonfinite(v) for v in row)]
        elif len(values) != len(labels):
            aligned = False
        else:
            for i, value in enumerate(values):
                if key == 'stats':
                    if isinstance(value, list) and any(nonfinite(v) for v in value):
                        invalid.add(i)
                elif nonfinite(value):
                    invalid.add(i)
        errors = source.get('errors')
        if errors is not None:
            normalized = [numeric(v) for v in errors] if isinstance(errors, list) else None
            if (kind not in {'line', 'bar', 'grouped_bar'} or normalized is None
                    or len(normalized) != len(labels)
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in normalized)):
                source.pop('errors', None)
            else:
                source['errors'] = normalized
    if aligned and invalid:
        keep = [i for i in range(len(labels)) if i not in invalid]
        element['labels'] = [labels[i] for i in keep]
        key = 'stats' if kind == 'box' else 'values'
        for source in series:
            source[key] = [source[key][i] for i in keep]
            if isinstance(source.get('errors'), list):
                source['errors'] = [source['errors'][i] for i in keep]
    return element


def check_chart(element, text, where):
    element = normalize_chart(element)
    chart_type = element.get('chart_type')
    if chart_type not in CHARTS:
        raise ValueError(f'{where}: chart_type must be one of {sorted(CHARTS)}')
    labels, series = element.get('labels'), element.get('series')
    if not isinstance(labels, list) or not isinstance(series, list) or not 1 <= len(series) <= 4:
        raise ValueError(f'{where}: labels and 1-4 series are required')

    def number(value):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'{where}: values must be finite numbers')
        return float(value)

    out = []
    for index, source in enumerate(series, 1):
        if not isinstance(source, dict) or not isinstance(source.get('name'), str):
            raise ValueError(f'{where}: series {index} needs a name')
        target = {'name': text(source['name'])}
        if chart_type == 'scatter':
            points = source.get('points')
            if not isinstance(points, list) or not 5 <= len(points) <= 80 or any(not isinstance(point, list) or len(point) != 2 for point in points):
                raise ValueError(f'{where}: scatter series need 5-80 [x, y] points')
            target['points'] = [[number(point[0]), number(point[1])] for point in points]
        elif chart_type == 'box':
            stats = source.get('stats')
            if not isinstance(stats, list) or len(stats) != len(labels):
                raise ValueError(f'{where}: box series need one [min,q1,median,q3,max] per label')
            target['stats'] = [[number(value) for value in stat] for stat in stats]
            if any(len(stat) != 5 or stat != sorted(stat) for stat in target['stats']):
                raise ValueError(f'{where}: box stats must be five increasing numbers')
        else:
            values = source.get('values')
            if not isinstance(values, list) or len(values) != len(labels):
                raise ValueError(f'{where}: one value per label')
            target['values'] = [number(value) for value in values]
            if chart_type in {'bar', 'grouped_bar', 'stacked_bar', 'histogram', 'donut'} and min(target['values']) < 0:
                raise ValueError(f'{where}: {chart_type} values must be non-negative')
            errors = source.get('errors')
            if errors is not None:
                if chart_type not in {'line', 'bar', 'grouped_bar'} or not isinstance(errors, list) or len(errors) != len(labels):
                    raise ValueError(f'{where}: errors need one value per label on line or bar charts')
                target['errors'] = [abs(number(value)) for value in errors]
        out.append(target)
    if chart_type != 'scatter' and not 2 <= len(labels) <= 16:
        raise ValueError(f'{where}: 2-16 labels')
    if chart_type in {'donut', 'histogram'} and len(out) != 1:
        raise ValueError(f'{where}: {chart_type} takes one series')
    if chart_type == 'scatter' and not 2 <= len(labels) <= 16:
        raise ValueError(f'{where}: scatter axis labels need 2-16 entries')
    legend_position = element.get('legend_position', 'outside')
    if legend_position not in {'inside', 'outside'}:
        raise ValueError(f'{where}: legend_position must be inside or outside')
    gridlines = element.get('gridlines', True)
    if type(gridlines) is not bool:
        raise ValueError(f'{where}: gridlines must be boolean')
    return {'chart_type': chart_type, 'labels': [text(str(label)) for label in labels], 'series': out,
            'x_label': text(element['x_label']) if element.get('x_label') else None,
            'y_label': text(element['y_label']) if element.get('y_label') else None,
            'legend_position': legend_position, 'gridlines': gridlines}


def _brace_group(source, start):
    if start >= len(source) or source[start] != '{':
        raise ValueError('markup command must be followed by braces')
    depth = 1
    for position in range(start + 1, len(source)):
        if source[position] == '{':
            depth += 1
        elif source[position] == '}':
            depth -= 1
            if depth == 0:
                return source[start + 1:position], position + 1
    raise ValueError('unclosed markup braces')


def parse_markup(source, *, lang, citation_style, references, labels, footnotes, used_citations, used_floats, latex):
    """Resolve inline markup into DocIR-compatible text/math/footnote spans."""
    spans, plain = [], []

    def emit_text(value):
        if value:
            spans.append({'type': 'text', 'text': value})
            plain.append(value)

    index = 0
    text_start = 0
    while index < len(source):
        if source[index] == '$':
            emit_text(source[text_start:index])
            end = source.find('$', index + 1)
            if end < 0 or not source[index + 1:end].strip():
                raise ValueError('inline math needs a non-empty closing $ delimiter')
            formula = source[index + 1:end].strip()
            spans.append({'type': 'equation_inline', 'latex': formula})
            latex.append((formula, False))
            plain.append('$' + formula + '$')
            index = end + 1
            text_start = index
            continue
        command = next((name for name in ('cite', 'ref', 'fn') if source.startswith('\\' + name, index)), None)
        if command:
            emit_text(source[text_start:index])
            start = index + len(command) + 1
            if start < len(source) and (source[start].isalnum() or source[start] == '_'):
                raise ValueError(f'unknown markup command beginning with \\{command}')
            value, after = _brace_group(source, start)
            value = value.strip()
            if not value:
                raise ValueError(f'\\{command} cannot be empty')
            if command == 'cite':
                try:
                    numbers = [int(part.strip()) for part in value.split(',')]
                except ValueError as exc:
                    raise ValueError('\\cite values must be comma-separated reference numbers') from exc
                if len(set(numbers)) != len(numbers):
                    raise ValueError('\\cite contains a duplicate reference number')
                if any(number < 1 or number > len(references) for number in numbers):
                    raise ValueError('\\cite number is outside the reference list')
                used_citations.update(numbers)
                if citation_style == 'numeric':
                    rendered = '[' + ', '.join(str(number) for number in numbers) + ']'
                else:
                    rendered = '(' + '; '.join(references[number - 1]['cite'] for number in numbers) + ')'
                emit_text(rendered)
            elif command == 'ref':
                if value not in labels:
                    raise ValueError(f'\\ref target does not resolve: {value}')
                if value.split(':', 1)[0] in {'tab', 'fig', 'alg'}:
                    used_floats.add(value)
                emit_text(labels[value])
            else:
                footnote_id = f'fn_{len(footnotes) + 1}'
                footnote = {'id': footnote_id, 'number': len(footnotes) + 1, 'text': value}
                footnotes.append(footnote)
                spans.append({'type': 'footnote_mark', 'text': str(footnote['number']), 'target': footnote_id})
                plain.append(str(footnote['number']))
            index = after
            text_start = index
            continue
        if source.startswith('\\cite', index) or source.startswith('\\ref', index) or source.startswith('\\fn', index):
            raise ValueError('markup commands must be written as \\name{value}')
        index += 1
    emit_text(source[text_start:])
    return spans, ''.join(plain)


def words(source):
    """Approximate prose word count, excluding math source and markup syntax."""
    return len(MARKUP.sub(' x ', source).split())
