"""Content-only sizing information for a design agent; no paper prose."""
from collections import Counter
import re


def profile(paper: dict) -> dict:
    values, variables = paper['values'], paper['variables']
    body = values['body']
    headings = [{'level': x['level'], 'characters': len(x['text'])}
                for x in body if x['type'] == 'heading']
    tables = [{'rows': len(x['rows']),
               'columns': max(sum(c.get('colspan', 1) if isinstance(c, dict) else 1 for c in row)
                              for row in x['header'])} for x in body if x['type'] == 'table']
    texts = []

    def visit(value):
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            for key, child in value.items():
                if not key.startswith('_') and key not in {'id', 'type', 'latex', 'resolved_spans'}:
                    visit(child)
    visit(values)
    authors = values['authors']
    return {'content_id': paper.get('content_id'), 'language': variables['lang'],
            'citation_style': variables['citation_style'], 'length_class': variables['paper_length'],
            'total_characters': sum(map(len, texts)), 'section_tree': headings,
            'section_counts': {str(k): v for k, v in Counter(x['level'] for x in headings).items()},
            'tables': tables, 'table_count': len(tables),
            'widest_column_count': max((x['columns'] for x in tables), default=0),
            'figures_charts': dict(Counter(x.get('chart_type', x.get('figure_type'))
                                          for x in body if x['type'] in {'chart', 'figure'})),
            'chart_count': sum(x['type'] == 'chart' for x in body),
            'figure_count': sum(x['type'] == 'figure' for x in body),
            'box_count': sum(x['type'] == 'box' for x in body),
            'display_equations': sum(x['type'] == 'equation' for x in body),
            'inline_equations': sum(len(re.findall(r'(?<!\\)\$[^$]+\$', t)) for t in texts),
            'element_plan': variables.get('element_plan'),
            'code_listing_count': sum(x['type'] == 'code' for x in body),
            'code_listing': any(x['type'] == 'code' for x in body),
            'footnote_count': sum(t.count('\\fn{') for t in texts),
            'reference_count': len(values['references']), 'author_count': len(authors),
            'affiliation_count': len(values['affiliations']),
            'title_characters': len(values['title']),
            'longest_author_line': max((len(a['name']) + len(a.get('email') or '') +
                                        len(str(a['affiliations'])) + 4 for a in authors), default=0),
            'longest_affiliation': max(map(len, values['affiliations']), default=0)}
