import asyncio
import json
from pathlib import Path
import pytest
from factory.runner.export import eligible_documents, export_prefix, export


def test_recursive_unreviewed_preserves_subsets_and_flat_filter(tmp_path):
    for subset,design in [('a','default'),('b','agent'),('','default')]:
        root=tmp_path/subset if subset else tmp_path
        folder=root/'documents'/'academic_paper'/'same_id'
        folder.mkdir(parents=True)
        (folder/'document.json').write_text(json.dumps({'page_count':1}),encoding='utf-8')
        (folder/'spec.json').write_text(json.dumps({'design':design}),encoding='utf-8')
    folders,_=eligible_documents(tmp_path,True)
    assert len(folders)==2
    assert {export_prefix(tmp_path,f)+'same_id' for f in folders}=={'a__same_id','b__same_id'}
    assert eligible_documents(tmp_path,False)[0]==[]


@pytest.mark.parametrize('unreviewed',[True,False])
def test_language_gate_applies_in_both_modes(tmp_path,monkeypatch,unreviewed):
    import factory.runner.languages as languages
    monkeypatch.setattr(languages,'stats',lambda source:{})
    monkeypatch.setattr(languages,'balance_problems',lambda report:['imbalance'])
    with pytest.raises(ValueError,match='imbalance'):
        asyncio.run(export(tmp_path,tmp_path/'export',include_unreviewed=unreviewed))
    with pytest.raises(ValueError,match='No eligible'):
        asyncio.run(export(tmp_path,tmp_path/'export',allow_imbalance=True,include_unreviewed=unreviewed))
