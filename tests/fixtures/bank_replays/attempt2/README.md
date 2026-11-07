# Round 3 live bank attempt 2 offline replay

Source record: `.doc_local/leverage_uniqueness/runs/round3_live_bank_attempt2.json` (76 calls, six failures, $0.16631622).

`replies.json` contains all 34 matching disk-cache replies with their exact usage record, source-cache filename and original LLMResult. The remaining 42 calls were repairs, which deliberately bypass disk-cache reads/writes after Round 3; there are no raw disk replies for them. `uncached_calls.json` retains their call metadata without inventing responses. Six `paper_NN.groups.json` files are exact final accepted checkpoints copied from content/academic_paper_v2; the live bank remains unchanged.

`tests/test_bank_attempt2.py` injects each of the 34 available replies through real build_bank generation, group validation, assembly, full paper validation and repair prompting, without HTTP. The six final checkpoints also run together through real full validation: each now requests its owning charts_figures repair, with the failed group and typed validation error. Missing captions remain a model repair rather than fabricated text. Paper 5 used named box-stat dictionaries; these can be converted exactly into the supported ordered five-number lists, after which other invalid IDs/captions still require correctly routed repairs.

Tests also cover all five non-prose element owners, safe numeric/error-bar normalization, aligned category removal and preservation of invalid data for repair when a conversion would be unsafe. Real module and installed-console subprocesses use a zero-dollar budget and deliberate dummy credentials to verify exit 1 and zero model calls. A separate regression proves the CLI rejects a persisted FAIL/failure list even if a future builder mistakenly returns 0.
