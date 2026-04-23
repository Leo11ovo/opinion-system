# Plan: Rebuild NormalRAG from Knowledge Graph Chunks

## Objective
Rebuild the NormalRAG vector database using existing `Chunk` nodes from the Neo4j Knowledge Graph to ensure consistency between GraphRAG and NormalRAG. This replaces the previous sentence-based splitting strategy with the graph's chunk-based strategy.

## Context
- **Current NormalRAG**: Uses regex-based sentence splitting (in `router_vec_data.py`), which is inconsistent with GraphRAG's chunking (512 chars).
- **Goal**: Align NormalRAG to use the same `Chunk` nodes as GraphRAG.
- **Data Source**: Neo4j `Chunk` nodes (linked to `Post` via `HAS_CHUNK`).
- **Target**: LanceDB table `normalrag` located at `src/utils/rag/ragrouter/{topic}数据库/vector_db`.

## Steps

1.  **Create Migration Script (`rebuild_normalrag_from_graph.py`)**
    -   **Fetch Data**: Query Neo4j for all `Chunk` nodes linked to `Post` nodes for a given topic.
        -   Retrieve: `Chunk.id`, `Chunk.text`, `Post.id` (as `doc_id`), `Post.title` (as `doc_name`), `Post.published_at` (as `time`).
    -   **Compute Embeddings**: Use the project's embedding client (`src.utils.embedding.get_sync_client`) to generate vectors for each chunk's text.
    -   **Initialize LanceDB**:
        -   Target path: `backend/src/utils/rag/ragrouter/{topic}数据库/vector_db`.
        -   Table name: `normalrag`.
        -   Schema:
            -   `sentence_id`: String (mapped from Chunk ID)
            -   `sentence_text`: String (mapped from Chunk Text)
            -   `sentence_vec`: Vector (Dimension from model)
            -   `doc_id`: String (mapped from Post ID)
            -   `doc_name`: String (mapped from Post Title)
            -   `time`: String (mapped from Post Published At)
    -   **Write Data**: Batch insert the processed chunks into LanceDB.

2.  **Execute Migration**
    -   Run the script for the user's current topic (e.g., `test`).

3.  **Verify NormalRAG Retrieval**
    -   Run `router_retrieve_data.py` with `--mode normalrag`.
    -   Confirm it successfully connects to the new database and returns results.

## Verification
-   **Check 1**: Script runs without errors and reports the number of chunks processed.
-   **Check 2**: LanceDB table `normalrag` exists and contains data.
-   **Check 3**: `router_retrieve_data.py` returns valid search results from NormalRAG.
