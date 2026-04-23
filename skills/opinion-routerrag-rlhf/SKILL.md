---
name: opinion-routerrag-rlhf
description: Operate and debug the opinion-system RouterRAG + RLHF loop end-to-end. Use when Codex needs to build/import RouterRAG indexes, diagnose retrieval quality regressions, fix missing LLM summary output, run feedback-driven tuning, or explain A/B chunking experiment results for reporting.
---

# Opinion RouterRAG RLHF

Use this skill for the practical workflow we stabilized in this repo: index build -> retrieval debug -> summary debug -> feedback collection -> RLHF tuning.

Core code paths:

- `scripts/build_routerrag_ab.py`
- `backend/src/utils/rag/ragrouter/router_vec_data.py`
- `backend/src/utils/rag/ragrouter/router_retrieve_data.py`
- `backend/src/rag/feedback/rlhf_tuner.py`
- `scripts/run_rlhf_tune.py`
- `frontend/src/views/retrieval/RouterRAGView.vue`

## Workflow

1. Build or import topic indexes first.
2. Verify retrieval returns `results` and `summary`.
3. If summary missing, check `router_retrieve` prompt files first.
4. Collect user feedback from frontend before applying RLHF.
5. Run tuning in suggest mode, then apply mode.
6. Save experiment outcomes into report notes.

## Quick Commands

Build A/B index:

```bash
python scripts/build_routerrag_ab.py --project-id <project_id> --source-text-dir <dir> --sample-ratio 0.1 --topic-a ab10_sentence --topic-b ab10_window --chunk-size 220 --chunk-overlap 40
```

Run RLHF tuning from feedback:

```bash
python scripts/run_rlhf_tune.py --topic <topic> --limit 1000
python scripts/run_rlhf_tune.py --topic <topic> --limit 1000 --apply
```

## Non-Negotiable Checks

- If log has `未找到time_extraction提示词配置` or `未找到strict模式的提示词配置`, inspect:
  - `backend/configs/prompt/router_retrieve/<topic>.yaml`
  - `backend/configs/prompt/router_retrieve/默认.yaml`
- If frontend shows 0 but logs show recall, compare `raw_total` vs filtered `total`.
- Never apply RLHF tuning when `total_feedback < 8`.
- Distinguish unrelated infrastructure errors:
  - `/api/query` postgres timeout does not mean `/api/rag/routerrag/retrieve` failed.

## Reporting Guidance

- Explain changes by cause/effect:
  - chunk strategy changed -> recall quality changed
  - prompt config fixed -> LLM summary restored
  - feedback accumulated -> RLHF apply became enabled
- Report both retrieval quality and operational stability.

Read detailed checklist:

- `references/playbook.md`
