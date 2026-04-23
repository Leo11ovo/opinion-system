# Tasks

- [ ] Task 1: 升级 Parser 逻辑 (Entity & Step Extraction)
    - [ ] SubTask 1.1: 重构 `PromptParser` 以提取 `Method` 和 `Indicator` 节点，建立 `HAS_INDICATOR` 关系。
    - [ ] SubTask 1.2: 重构 `CaseParser` 以提取 `CaseStudy`, `Stakeholder`, `Event`, `Risk` 等核心实体。
    - [ ] SubTask 1.3: 更新 `MethodologyParser` 提取理论和指南实体。
    - [ ] SubTask 1.4: 确保每个 Parser 返回 `(nodes, relationships)` 列表，包含实体节点和 Chunk 节点。

- [ ] Task 2: 更新 Builder 适配新 Schema
    - [ ] SubTask 2.1: 更新 `VALID_LABELS` 为包含 `Theory`, `Method`, `Indicator`, `Stakeholder`, `EventType`, `Tool`, `Guideline`, `CaseStudy` 以及 `ExpertChunk`。
    - [ ] SubTask 2.2: 更新 `VALID_RELATIONSHIPS` 为包含 `GUIDES`, `APPLIES_TO`, `MEASURES`, `INFLUENCES`, `HAS_INDICATOR`, `REFERENCES`, `WARNING`, `HAS_CHUNK`, `NEXT_CHUNK`。
    - [ ] SubTask 2.3: 修改 `ingest_nodes` 逻辑，确保实体节点（Entity）基于 `name + description` 生成向量，Chunk 节点基于 `content` 生成向量。

- [ ] Task 3: 向量索引策略调整
    - [ ] SubTask 3.1: 确认是否需要单独的索引，或统一使用 `expert_embedding_index`。
    - [ ] SubTask 3.2: 更新索引创建逻辑，确保所有带 `embedding` 的节点都能被检索。

- [ ] Task 4: 检索与评估优化
    - [ ] SubTask 4.1: 修改 `ExpertRetriever`，支持基于实体的语义检索，并能通过关系链召回相关背景（Chunk）。
    - [ ] SubTask 4.2: 更新 `Evaluator` 以统计各种 Label 节点的覆盖率和关系密度。

- [ ] Task 5: 全量重建与验证
    - [ ] SubTask 5.1: 运行 `python -m src.expert_kg.pipeline --rebuild`。
    - [ ] SubTask 5.2: 验证图谱中的路径，如 `(Method)-[:HAS_INDICATOR]->(Indicator)` 是否真实存在。

# Task Dependencies
- [Task 1] depends on Schema definition in spec.md
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 2]
- [Task 4] depends on [Task 3]
- [Task 5] depends on [Task 4]
