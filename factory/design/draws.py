from random import Random
CRITERIA=('layout','style','reading_order','orientation')
def design_seed(seed,index):return seed*1000003+index
def draws(seed):
    rng=Random(seed)
    return {c:[rng.random() for _ in range(6)] for c in CRITERIA}
