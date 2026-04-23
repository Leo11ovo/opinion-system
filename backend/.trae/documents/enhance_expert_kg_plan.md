# Plan: Enhance Expert Knowledge Graph Construction

## Objective
This plan aims to refine the construction of the Expert Knowledge Graph (ExpertKG) by addressing two key user requirements:
1.  **Database Separation**: Configure the Neo4j client to use a dedicated database named `opinion-expert` for the ExpertKG, ensuring physical isolation from the main application data (if supported by the Neo4j edition).
2.  **Comprehensive Data Ingestion**: Expand the data ingestion scope to include additional relevant folders within `backend/data/expert/`, specifically `智库报告及深度分析`, `研究文章`, `舆情分析报告`, and `舆情分析方法论`.

## Phase 1: Database Configuration (Physical Separation)

### 1.1 Update Neo4j Client Configuration
-   **Modify `src/graph/neo4j_client.py`**:
    -   Update the `get_session` function (or create a new `get_expert_session` function) to accept a `database` parameter.
    -   Set the default database for expert operations to `opinion-expert`.
    -   *Note*: This assumes the user's Neo4j instance (likely Enterprise or compatible version) supports multi-database management. If it's Community Edition, this might fail or require a fallback to the default `neo4j` database with label-based isolation. **Action**: Implement with a try-catch block or configuration flag to handle potential "database not found" or licensing errors gracefully.

### 1.2 Update Expert Builder
-   **Modify `src/expert_kg/builder.py`**:
    -   Update `ExpertKGBuilder` to use the new session creation logic with `database="opinion-expert"`.
    -   Update `ExpertRetriever` to also query from this specific database.

## Phase 2: Expand Data Ingestion Scope

The current builder only processes `分析角度框架prompt` and `舆情事件库`. We need to add parsers for other valuable directories.

### 2.1 Analyze & Implement New Parsers
-   **`智库报告及深度分析` & `舆情分析报告` (Reports)**:
    -   **File Types**: `.md`, `.docx`, `.pdf`, `.txt`.
    -   **Strategy**:
        -   For `.md` and `.txt`: Extract Title, Summary (first N chars or LLM summary), and full content. Create `Report` nodes.
        -   For `.docx` and `.pdf`: Use `textract` or `pypdf` (if available) or existing RAG file loaders to extract text. *Constraint*: To keep it simple for now, prioritize `.md` and `.txt`. For binary files, if no loader exists, log a warning or use a placeholder. **Decision**: Implement a `ReportParser` for `.md` and `.txt` files first.
    -   **Schema**: Label `Report`. Properties: `title`, `content`, `date` (if parseable), `source_file`.

-   **`研究文章` (Research Papers)**:
    -   **File Types**: Mostly `.pdf` and `.docx`.
    -   **Strategy**: Similar to reports. These contain theoretical foundations.
    -   **Schema**: Label `ResearchPaper` or merge into `Theory`/`Method` if content implies. Let's use `ResearchPaper` for now.
    -   **Structure**: Subfolders like `意见领袖`, `舆情规律`, `舆论动力学` can be used as `Topic` or `Category` tags for these papers.

-   **`舆情分析方法论` (Methodology)**:
    -   **File Types**: `.md`, `.docx`.
    -   **Strategy**: High value. Parse as `Methodology` nodes.
    -   **Schema**: Label `Methodology`.

### 2.2 Refactor `builder.py` for Generic Ingestion
-   Update `ingest_from_directory` to recursively walk through `data/expert`.
-   Map folder names to Parser classes or Node Labels:
    -   `分析角度框架prompt` -> `Method` (Existing)
    -   `舆情事件库` -> `CaseStudy` (Existing)
    -   `智库报告及深度分析` -> `Report`
    -   `舆情分析报告` -> `Report`
    -   `研究文章` -> `ResearchPaper` (with sub-category support)
    -   `舆情分析方法论` -> `Methodology`

### 2.3 LLM-Enhanced Extraction (Optional/Future)
-   For unstructured text (Reports/Papers), simple regex parsing is weak.
-   **Plan**: Use a simple "Chunk + Embedding" strategy for these new document types for now (similar to NormalRAG), OR use a lightweight LLM call to extract `Summary` and `Keywords` if `enable_llm` is set.
-   **Decision**: For this iteration, treat them as **Knowledge Nodes** with full text properties and embeddings. We won't do deep entity extraction on them yet to save time/cost, but we will index them for vector search.

## Implementation Steps

1.  **Modify `neo4j_client.py`**: Add support for `database` parameter.
2.  **Update `builder.py`**:
    -   Update session usage.
    -   Add `ReportParser` (for `.md`/`.txt` in reports folder).
    -   Add `GeneralDocParser` (for other folders).
    -   Update `ingest_from_directory` to handle the new folders.
3.  **Verification**: Run builder and check if data from all folders is ingested into `opinion-expert`.

