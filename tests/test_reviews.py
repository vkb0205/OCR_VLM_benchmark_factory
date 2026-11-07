"""Review selection rejects stale and text-flagged approvals."""
import json
from factory.contract.models.review import Review, PageReview, BlockReview
from factory.runner.reviews import status, bundle_hash, load_review

def test_text_wrong_prevents_approval():
    review=Review(subset='en',doc_id='d',bundle_hash='hash',pages={'1':PageReview(decision='approved',blocks={'b':BlockReview(verdict='text_wrong',by='test',at='now')})})
    assert status(review,1)=='flagged'

def test_all_pages_required():
    review=Review(subset='en',doc_id='d',bundle_hash='hash',pages={'1':PageReview(decision='approved')})
    assert status(review,1)=='approved'
    assert status(review,2)!='approved'

def test_stale_review_is_excluded(tmp_path):
    bundle=tmp_path/'subset/documents/type/d';bundle.mkdir(parents=True)
    for name in ['document.json','content.json','pagination.json']:(bundle/name).write_text('{}',encoding='utf-8')
    review=Review(subset='subset',doc_id='d',bundle_hash=bundle_hash(bundle))
    reviews=tmp_path/'subset/reviews';reviews.mkdir()
    (reviews/'d.json').write_text(review.model_dump_json(),encoding='utf-8')
    assert load_review(bundle) is not None
    (bundle/'document.json').write_text('{"changed":true}',encoding='utf-8')
    assert load_review(bundle) is None
