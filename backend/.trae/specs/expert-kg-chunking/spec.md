# Expert KG Structural Spec (V2)

## Why
原有的“Chunk Only”方案虽然解决了粒度问题，但缺乏结构化语义，导致图谱变成了线性链表，无法体现专家库的方法论、概念层级和逻辑关系。我们需要构建一个真正的“专家脑”，包含明确的实体（Theory, Method, etc.）和逻辑关系。

## What Changes
1.  **Schema 升级 (Entity-Centric)**:
    -   引入核心实体标签：`Theory`, `Method`, `Indicator`, `Stakeholder`, `EventType`, `Tool`, `Guideline`, `CaseStudy`。
    -   引入语义关系：`GUIDES`, `APPLIES_TO`, `MEASURES`, `INFLUENCES`, `HAS_INDICATOR`, `REFERENCES`, `WARNING`。
    -   保留 `Document` 和 `ExpertChunk` 作为知识载体，但它们将作为实体的上下文来源。

2.  **Parser 升级 (Extraction)**:
    -   `PromptParser`: 从 Markdown 中提取 `Method` (分析角度) 和 `Indicator` (具体指标)，并建立 `HAS_INDICATOR` 关系。
    -   `MethodologyParser`: 从文本中提取 `Theory` 和 `Guideline`。
    -   `CaseParser`: 提取 `CaseStudy`, `Stakeholder`, `Event`, `Risk` 以及它们之间的 `INVOLVED_IN`, `HAS_RISK` 等关系。
    -   `Report/PaperParser`: 除了 Chunking，还需提取元数据（Authors, Topics）并尝试链接到已有的 Method/Theory（未来可引入 LLM 提取）。

3.  **Builder 升级**:
    -   更新 `VALID_LABELS` 和 `VALID_RELATIONSHIPS` 以支持新 Schema。
    -   确保所有实体节点（Entity）和 Chunk 节点都包含 `embedding` 属性，以支持混合检索。

4.  **Retrieval 升级**:
    -   支持多跳检索：Query -> Vector Search (Entity/Chunk) -> Graph Traversal (e.g., Method -> Indicator) -> Context (Chunk)。

## Impact
-   **Affected Specs**: Expert KG Construction Pipeline.
-   **Affected Code**:
    -   `src/expert_kg/parsers.py`: 重写解析逻辑，专注于实体和关系的提取。
    -   `src/expert_kg/builder.py`: 适配新 Schema，更新索引策略（可能需要多个索引或统一索引）。
    -   `src/rag/retrievers/expert_retriever.py`: 优化 Cypher 查询以利用结构化信息。

## ADDED Requirements
### Requirement: Entity Extraction
系统必须从结构化文档（如 Markdown 列表、表格）中提取明确定义的实体（Method, Indicator, Stakeholder 等）。

### Requirement: Semantic Relationships
必须建立实体间的语义连接，例如 `(Method)-[:HAS_INDICATOR]->(Indicator)`，而不仅仅是 `HAS_CHUNK`。

### Requirement: Hybrid Embedding
-   **Entity Nodes**: Embedding 基于 `name + description`。
-   **Chunk Nodes**: Embedding 基于 `content`。
-   **检索**: 同时检索 Entity 和 Chunk，优先匹配 Entity（高置信度），Chunk 作为补充。

## MODIFIED Requirements
### Requirement: Schema Definition
废弃纯 Document-Chunk 模式，采用 Entity-Document-Chunk 混合模式。
所有节点必须包含：`id`, `name`, `description`, `source_pdf`, `embedding`, `confidence`。
