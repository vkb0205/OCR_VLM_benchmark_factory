"""Cross-field rules and inline-markup resolution for academic papers."""
import re

from factory.content.article import LENGTH_WORDS, WORDS, latex_problems, parse_markup, words


def apply(config, values, statements, *, variables=None, lang=None):
    del statements
    variables = variables or {}
    lang = lang or variables.get(config.language_variable, config.lang)
    if lang not in {'vi', 'en'}:
        raise ValueError('academic_paper language must be vi or en')
    if variables.get('lang', lang) != lang:
        raise ValueError('lang variable and document language disagree')
    paper_length = variables.get('paper_length', 'short')
    if paper_length not in LENGTH_WORDS:
        raise ValueError('paper_length must be short, medium or long')
    citation_style = variables.get('citation_style', 'numeric')
    if citation_style not in {'numeric', 'author_year'}:
        raise ValueError('citation_style must be numeric or author_year')

    affiliations = values.get('affiliations')
    authors = values.get('authors')
    if not isinstance(affiliations, list) or not 1 <= len(affiliations) <= 5:
        raise ValueError('affiliations needs 1-5 entries')
    for index, author in enumerate(authors, 1):
        if any(number > len(affiliations) for number in author['affiliations']):
            raise ValueError(f'authors: author {index} names an unknown affiliation')

    if bool(values.get('abstract_alt')) != bool(values.get('keywords_alt')):
        raise ValueError('abstract_alt and keywords_alt must appear together')
    if values.get('abstract_alt') and values.get('abstract_alt') == values.get('abstract'):
        raise ValueError('abstract_alt must contain the other language')

    body = values.get('body')
    headings = [item for item in body if item['type'] == 'heading']
    level_one = [item for item in headings if item['level'] == 1]
    if not 4 <= len(level_one) <= (10 if variables.get("element_plan") else 7) or not any(item['level'] == 2 for item in headings):
        raise ValueError('body needs 4-7 level-1 sections and at least one level-2 subsection')

    labels, float_ids = {}, []
    counters = {'tab': 0, 'fig': 0, 'alg': 0, 'eq': 0}
    equations = []
    for item in body:
        kind = item['type']
        if kind == 'equation':
            if item['numbered']:
                counters['eq'] += 1
                item['number'] = counters['eq']
                labels[item['id']] = f"({counters['eq']})"
            equations.append((item['latex'], True))
        elif kind in {'table', 'chart', 'figure', 'code'}:
            if kind == 'code' and 'id' not in item:
                continue
            prefix = {'table': 'tab', 'chart': 'fig', 'figure': 'fig', 'code': 'alg'}[kind]
            counters[prefix] += 1
            item['number'] = counters[prefix]
            label = WORDS[lang][prefix]
            labels[item['id']] = f'{label} {counters[prefix]}'
            float_ids.append(item['id'])
            if kind in {'table', 'chart', 'figure'}:
                item['caption_printed'] = f'{label} {counters[prefix]}. {item["caption"]}'
            elif item.get('caption'):
                item['caption_printed'] = f'{label} {counters[prefix]}. {item["caption"]}'

    if not variables.get('element_plan') and sum(item['type'] == 'equation' for item in body) < 3:
        raise ValueError('body needs at least three display equations')
    if not variables.get('element_plan') and not any(re.search(r'\\begin\s*\{aligned\}', formula) for formula, _ in equations):
        raise ValueError('one display equation must use an aligned environment')
    for category, label in (('table', 'table'), ('chart', 'chart'), ('figure', 'figure')):
        if not any(item['type'] == category for item in body):
            raise ValueError(f'body needs at least one {label} with a caption')

    footnotes, used_citations, used_floats, latex = [], set(), set(), list(equations)

    def resolve(source, anchor):
        spans, visible = parse_markup(source, lang=lang, citation_style=citation_style,
                                      references=values['references'], labels=labels,
                                      footnotes=footnotes, used_citations=used_citations,
                                      used_floats=used_floats, latex=latex)
        for footnote in footnotes:
            if 'anchor' not in footnote:
                footnote['anchor'] = anchor
        return spans, visible

    inline_math_paragraphs = 0
    total_words = 0
    for index, item in enumerate(body):
        kind = item['type']
        if kind in {'heading', 'paragraph'}:
            spans, visible = resolve(item['text'], index)
            item['resolved_spans'], item['visible_text'] = spans, visible
            total_words += words(item['text'])
            if kind == 'paragraph' and any(span['type'] == 'equation_inline' for span in spans):
                inline_math_paragraphs += 1
        elif kind == 'list':
            item['item_spans'], item['visible_items'] = [], []
            for value in item['items']:
                spans, visible = resolve(value, index)
                item['item_spans'].append(spans)
                item['visible_items'].append(visible)
                total_words += words(value)
        elif kind in {'table', 'chart', 'figure'}:
            spans, visible = resolve(item['caption'], index)
            item['caption_spans'], item['caption_visible'] = spans, visible
            total_words += words(item['caption'])
            if kind == 'table':
                for row in item['header'] + item['rows']:
                    total_words += sum(words(cell['text']) for cell in row)
                if item.get('note'):
                    spans, visible = resolve(item['note'], index)
                    item['note_spans'], item['note_visible'] = spans, visible
                    total_words += words(item['note'])
            elif kind == 'chart':
                total_words += sum(words(label) for label in item['labels'])
                total_words += sum(words(series['name']) for series in item['series'])
            else:
                total_words += words(item['description']) + sum(words(label) for label in item['labels'])
        elif kind == 'code':
            total_words += sum(words(line) for line in item['lines'])
            if item.get('caption'):
                spans, visible = resolve(item['caption'], index)
                item['caption_spans'], item['caption_visible'] = spans, visible
                total_words += words(item['caption'])
        elif kind == 'box':
            item['title_spans'], item['title_visible'] = resolve(item['title'], index)
            item['text_spans'], item['text_visible'] = resolve(item['text'], index)
            total_words += words(item['title']) + words(item['text'])

    if inline_math_paragraphs < 5:
        raise ValueError(f'body needs inline math in at least five paragraphs (found {inline_math_paragraphs})')
    if not footnotes:
        raise ValueError('body needs at least one page footnote mark using \\fn{text}')
    if set(float_ids) - used_floats:
        missing = ', '.join(sorted(set(float_ids) - used_floats))
        raise ValueError('every float needs a text reference; missing: ' + missing)
    if not used_citations:
        raise ValueError('body must cite references')
    if set(range(1, len(values['references']) + 1)) - used_citations:
        missing = ', '.join(str(value) for value in sorted(set(range(1, len(values['references']) + 1)) - used_citations))
        raise ValueError('every reference must be cited; missing citation numbers: ' + missing)
    math_errors = latex_problems(latex)
    if math_errors:
        raise ValueError('; '.join(math_errors))

    minimum = LENGTH_WORDS[paper_length]
    if total_words < minimum:
        raise ValueError(f'body has {total_words} words; {paper_length} papers need at least {minimum}')

    if citation_style == 'numeric':
        for index, reference in enumerate(values['references'], 1):
            reference['text'] = f'[{index}] ' + re.sub(r'^\s*\[\d+\]\s*', '', reference['text'])
    values['_academic_footnotes'] = footnotes
    values['_academic_labels'] = labels
    values['_academic_metrics'] = {'body_words': total_words, 'inline_math_paragraphs': inline_math_paragraphs,
                                   'display_equations': len(equations), 'citations_used': len(used_citations),
                                   'floats': len(float_ids), 'footnotes': len(footnotes)}
