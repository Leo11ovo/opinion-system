# Neo4j 图模块

与 3.1.1 图结构一致，并已统一为双层构图：

- 证据层：`Post`、`Chunk`、`Entity`、`Claim`
- 报告层：`Report`、`Section`、`Finding`、`Recommendation`、`Metric`、`Topic`、`Event`

## 配置

- `configs/neo4j.yaml`：uri、user；密码建议用环境变量 `NEO4J_PASSWORD`。
- 可选：`enable_entity_extraction`、`enable_chunk_embedding`、`sync_batch_size`。

## 触发

- 在 DataPipeline 中 Upload 成功后自动调用 `sync_after_upload(topic, date)`。
- `sync_after_upload(...)` 现在是统一入口：先写证据层，再自动识别报告类文件补建报告层，最后统一回填图节点向量。
- 未配置 Neo4j 或同步失败时仅打日志，不中断流水线。

## 依赖

- `pip install neo4j`（已加入 requirements.txt）。
