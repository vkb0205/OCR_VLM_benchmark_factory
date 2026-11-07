"""Build, validate and freeze reusable academic content, with group-owned repairs."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from pathlib import Path
import time
from typing import Any

from pydantic import BaseModel

from factory.content.article import LATEX_COMMANDS, LENGTH_WORDS, grid_width
from factory.content.config import load_config
from factory.content.profile import profile
from factory.content.schema import validate_content
from factory.llm.client import Router, parse_json
from factory.log import log
from factory.paths import ROOT

GROUPS = ('front', 'formulas', 'tables', 'charts_figures', 'code', 'references', 'body')
FRONT = ('title', 'authors', 'affiliations', 'abstract', 'abstract_alt', 'keywords',
         'keywords_alt', 'journal', 'acknowledgement')
KINDS = {'body': {'heading', 'paragraph', 'list', 'box'}, 'formulas': {'equation'},
         'tables': {'table'}, 'charts_figures': {'chart', 'figure'}, 'code': {'code'}}


ARCHETYPES = {
 'experimental': ((3,7),(1,3),(2,5),(2,8),(0,1)),
 'methods': ((2,5),(1,3),(1,4),(4,12),(1,2)),
 'systems': ((3,6),(2,4),(2,5),(1,6),(1,2)),
 'survey': ((2,5),(2,4),(2,5),(0,2),(0,0)),
 'field_study': ((3,7),(1,4),(1,4),(0,5),(0,0)),
 'theoretical': ((2,4),(1,2),(1,3),(8,15),(0,1)),
}
# Field-specific cycles ensure balanced coverage over the 16-paper bank.
FIELD_ARCHETYPES = {
 'materials modelling': ('theoretical','experimental'),
 'signal processing': ('methods','theoretical'), 'robotics': ('systems','methods'),
 'hydrology': ('field_study','experimental'), 'linguistics': ('survey','field_study'),
 'ecology': ('experimental','field_study'), 'transport': ('systems','field_study'),
 'energy storage': ('experimental','methods'), 'computer vision': ('methods','survey'),
 'acoustics': ('theoretical','experimental'), 'soil mechanics': ('field_study','theoretical'),
 'network optimization': ('survey','methods'), 'thermal engineering': ('theoretical','systems'),
 'ocean dynamics': ('field_study','theoretical'), 'computational biology': ('survey','methods'),
 'urban climatology': ('experimental','field_study'),
}

def draw_paper_plan(seed, field):
    """Draw before prompting; the plan is frozen with the paper variables."""
    import random
    from factory.content.article import CHARTS, FIGURES
    rng = random.Random(seed + 1)
    archetype = rng.choice(FIELD_ARCHETYPES.get(field, tuple(ARCHETYPES)))
    counts = {k: rng.randint(*bounds) for k,bounds in zip(
        ('chart','figure','table','equation','code'), ARCHETYPES[archetype])}
    chart_types = rng.sample(sorted(CHARTS - {'donut'}), min(counts['chart'],len(CHARTS)-1))
    if archetype == 'survey' and rng.random() < .2:
        chart_types[-1] = 'donut'
    return {'archetype': archetype, 'counts': {**counts, 'references': rng.randint(15,45)},
            'chart_types': chart_types,
            'figure_types': rng.choices(sorted(FIGURES), k=counts['figure']),
            'sections': {
                'survey':['Introduction','Scope and Search','Taxonomy','Comparative Evidence','Open Questions','Conclusion'],
                'theoretical':['Introduction','Related Work','Definitions','Main Results','Proofs','Numerical Illustration','Limitations','Conclusion'],
                'field_study':['Introduction','Study Area','Sampling Protocol','Measurements','Results','Discussion','Limitations','Conclusion'],
                'methods':['Introduction','Related Work','Method','Experimental Setup','Results','Ablation','Limitations','Conclusion'],
                'systems':['Introduction','Requirements','Architecture','Implementation','Evaluation','Discussion','Limitations','Conclusion'],
                'experimental':['Introduction','Related Work','Materials and Methods','Experimental Setup','Results','Discussion','Limitations','Conclusion'],
            }[archetype]}


def validate_plan_counts(plan, body, references):
    from collections import Counter
    counts = Counter(x['type'] for x in body)
    counts['references'] = len(references)
    owners = {'chart':'charts_figures','figure':'charts_figures','table':'tables',
              'equation':'formulas','code':'code','references':'references'}
    for kind,target in plan['counts'].items():
        tolerance = 0 if kind=='code' or target==0 else 1
        if abs(counts[kind]-target)>tolerance:
            raise ValueError(f'{owners[kind]}: plan requires {target} {kind} (tolerance {tolerance}); got {counts[kind]}')


class GroupReply(BaseModel):
    data: Any


def validate_group(name, data):
    """Reject a reply that belongs to another element group before checkpointing it."""
    if name == 'front':
        if not isinstance(data, dict) or any(key not in data for key in FRONT):
            raise ValueError('front: expected an object with every front field')
        return data
    if name == 'references':
        if not isinstance(data, list) or any(
                not isinstance(row, dict) or not isinstance(row.get('text'), str)
                or not isinstance(row.get('cite'), str) for row in data):
            raise ValueError('references: expected a list of {text, cite} objects')
        return data
    if name not in KINDS:
        raise ValueError(f'unknown content group {name!r}')
    if not isinstance(data, list):
        raise ValueError(f'{name}: expected a list')
    if name == 'body':
        for index, element in enumerate(data, 1):
            kind = element.get('type') if isinstance(element, dict) else None
            if kind not in KINDS[name]:
                raise ValueError(f'{name}: element {index} has type {kind!r}; allowed: {sorted(KINDS[name])}')
        return data
    for index, row in enumerate(data, 1):
        if not isinstance(row, dict) or type(row.get('after')) is not int or not isinstance(row.get('element'), dict):
            raise ValueError(f'{name}: item {index} must contain an integer after and an element object')
        kind = row['element'].get('type')
        if kind not in KINDS[name]:
            raise ValueError(f'{name}: element {index} has type {kind!r}; allowed: {sorted(KINDS[name])}')
    return data


PLAN_KEYS = {'sections', 'equations', 'tables', 'charts', 'figures', 'code',
             'element_plan', 'archetype', 'counts', 'chart_types', 'figure_types'}


def clean_group(name, data, plan=None):
    """Remove known plan echoes and foreign elements, retaining count validation."""
    if name == 'front' and isinstance(data, dict):
        data = {k: v for k, v in data.items() if k not in PLAN_KEYS or k in FRONT}
    if name in KINDS and isinstance(data, list):
        kept = []
        for row in data:
            element = row if name == 'body' else row.get('element', {}) if isinstance(row, dict) else {}
            kind = element.get('type') if isinstance(element, dict) else None
            if kind not in KINDS[name] and (kind == 'reference' or any(kind in kinds for kinds in KINDS.values())):
                log(f'warning: bank {name}: dropping out-of-group {kind} element')
            else:
                kept.append(row)
        data = kept
    validate_group(name, data)
    if plan and name != 'front':
        from collections import Counter
        counts = Counter({'references': len(data)}) if name == 'references' else Counter(
            (row if name == 'body' else row['element'])['type'] for row in data)
        for kind, target in plan['counts'].items():
            if (name == 'references' and kind == 'references') or kind in KINDS.get(name, set()):
                tolerance = 0 if kind == 'code' or target == 0 else 1
                if abs(counts[kind] - target) > tolerance:
                    raise ValueError(f'{name}: plan requires {target} {kind} (tolerance {tolerance}); got {counts[kind]}')
    return data


def digest(paper):
    return hashlib.sha256(json.dumps({'values': paper['values'], 'variables': paper['variables']},
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_paper(paper):
    variables = paper['variables']
    config = load_config().documents['academic_paper'].for_lang(variables['lang'])
    def reject_words(value, owner):
        if isinstance(value, str):
            for word in config.design.get('forbidden_words', []) + ['sample', 'synthetic', 'fictional', 'placeholder', 'example.invalid']:
                if re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', value, re.I):
                    raise ValueError(f'{owner}: forbidden word {word}')
        elif isinstance(value, list):
            for item in value:
                reject_words(item, owner)
        elif isinstance(value, dict):
            if value.get('type'):
                owner = next((g for g, kinds in KINDS.items() if value['type'] in kinds), owner)
            for child in value.values():
                reject_words(child, owner)
    for key, value in paper['values'].items():
        reject_words(value, 'references' if key == 'references' else 'body' if key == 'body' else 'front')
    content = validate_content(config, deepcopy(paper['values']), lang=variables['lang'], variables=variables)
    values, body = content.values, content.values['body']
    if not 2 <= len(values['authors']) <= 6:
        raise ValueError('front: requires 2-6 authors')
    if not any(a['corresponding'] and a.get('email') for a in values['authors']):
        raise ValueError('front: corresponding author needs email')
    plan = variables.get('element_plan')
    if plan:
        validate_plan_counts(plan, body, values['references'])
    else:
        for kind, lo, hi, owner in [('equation', 2, 8, 'formulas'), ('table', 1, 4, 'tables')]:
            if not lo <= sum(x['type'] == kind for x in body) <= hi:
                raise ValueError(f'{owner}: requires {lo}-{hi} {kind} elements')
        if not 1 <= sum(x['type'] in {'chart', 'figure'} for x in body) <= 3:
            raise ValueError('charts_figures: requires 1-3 figures/charts')
    if not any(grid_width(x['header']) >= 6 for x in body if x['type'] == 'table'):
        raise ValueError('tables: requires a wide table with at least six columns')
    if paper.get('hash') and paper['hash'] != digest(paper):
        raise ValueError('bank content hash mismatch')
    return content


def repair_owner(error, values):
    """Return the sole group owning a validation error, never regenerate other groups."""
    message = str(error)
    for group in GROUPS:
        if group != 'body' and message.startswith(group + ':'):
            return group
    if message.startswith('references:'):
        return 'references'
    # Schema validation wraps typed element errors as body errors. Prefer their
    # explicit kind over an index into a possibly normalized/changed body.
    typed = re.search(r'element \d+ \((\w+)\)', message)
    if typed:
        owner = next((g for g, kinds in KINDS.items() if typed[1] in kinds), None)
        if owner:
            return owner
    # Some cross-reference errors identify an element by id, without an index.
    for element in values.get('body', []):
        ident = element.get('id')
        if isinstance(ident, str) and re.search(r'(?<![\w:-])' + re.escape(ident) + r'(?![\w:-])', message):
            return next((g for g, kinds in KINDS.items() if element.get('type') in kinds), 'body')
    index = re.search(r'element (\d+)', message)
    if index and 1 <= int(index[1]) <= len(values.get('body', [])):
        kind = values['body'][int(index[1]) - 1].get('type')
        return next((g for g, kinds in KINDS.items() if kind in kinds), 'body')
    if any(message.startswith(k + ':') for k in FRONT) or 'author' in message or 'affiliation' in message or 'abstract_alt' in message:
        return 'front'
    if 'LaTeX' in message or 'display equation' in message or 'aligned environment' in message:
        if any(x.get('type') == 'equation' and repr(x.get('latex', '')) in message
               for x in values.get('body', [])):
            return 'formulas'
        return 'formulas' if 'display' in message or 'aligned' in message else 'body'
    if 'table' in message and ('needs at least' in message or 'wide' in message):
        return 'tables'
    if 'needs at least one chart' in message or 'needs at least one figure' in message:
        return 'charts_figures'
    return 'body'  # prose owns citation usage, float references, length and footnote marks


def assemble(groups):
    values = dict(groups['front'])
    values['references'] = groups['references']
    body = list(groups['body'])
    inserts = []
    for name in ('formulas', 'tables', 'charts_figures', 'code'):
        for row in groups.get(name, []):
            if row['element'].get('type') not in KINDS[name]:
                raise ValueError(f'{name}: wrong element type')
            inserts.append((int(row['after']), row['element']))
    # `after` is a 1-based prose-element index. Each group retains its own ordering.
    for after, item in sorted(inserts, key=lambda row: row[0], reverse=True):
        body.insert(max(0, min(after, len(body))), item)
    values['body'] = body
    return values


def group_prompt(name, variables, groups):
    front = 'Return {"data": {all front field ids: values}}. Required fields: ' + ', '.join(FRONT) + '. '
    front += ('Authors are 2-6 objects {name,affiliations:[1-based integers],corresponding:boolean,email?}; '
              'exactly one corresponding author with an email on an invented realistic domain. '
              'Affiliations: 1-5 strings. abstract_alt and keywords_alt must both be null. '
              'title, abstract, keywords, journal and acknowledgement are non-empty strings; '
              'keywords must be one semicolon-separated STRING, never an array. '
              'Use the paper language for all printed strings. No prose declaring this a simulation or invented document.')
    instructions = {
        'front': front,
        'references': 'Return {"data": [{"text":"full formatted reference","cite":"short author-year citation"}, ...]}. '
                      'Give exactly 12 credible invented references for this field; use no real DOI or real institution.',
        'formulas': 'Return {"data":[{"after":prose_index,"element":{"type":"equation","id":"eq:unique",'
                    '"latex":"ASCII KaTeX","numbered":true}},...]}. Give 3 numbered equations including '
                    'one \\begin{aligned} environment. Use standard KaTeX commands; no Unicode in math. '
                    'Place after prose elements 6, 10, and 14.',
        'tables': 'Return {"data":[{"after":prose_index,"element":{"type":"table","id":"tab:unique",'
                  '"caption":"...","header":[["column",...]],"rows":[["value",...]],"note":"..."}},...]}. '
                  'Give two rectangular tables, one with at least 6 columns and 4-8 data rows, '
                  'short column labels. Place after prose elements 9 and 15. No math in cells.',
        'charts_figures': 'Return {"data":[{"after":prose_index,"element":typed_element},...]}. Give one chart '
                         '{type:"chart",id:"fig:chart",caption,chart_type:"bar",labels:[strings],'
                         'series:[{name,values:[numbers]}]} and one figure '
                         '{type:"figure",id:"fig:diagram",figure_type:"block_diagram",caption,description,'
                         'labels:[3-6 short strings each <=28 characters]}. Place after prose elements 12 and 18. '
                         'Every data item must be an insertion object containing exactly one chart or figure element. '
                         'Return no front matter, prose, headings, or other element types in this group.',
        'code': 'Return {"data":[]}; this paper does not need a code listing.',
        'body': 'Return {"data":[typed prose elements in reading order]}. Types: heading {type,level:1|2,text}, '
                'paragraph {type,text}, list {type,ordered:boolean,items:[strings]}, box {type,kind:"remark",title,text}. '
                'Write 5 or 6 level-1 sections, at least one level-2 subsection, and substantial continuous research prose. '
                f'At least {LENGTH_WORDS[variables["paper_length"]] + 200} words in prose alone. '
                'Use inline $ASCII math$ in at least 5 distinct paragraphs, at least one \\fn{footnote text}, '
                'cite ALL 12 references with \\cite{1}, \\cite{2}, etc (also for author_year style); '
                'reference ALL table, figure, and code ids provided in context using \\ref{tab:id} / \\ref{fig:id}. '
                'Use each actual id from context exactly. Cite floats early, before their placement index. '
                'Do not put display equations, tables, figures or charts in this group; those groups are immutable.',
    }
    plan = variables.get('element_plan')
    if plan:
        instructions['references'] = 'Return {"data":[{text:"formatted reference",cite:"author-year"},...]}. Follow the reference count in the plan.'
        instructions['formulas'] = 'Return {"data":[{after:prose_index,element:{type:"equation",id:"eq:unique",latex:"ASCII KaTeX",numbered:true}},...]}. Follow the equation count; zero means empty list.'
        instructions['tables'] = 'Return {"data":[{after:prose_index,element:{type:"table",id:"tab:unique",caption,header:[[cells]],rows:[[cells]],note}},...]}. Follow the table count. Include a wide table with six columns, multirow/multicolumn headers, numeric results and bold best values using {text,bold:true} cells.'
        instructions['charts_figures'] = 'Return {"data":[{after:prose_index,element:typed_chart_or_figure},...]}. Follow chart and figure counts and kinds in the plan. Charts use labels, series [{name,values,errors?}], x_label, y_label, legend_position:"outside". Scatter uses points; box uses stats. Every chart and figure requires a non-empty caption and a fig:lowercase_id. Figures use figure_type, description, labels (3-10 short labels), panels for multi_panel. Supply plausible units and measured uncertainties; use multiple series where natural. Keep values consistent with accepted tables and prose.'
        instructions['code'] = 'Return {"data":[{after:prose_index,element:{type:"code",id:"alg:unique",language:"pseudocode",caption,lines:[strings]}},...]}. Follow code count; zero means empty list; 3-30 lines per listing.'
        instructions['body'] = instructions['body'].replace('5 or 6 level-1 sections', 'archetype-appropriate level-1 sections following the plan').replace('ALL 12 references', 'ALL references')
    prompt_variables = {k: v for k, v in variables.items() if k != 'element_plan'}
    group_plan = {}
    if plan:
        kinds = KINDS.get(name, set()) | ({'references'} if name == 'references' else set())
        group_plan = {k: v for k, v in plan['counts'].items() if k in kinds}
        if name == 'charts_figures':
            group_plan.update(chart_types=plan['chart_types'], figure_types=plan['figure_types'])
        if name == 'body':
            group_plan = {'sections': plan['sections']}
        group_plan['archetype'] = plan['archetype']
    allowed = KINDS.get(name, set())
    forbidden = sorted(set().union(*KINDS.values()) - allowed)
    return (json.dumps(prompt_variables, ensure_ascii=False) + '\nGroup plan (instructions only, never content fields):\n' +
            json.dumps(group_plan, ensure_ascii=False) + '\nForbidden element types: ' + ', '.join(forbidden) +
            '\n' + instructions[name] +
            '\nForbidden printed words (whole-word, any case): sample, synthetic, fictional, placeholder, example.invalid. '
            'Use naturally occurring terminology without these words, including in references and captions.\n' +
            '\nMath command allowlist enforced by this engine: ' + ', '.join(sorted(LATEX_COMMANDS)) +
            '. Use ONLY these backslash commands in display AND inline math. '
            'Use plain ASCII spacing, and literal letters when a Greek name is not allowed.\n' +
            '\nContext (accepted groups, do not modify):\n' + json.dumps(groups, ensure_ascii=False))


async def build_bank(n, output, jobs=4, max_usd=None):
    if max_usd is not None and (not math.isfinite(max_usd) or max_usd < 0):
        raise ValueError('max-usd must be finite and non-negative')
    if jobs < 1:
        raise ValueError('jobs must be positive')
    if not 1 <= n <= 20:
        raise ValueError('bank size must be 1-20')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    record_path = output / 'bank_run.json'
    previous = json.loads(record_path.read_text(encoding='utf-8')) if record_path.exists() else None
    if previous and previous.get('status') == 'RUNNING':
        # A live attempt can resume from its group checkpoints without losing usage.
        record = previous
    else:
        attempt = int(previous.get('attempt', 0)) + 1 if previous else 1
        if previous:
            history = output / 'runs'
            history.mkdir(parents=True, exist_ok=True)
            archived = history / f'bank_attempt_{int(previous.get("attempt", attempt - 1)):02}.json'
            if not archived.exists():
                archived.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding='utf-8')
        record = {
            'attempt': attempt,
            'command': (f'factory content academic_paper --n {n} --out {output} --jobs {jobs}'
                        + (f' --max-usd {max_usd}' if max_usd is not None else '')),
            'started': datetime.now(timezone.utc).isoformat(), 'calls': [], 'papers': [],
            'cumulative_spend_before_usd': float(previous.get('cumulative_project_spend_usd',
                previous.get('cumulative_spend_usd', previous.get('cost_usd', 0.0)))) if previous else 0.0,
            'cumulative_bank_spend_before_usd': float(previous.get('cumulative_bank_spend_usd',
                previous.get('cumulative_spend_usd', previous.get('cost_usd', 0.0)))) if previous else 0.0,
        }
    record['max_usd'] = max_usd
    record['status'] = 'RUNNING'
    record.pop('ended', None)
    llm = Router(force='luna')
    endpoint = llm.endpoint('academic_paper')
    if endpoint.model_name() != 'gpt-6-luna' or endpoint.params.get('reasoning_effort') not in {'medium', 'high'}:
        raise ValueError('bank requires gpt-6-luna with medium or high reasoning')
    shared = load_config()
    fields = ['materials modelling', 'signal processing', 'robotics', 'hydrology', 'linguistics',
              'ecology', 'transport', 'energy storage', 'computer vision', 'acoustics',
              'soil mechanics', 'network optimization', 'thermal engineering', 'ocean dynamics',
              'computational biology', 'urban climatology', 'polymer rheology', 'geodesy',
              'optical metrology', 'agricultural engineering']

    def save():
        record['updated'] = datetime.now(timezone.utc).isoformat()
        if record['status'] in {'PASS', 'FAIL'}:
            record['ended'] = record['updated']
        record['cost_usd'] = sum(row['cost_usd'] for row in record['calls'])
        record['cumulative_bank_spend_usd'] = record.get('cumulative_bank_spend_before_usd', 0.0) + record['cost_usd']
        record['cumulative_project_spend_usd'] = record.get('cumulative_spend_before_usd', 0.0) + record['cost_usd']
        record['cumulative_spend_usd'] = record['cumulative_project_spend_usd']
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')

    save()

    async def ask(index, name, variables, groups, error=None, bad_reply=None):
        if max_usd is not None and sum(row['cost_usd'] for row in record['calls']) >= max_usd:
            raise RuntimeError(f'run spending guard reached ${max_usd:.2f}')
        spent = record.get('cumulative_spend_before_usd', 0.0) + sum(row['cost_usd'] for row in record['calls'])
        # Reserve a conservative maximum for every potentially in-flight worker.
        if spent + .10 * jobs >= 50:
            raise RuntimeError('spending guard: next call could exceed $50')
        task = group_prompt(name, variables, {k: v for k, v in groups.items() if k != name})
        if error:
            task += '\nRepair only this group: ' + str(error) + '\nCurrent group:\n' + (bad_reply if bad_reply is not None else json.dumps(groups.get(name), ensure_ascii=False))
            task += '\nPreserve valid existing element ids; correct invalid ids to the required syntax. Other accepted groups reference these ids.'
            if name == 'formulas':
                task += ('\nRewrite each equation using Latin variable names and only these commands: '
                         '\\begin{aligned}, \\end{aligned}, \\frac, \\sum, \\partial, \\exp, \\mathrm, '
                         '\\left, \\right, \\neq. Use literal ASCII letters instead of ALL Greek commands. '
                         'Use a plain space instead of backslash spacing commands. Check every equation before returning.')
        start = time.monotonic()
        try:
            result = await llm.generate('academic_paper', [
                {'role': 'system', 'content': shared.system + '\nReturn a JSON object with exactly one key: data.'},
                {'role': 'user', 'content': task}], use_cache=not bool(error))
        except Exception as error:
            record.setdefault('errors', []).append({'paper': index, 'group': name,
                'type': type(error).__name__, 'http_status': getattr(error, 'status_code', None)})
            save()
            raise
        record['calls'].append({'paper': index, 'group': name, 'repair': bool(error),
                                'seconds': time.monotonic() - start, **result.model_dump(exclude={'text'})})
        save()  # account for every billed reply before parsing or validation
        return result.text

    async def request_group(index, name, variables, groups, initial_error=None):
        error = initial_error
        bad_reply = json.dumps(groups.get(name), ensure_ascii=False) if initial_error else None
        for attempt in range(3):
            try:
                bad_reply = await ask(index, name, variables, groups, error, bad_reply)
                data = parse_json(bad_reply, GroupReply).data
                return clean_group(name, data, variables.get('element_plan'))
            except (ValueError, KeyError, TypeError) as exc:
                detail = str(exc)
                error = detail if detail.startswith(name + ':') else f'{name}: invalid group response: {detail}'
                if attempt == 2:
                    raise ValueError(error) from exc
        raise AssertionError('unreachable')

    semaphore = asyncio.Semaphore(jobs)

    async def build_paper(index):
        async with semaphore:
            path = output / f'paper_{index:02}.json'
            if path.exists():
                paper = json.loads(path.read_text(encoding='utf-8'))
                validate_paper(paper)
                if not any(row.get('content_id') == paper['content_id'] for row in record['papers']):
                    rows = [row for row in record['calls'] if row['paper'] == index]
                    record['papers'].append({'content_id': paper['content_id'], 'seconds': sum(row['seconds'] for row in rows),
                        'calls': len(rows), 'tokens_in': sum(row['tokens_in'] for row in rows),
                        'tokens_out': sum(row['tokens_out'] for row in rows),
                        'cost_usd': sum(row['cost_usd'] for row in rows), 'rule_failures': 0,
                        'repair_calls': sum(bool(row['repair']) for row in rows),
                        'hash': paper.get('hash'), 'resumed': True})
                    save()
                return
            variables = {'lang': 'vi' if index % 2 else 'en', 'field': fields[index - 1],
                         'paper_length': ['short', 'medium', 'long'][(index - 1) % 3],
                         'citation_style': 'numeric' if ((index - 1) // 2) % 2 == 0 else 'author_year'}
            variables['element_plan'] = draw_paper_plan(index - 1, variables['field'])
            checkpoint = output / f'.paper_{index:02}.groups.json'
            groups = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {}
            start = time.monotonic()
            for name in GROUPS:
                try:
                    groups[name] = clean_group(name, groups[name], variables['element_plan'])
                except (KeyError, ValueError, TypeError) as invalid:
                    log(f'bank paper {index}/{n} {variables["lang"]}: {name}')
                    groups[name] = await request_group(index, name, variables, groups,
                                                       str(invalid) if name in groups else None)
                    checkpoint.write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding='utf-8')
            checkpoint.write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding='utf-8')
            paper = {'content_id': f'paper_{index:02}', 'variables': variables, 'lang': variables['lang']}
            for attempt in range(8):
                try:
                    paper['values'] = assemble(groups)
                    validate_paper(paper)
                    break
                except (ValueError, KeyError, TypeError) as error:
                    if attempt == 7:
                        raise
                    name = repair_owner(error, paper.get('values', {}))
                    log(f'bank paper {index}: repair {name}: {str(error)[:180]}')
                    groups[name] = await request_group(index, name, variables, groups, error)
                    checkpoint.write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding='utf-8')
            paper['hash'] = digest(paper)
            path.write_text(json.dumps(paper, ensure_ascii=False, indent=2), encoding='utf-8')
            path.with_suffix('.profile.json').write_text(json.dumps(profile(paper), ensure_ascii=False, indent=2), encoding='utf-8')
            rows = [row for row in record['calls'] if row['paper'] == index]
            record['papers'].append({'content_id': paper['content_id'], 'seconds': time.monotonic() - start,
                                     'calls': len(rows), 'tokens_in': sum(row['tokens_in'] for row in rows),
                                     'tokens_out': sum(row['tokens_out'] for row in rows),
                                     'cost_usd': sum(row['cost_usd'] for row in rows),
                                     'repair_calls': sum(bool(row['repair']) for row in rows),
                                     'rule_failures': 0, 'hash': paper['hash']})
            save()

    async def checked_paper(index):
        try:
            return await build_paper(index)
        except Exception as error:
            failure = {'paper': index, 'error_type': type(error).__name__,
                       'http_status': getattr(error, 'status_code', None)}
            if isinstance(error, (ValueError, KeyError, TypeError)):
                failure['validation_error'] = str(error)
            record.setdefault('failures', []).append(failure)
            save()
            log(f'bank paper {index} failed: {failure}')
            raise

    try:
        outcomes = await asyncio.gather(*(checked_paper(i) for i in range(1, n + 1)), return_exceptions=True)
        errors = [result for result in outcomes if isinstance(result, BaseException)]
        if errors:
            record['status'] = 'FAIL'
            save()
            log('bank failures: ' + ', '.join(f"paper {f['paper']}: {f['error_type']}" for f in record.get('failures', [])))
            return 1
        papers = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(output.glob('paper_??.json'))]
        assert len(papers) == n and sum(p['variables']['lang'] == 'vi' for p in papers) == (n + 1) // 2
        for paper in papers:
            validate_paper(paper)
            (output / (paper['content_id'] + '.profile.json')).write_text(
                json.dumps(profile(paper), ensure_ascii=False, indent=2), encoding='utf-8')
        (output / 'FROZEN.json').write_text(json.dumps({p['content_id']: p['hash'] for p in papers}, indent=2), encoding='utf-8')
        record['status'] = 'PASS'
        save()
        return 0
    except Exception as error:
        record['status'] = 'FAIL'
        # Avoid including SDK exceptions which might contain request credentials.
        record['error_type'] = type(error).__name__
        save()
        raise
