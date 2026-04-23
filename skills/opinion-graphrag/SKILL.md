---
name: opinion-graphrag
description: Work with the opinion-system GraphRAG and RouterRAG stack. Use when Codex needs to run retrieval against the current opinion-system backend, choose different retrieval strategies for different question types, explain how the dual-graph design should be queried, debug GraphRAG or RouterRAG behavior, or design/adjust question-type routing for factual, explanatory, comparative, or decision-oriented opinion-analysis queries.
---

# Opinion GraphRAG

Use this skill to work with the current opinion-system retrieval stack.

The active retrieval entrypoint is RouterRAG, not the deleted legacy `graph_rag.py` pipeline.
The main code path is:

- `backend/src/utils/rag/ragrouter/router_retrieve_data.py`
- `backend/src/rag/planner/engine.py`

## Workflow

1. Treat retrieval as `evidence first, expert augmentation second`.
2. Classify the user query into a question type before selecting parameters.
3. Use the strategy presets in `references/strategy-matrix.md`.
4. Prefer the deterministic wrapper in `scripts/run_routerrag.py` when you need to execute retrieval.
5. If the task is architectural or debugging oriented, read `references/architecture.md`.

## Question Types

- `fact`: ask what happened, who participated, where the activity is concentrated, or what the measured values are.
- `explain`: ask why something happened, why a judgment is valid, or what theory/frame explains the case.
- `compare`: ask for similar cases, analogies, differences, or historical comparison.
- `decision`: ask what to do next, how to respond, or which strategy is appropriate.
- `explore`: broad open-ended analysis when no narrower type is obvious.

## Run Retrieval

Run the wrapper from the repo root:

```bash
python skills/opinion-graphrag/scripts/run_routerrag.py --topic <topic> --query "<question>"
```

Override the detected question type when needed:

```bash
python skills/opinion-graphrag/scripts/run_routerrag.py --topic <topic> --query "<question>" --question-type decision
```

For architecture and strategy details, read:

- `references/architecture.md`
- `references/strategy-matrix.md`
