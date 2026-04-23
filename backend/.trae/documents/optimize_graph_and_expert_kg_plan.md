# Plan: Optimize GraphRAG and Build Expert Knowledge Graph

## Objective
This plan addresses two main requirements:
1.  **Graph Construction Optimization**: Refine the graph construction pipeline to follow the `Post -> Chunk -> Entity/Claim` granularity, aligning it with the multi-path RAG system (NormalRAG, TagRAG, GraphRAG).
2.  **Expert Knowledge Graph (ExpertKG)**: Build a dedicated "Expert Knowledge Base" for public opinion analysis theories and methodologies. This KG will act as the "Theoretical Brain," providing guidance for analyzing the "Factual Muscle" from the data source KG.

## Phase 1: Optimize Data Source Graph (Post -> Chunk -> Entity/Claim)

The goal is to shift entity/claim extraction from the `Post` level to the `Chunk` level for finer granularity and better retrieval precision.

### 1.1 Refactor Entity Extraction Logic
-   **Modify `src/graph/entity_extraction.py`**:
    -   Update `extract_entities_and_claims` (or equivalent function) to accept `chunk_text` instead of `post_content`.
    -   Change the extraction flow:
        -   Old: Iterate Posts -> LLM Extract -> Write `(Post)-[:MENTIONS]->(Entity)`.
        -   New: Iterate Posts -> Split into Chunks -> Iterate Chunks -> LLM Extract -> Write `(Chunk)-[:MENTIONS]->(Entity)`.
    -   Ensure `Post` still connects to `Chunk` via `[:HAS_CHUNK]`.
    -   *Implicit Relationship*: `Post` mentions `Entity` if `Post` has a `Chunk` that mentions `Entity`. We can create a direct `(Post)-[:MENTIONS]->(Entity)` relationship as an aggregation for easier querying if needed, or derive it at query time. **Decision**: Create both `(Chunk)-[:MENTIONS]->(Entity)` (for precision) and aggregate to `(Post)-[:MENTIONS]->(Entity)` (for compatibility/performance).

### 1.2 Update Graph Construction Pipeline
-   **Modify `src/graph/build_graph.py`**:
    -   Ensure chunking happens *before* entity extraction.
    -   Pass chunks to the extraction module.

### 1.3 Adapt Retrieval Logic (Multi-path RAG)
-   **Modify `src/rag/storage/router_retrieve_data.py`**:
    -   **GraphRAG Search (`_graphrag_search`)**:
        -   Update Cypher queries to utilize `Chunk` level connections.
        -   Query path: `Entity/Claim -> Chunk -> Post -> Event`.
        -   Return `Chunk.text` as evidence instead of `Post.contents` to reduce token usage and improve relevance.
    -   **NormalRAG Search (`_normalrag_search`)**:
        -   No major changes needed (already using Chunks), but ensure metadata (like linked entities) is consistent.

## Phase 2: Build Expert Knowledge Graph (ExpertKG)

Create a separate knowledge graph for theories, methods, and guidelines.

### 2.1 Schema Definition
-   **Labels**: `Theory`, `Method`, `Indicator`, `Stakeholder`, `EventType`, `Tool`, `Guideline`, `CaseStudy`.
-   **Relationships**: `GUIDES`, `APPLIES_TO`, `MEASURES`, `INFLUENCES`, `HAS_INDICATOR`, `REFERENCES`, `WARNING`.
-   **Properties**: `name`, `description`, `source_pdf` (origin), `embedding` (vector), `confidence`.

### 2.2 Expert Knowledge Ingestion
-   **Create `src/expert_kg/builder.py`**:
    -   Function to ingest expert knowledge (from JSON/YAML or hardcoded for now, expandable to PDF parsing later).
    -   Function to generate embeddings for nodes (using the same embedding model as the main RAG).
    -   Function to write nodes and relationships to Neo4j.
    -   **Note**: Use a distinct label prefix or a separate Neo4j database/namespace to avoid collision with the Data Source KG? **Decision**: Use distinct labels (defined above) within the same Neo4j instance for easier cross-graph querying if needed, but treat them logically as separate domains.

### 2.3 Expert RAG Retrieval
-   **Create `src/rag/retrievers/expert_retriever.py`**:
    -   Logic to retrieve "Guidance" from ExpertKG.
    -   Input: User Query (e.g., "Analyze the brand crisis...").
    -   Process:
        1.  Vector search on ExpertKG nodes to find relevant `Theory`, `Method`, or `EventType`.
        2.  Traverse 1-4 hops to gather connected `Guideline`, `Indicator`, `Warning`.
        3.  Format the path as a "Guidance" string.

### 2.4 Integration with Main RAG Pipeline
-   **Modify `src/rag/storage/router_retrieve_data.py` (or `AdvancedRAGSearcher`)**:
    -   Add a "Planning/Guidance" step before the main data retrieval.
    -   **Workflow**:
        1.  **Expert Step**: Query ExpertKG -> Get Guidance (e.g., "Check negative sentiment > 60%").
        2.  **Prompt Augmentation**: Inject Guidance into the query/system prompt.
        3.  **Data Step**: Execute NormalRAG/GraphRAG on Data Source KG.
        4.  **Synthesis**: LLM generates answer using Guidance + Data Facts.

## Phase 3: Verification & Testing

-   **Test Phase 1**: Rebuild graph for a sample topic (`test`). Verify `Chunk -> Entity` relationships in Neo4j. Test `router_retrieve` to ensure it returns chunks.
-   **Test Phase 2**: Ingest sample expert data (e.g., "Agenda Setting Theory"). Verify nodes in Neo4j.
-   **Test Phase 3**: Run a full query. Check logs to see if "Guidance" is retrieved and used in the final LLM call.

## Implementation Roadmap

1.  **Refactor Extraction**: Update `entity_extraction.py` for Chunk granularity.
2.  **Update Pipeline**: Adjust `build_graph.py` and `sync_graph_to_vector.py`.
3.  **Expert KG Builder**: Implement `src/expert_kg/` module.
4.  **RAG Integration**: Wire ExpertKG retrieval into the main searcher.
