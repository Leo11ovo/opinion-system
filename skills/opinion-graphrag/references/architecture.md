# Architecture

## Active Retrieval Stack

Use RouterRAG as the live retrieval pipeline.

Main files:

- `backend/src/utils/rag/ragrouter/router_retrieve_data.py`
- `backend/src/rag/planner/engine.py`

Key behaviors in the active stack:

- planner-driven retrieval hints
- expert overlay from Neo4j expert graph
- opinion graph retrieval as a separate evidence source
- mixed retrieval across GraphRAG, NormalRAG, and TagRAG
- optional LLM answer structuring and summarization

## Important Constraint

The old standalone GraphRAG pipeline has been removed. Do not reference:

- `backend/src/rag/graph_rag.py`
- `backend/src/rag/graph_pipeline.py`
- `backend/src/rag/retrievers/graph_retriever.py`

## Conceptual Model

- Evidence graph: answers what happened and what supports the claim.
- Expert graph: answers how to interpret, judge, and respond.
- RouterRAG should retrieve evidence first, then use expert overlay to improve routing, ranking, and answer structure.

## Current Main Parameters

RouterRAG supports:

- `mode`: `mixed`, `graphrag`, `normalrag`, `tagrag`
- `topk_graphrag`
- `topk_normalrag`
- `topk_tagrag`
- `enable_query_expansion`
- `enable_llm_summary`
- `llm_summary_mode`
- `return_format`
- `enable_expert_overlay`
- `enable_expert_rewrite`
- `enable_expert_hints`
- `enable_expert_answer_structure`

## Preferred Principle

Use one retrieval entrypoint and vary the strategy by question type instead of creating multiple independent GraphRAG pipelines.
