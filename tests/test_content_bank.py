"""Bank integrity, repair isolation and information boundary tests."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from factory.content.bank import assemble, digest, repair_owner, validate_group, validate_paper
from factory.content.profile import profile


def fixture():
    return json.loads(Path('tests/fixtures/academic_paper_vi_short.json').read_text(encoding='utf-8'))


def test_profile_excludes_prose_and_names():
    paper = fixture()
    result = profile(paper)
    encoded = json.dumps(result, ensure_ascii=False)
    assert paper['values']['abstract'] not in encoded
    assert paper['values']['title'] not in encoded
    assert all(a['name'] not in encoded for a in paper['values']['authors'])
    assert result['display_equations'] >= 3
    assert result['reference_count'] == len(paper['values']['references'])
    assert result['widest_column_count'] >= 1
    assert result == json.loads(json.dumps(result))


def test_hash_detects_content_or_variable_change():
    paper = fixture()
    original = digest(paper)
    paper['values']['title'] += ' changed'
    assert digest(paper) != original
    paper = fixture()
    paper['variables']['citation_style'] = 'author_year'
    assert digest(paper) != original


def test_repair_targets_owning_group():
    values = {'body': [{'type': 'paragraph'}, {'type': 'table'}, {'type': 'equation'}]}
    assert repair_owner('body: element 2: invalid table shape', values) == 'tables'
    assert repair_owner('body: element 3: LaTeX must be ASCII', values) == 'formulas'
    assert repair_owner('every reference must be cited', values) == 'body'
    assert repair_owner('authors: affiliation not found', values) == 'front'
    values['body'][2]['latex'] = r'x \\quad y'
    assert repair_owner('LaTeX ' + repr(values['body'][2]['latex']) + ': commands are not allowed', values) == 'formulas'


def test_group_rejects_elements_owned_by_another_group():
    invalid = [{'after': 0, 'element': {'type': 'front', 'title': 'Wrong group'}}]
    with pytest.raises(ValueError, match='charts_figures: element 1 has type'):
        validate_group('charts_figures', invalid)
    assert repair_owner('charts_figures: element 1 has type', {'body': []}) == 'charts_figures'


def test_group_accepts_only_well_shaped_insertions():
    valid = [{'after': 3, 'element': {'type': 'chart', 'id': 'fig:trial'}}]
    assert validate_group('charts_figures', valid) == valid
    with pytest.raises(ValueError, match='charts_figures: item 1 must contain'):
        validate_group('charts_figures', [{'after': 'three', 'element': {'type': 'chart'}}])


def test_assembling_preserves_accepted_groups():
    groups = {'front': {'title': 'Title'}, 'references': [],
              'body': [{'type': 'heading'}, {'type': 'paragraph'}],
              'tables': [{'after': 1, 'element': {'type': 'table'}}]}
    before = deepcopy(groups)
    result = assemble(groups)
    assert groups == before
    assert [e['type'] for e in result['body']] == ['heading', 'table', 'paragraph']


def test_forbidden_raw_content_is_rejected_before_normalization():
    paper = fixture()
    paper['values']['title'] = 'A synthetic investigation'
    with pytest.raises(ValueError, match='front: forbidden word synthetic'):
        validate_paper(paper)


def test_seeded_plans_cover_archetypes_and_validate_counts():
    from collections import Counter
    from factory.content.bank import draw_paper_plan, FIELD_ARCHETYPES, validate_plan_counts
    plans = [draw_paper_plan(i,field) for i,field in enumerate(FIELD_ARCHETYPES)]
    assert plans == [draw_paper_plan(i,field) for i,field in enumerate(FIELD_ARCHETYPES)]
    assert len({json.dumps(p,sort_keys=True) for p in plans}) == 16
    assert min(Counter(p['archetype'] for p in plans).values()) >= 2
    assert len({p['archetype'] for p in plans}) == 6
    for plan in plans:
        body = [{'type':kind} for kind,n in plan['counts'].items() if kind!='references' for _ in range(n)]
        validate_plan_counts(plan,body,[{}]*plan['counts']['references'])
        with pytest.raises(ValueError,match='charts_figures:'):
            validate_plan_counts(plan,body+[{'type':'chart'}]*3,[{}]*plan['counts']['references'])
