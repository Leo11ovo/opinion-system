# Plan: Enhance Expert Knowledge Graph Construction

## Objective
This plan aims to refine the construction of the Expert Knowledge Graph (ExpertKG) by addressing two key user requirements:
1.  **PDF Parsing**: Implement robust PDF parsing capabilities to ingest high-value documents (reports, research papers) from `data/expert/`.
2.  **Expert KG Construction Pipeline**: Create a structured pipeline that orchestrates data ingestion, graph construction, and quality verification.
3.  **Quality Evaluation**: Implement metrics and tools to verify the quality of the constructed Expert KG.

## Phase 1: PDF Parsing Implementation

### 1.1 Choose Parsing Library
-   **Decision**: Use `PyMuPDF` (fitz) for general text extraction due to its speed and accuracy. Use `pdfplumber` as a fallback or for specific layout-heavy documents if needed.
-   **Action**: Add `pymupdf` and `pdfplumber` to project dependencies (if not present).

### 1.2 Implement `PDFParser` Class
-   **Location**: `src/expert_kg/parsers.py` (New file to keep `builder.py` clean).
-   **Functionality**:
    -   `parse(file_path: Path) -> str`: Extract full text.
    -   `extract_metadata(file_path: Path) -> Dict`: Extract title, author, creation date from PDF metadata.
    -   *Advanced*: Chunking logic is already in `src/rag/core/chunker.py`, we can reuse it or implement a simple paragraph-based splitter for expert documents.

### 1.3 Update `builder.py` to use `PDFParser`
-   Modify `ReportParser` and `ResearchPaperParser` to detect `.pdf` extension and delegate to `PDFParser`.

## Phase 2: Expert KG Construction Pipeline

### 2.1 Pipeline Orchestrator (`src/expert_kg/pipeline.py`)
-   **Goal**: A single script to run the entire process: `Ingest -> Construct -> Verify`.
-   **Steps**:
    1.  **Init**: Check database connection (`opinion-expert`).
    2.  **Ingest**: Iterate through `data/expert/` subfolders using appropriate parsers.
    3.  **Construct**: Create nodes and relationships in Neo4j.
    4.  **Index**: Create vector indices.
    5.  **Verify**: Run quality checks (Phase 3).

### 2.2 CLI Interface
-   Make the pipeline runnable via command line: `python -m src.expert_kg.pipeline --rebuild`.

## Phase 3: Quality Evaluation & Verification

### 3.1 Structural Metrics (`src/expert_kg/evaluator.py`)
-   **Node Count per Label**: Are we ingesting enough Theories/Methods?
-   **Relationship Density**: Are nodes well-connected? (Avg degree).
-   **Isolated Nodes**: Identify nodes with no relationships (orphans).

### 3.2 Semantic Verification (LLM-based)
-   **Sample Check**: Randomly select 5 nodes and use LLM to verify if the `description` matches the `source_pdf` content.
-   **Retrieval Test**: Run a set of "Golden Queries" (e.g., "What is Agenda Setting Theory?") and check if the correct node is retrieved in top-k.

### 3.3 Integration into Pipeline
-   The pipeline script should output a "Quality Report" at the end of the run.

## Implementation Roadmap

1.  **Install Dependencies**: `pip install pymupdf pdfplumber`.
2.  **Create Parsers**: Implement `src/expert_kg/parsers.py`.
3.  **Refactor Builder**: Move parsing logic out of `builder.py` to `parsers.py` and integrate PDF support.
4.  **Implement Evaluator**: Create `src/expert_kg/evaluator.py`.
5.  **Build Pipeline**: Create `src/expert_kg/pipeline.py` to stitch everything together.

