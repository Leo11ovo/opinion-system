# RouterRAG RLHF Playbook

## 1) Build and Data

- Source text can come from `txt/jsonl/csv` via `scripts/build_routerrag_ab.py`.
- Use smaller sample for fast validation, then expand.
- Keep A/B topic names explicit (`ab10_sentence`, `ab10_window`).

## 2) Retrieval Debug Priority

1. Confirm topic has `vector_db` under project path.
2. Confirm API payload includes `topic` and correct retrieval mode.
3. Check backend logs for:
- table loading success (`normalrag/graphrag_texts`)
- query expansion success
- summary generation success

## 3) Missing LLM Summary

Most common root cause is prompt config mismatch.

Check `backend/configs/prompt/router_retrieve` first:
- `<topic>.yaml` may not exist.
- `默认.yaml` must include:
  - `time_extraction`
  - `time_matching`
  - `result_summary_strict`
  - `result_summary_supplement`

Expected fallback log:
- `提示词文件不存在或不可用: <topic>.yaml，已回退到 默认.yaml`

Expected success log:
- `资料整理完成：共 (xxx字)`

## 4) Frontend Displays 0 But Backend Has Recall

- `total` is after threshold filtering.
- `raw_total` is before threshold filtering.
- If `raw_total > 0` and `total = 0`, lower threshold or inspect score distribution.

## 5) RLHF Tuning Loop

Use this order:

1. Submit feedback samples first.
2. Pull stats.
3. Generate suggestion.
4. Apply only when enough samples.

Operational guardrail:
- Do not apply if `total_feedback < 8`.

CLI:

```bash
python scripts/run_rlhf_tune.py --topic <topic> --limit 1000
python scripts/run_rlhf_tune.py --topic <topic> --limit 1000 --apply
```

## 6) Noise vs Real Failure

- `neo4j cartesian product` notifications are performance warnings, not immediate hard failures.
- `id deprecated` is a deprecation warning.
- `/api/query` postgres timeout impacts remote query module, not necessarily RouterRAG retrieve.
