# Round 3 offline replays

JSON reply fixtures are exact LLMResult objects copied from `.cache/llm`, with a `source_cache` filename added. Token pairs identify calls in `.doc_local/leverage_uniqueness/runs/round2_live_bank_attempt1.json`:

- 5847/4938 and 5959/5124: paper 1 original and repaired formulas, including foreign code/charts/tables/references.
- 741/5139: paper 1 accepted front checkpoint reply.
- 741/7641: paper 3 front reply with echoed plan keys.
- 14305/7926: paper 3 original body prose.
- Hidden `.paper_01.groups.json` and `.paper_03.groups.json`: exact attempt-1 accepted checkpoints, copied without modifying the live bank.

Paper 2 has no reply: its recorded status-less APIError is recreated with the real OpenAI SDK exception class and an offline httpx request. Investigation of paper 3's complete checkpoint shows the recorded `body: element 6 (figure)` error actually comes from the charts_figures group's `fig:F1` id, after insertion into the assembled body. Its saved prose contains no foreign figure. Tests cover both the requested foreign-body-element regression and the actual checkpoint failure, routing the latter to charts_figures with the bad reply and validation error.
