# `sync_to_neo4j.py` 主入口说明

这份文档说明当前 [sync_to_neo4j.py](/f:/opinion-system/opinion-system/backend/src/graph/sync_to_neo4j.py) 的真实职责、处理分支和后续触发链路。

核心结论：

- `sync_to_neo4j.py` 现在是图谱统一入图入口。
- 主入口函数是 `sync_after_upload(...)`。
- 它不再只是“从 MySQL 同步到 Neo4j”。
- 它同时兼容历史上传链路和当前本地文件/文档入图链路。

## 1. 这个入口现在负责什么

`sync_after_upload(...)` 负责把一批输入数据统一整理为 Neo4j 中可检索的图结构，并在需要时继续触发：

- 证据层入图：`Post`、`Account`、`Platform`
- 证据层关系：`POSTED`、`IN_PLATFORM`
- 文本切块：`Chunk` 与 `HAS_CHUNK`
- 实体/观点抽取：`Entity`、`Claim` 与 `MENTIONS`、`HAS_CLAIM`
- 报告层构建：`Report`、`Section`、`Finding`、`Recommendation`、`Metric`
- 图节点向量回填：给 `Entity`、`Claim`、`Event`、`Topic`、`Finding` 写 `embedding` 并确保 Neo4j 向量索引存在

它返回一个统一结果对象，里面包含：

- 本次写入的 `Post/Chunk/Mentions` 统计
- 当前图能力判断 `graph_capability`
- 报告层构建结果 `report_layer`
- 向量回填结果 `vector_backfill`

## 2. 它接受哪些输入

`sync_after_upload(...)` 当前有两种主要输入模式。

### 2.1 历史上传链路

默认使用：

- `source_bucket="filter"`
- `topic`
- `date`
- `dataset_name` 可选

这时它会去 `bucket(source_bucket, topic, date)` 下找产物文件。

当前会识别：

- `*.jsonl`
- `*.csv`

注意：

- 这条路径下的 `jsonl` 处理逻辑仍然依赖数据库连接。
- 代码不是直接解析 `jsonl` 文件内容，而是拿 `jsonl` 文件名当表名，再去数据库里执行 `SELECT * FROM \`table_name\``。
- 所以这部分仍然是“历史上传链路兼容层”。

### 2.2 自定义本地路径

当：

- `source_bucket="custom"`
- `dataset_name` 传入文件路径或目录路径

它会直接处理本地内容。

支持：

- `jsonl`
- `csv`
- `pdf`
- `docx`
- `txt`
- `md`

具体行为：

- 如果 `dataset_name` 是单个文件，只处理该文件
- 如果 `dataset_name` 是目录，会递归扫描目录下所有支持类型

这里最重要的是：

- `csv` 可以直接读取
- `pdf/docx/txt/md` 可以直接读取并转成 `Post`
- `jsonl` 目前在实现上仍偏向旧表同步思路，不是完整的本地 JSONL 直读解析器

## 3. 入图前会先做什么

### 3.1 检查 Neo4j 配置

如果 Neo4j 没配置，直接返回：

- `status = skipped`

不会继续执行。

### 3.2 尝试准备数据库连接

代码会调用：

- `db_manager.get_engine_for_database(target_database)`

这里的行为是：

- 如果数据库可连接，后续可以支持历史表同步
- 如果数据库不可连接：
  - 且本次包含 `jsonl`，直接报错返回
  - 否则记录 warning，继续尝试本地文件入图

这也是为什么它现在是“统一入图入口”，而不是“数据库必须在线”。

### 3.3 初始化 Neo4j Schema

如果 `init_schema_if_missing=True`，会调用：

- [schema.py](/f:/opinion-system/opinion-system/backend/src/graph/schema.py) 中的 `init_schema()`

当前会创建或确保存在：

- 唯一约束：`Post`、`Platform`、`Account`、`Entity`、`Chunk`、`Topic`、`Claim`、`Event`、`Report`、`Section`、`Finding`、`Recommendation`、`Metric`
- 查询索引：围绕 `topic`、`channel`、`published_at`、`chunk_index`、`report_id` 等字段
- 默认平台节点

## 4. 各类输入会怎样被转成 Post

主循环会把待处理内容统一转成一个 `DataFrame`，然后逐行写成 `Post`。

### 4.1 `jsonl`

当前逻辑：

- 取文件名 `file_path.stem` 作为表名
- 用数据库连接执行 `SELECT * FROM table_name`
- 查询结果读成 `DataFrame`

这说明：

- 这里的 `jsonl` 更像“上传链路留下的表名线索”
- 不是“直接 parse jsonl 文件”

### 4.2 `csv`

当前逻辑：

- 直接 `pd.read_csv(file_path)`
- 如果没有 `id` 但有 `post_id`，会把 `post_id` 补成 `id`

### 4.3 `pdf/docx/txt/md`

当前逻辑：

- 先读取文件正文
- 再人为包装成一行 `DataFrame`

包装后的字段大致是：

- `id`: 基于文件绝对路径哈希生成的 `report_xxx`
- `author`: `report_source`
- `title`: 文件名
- `contents`: 文档正文
- `platform`: `report`
- `published_at`: 文件修改时间
- `url`: 文件绝对路径
- `classification`: `报告`

也就是说：

- 文档文件会先被当成一种特殊 `Post`
- 后面证据层和报告层都可以继续消费它

## 5. 证据层怎么写入 Neo4j

对每一行标准化后的数据，`sync_after_upload(...)` 都会写三类节点和两类关系。

### 5.1 Platform

```cypher
MERGE (p:Platform {name: $name})
```

### 5.2 Account

`Account.id` 规则：

- `topic + "_" + author`
- 作者为空时用 `__unknown__`

### 5.3 Post

`Post.id` 规则：

- `topic + "_" + channel + "_" + row_id`

这样是为了避免：

- 多专题冲突
- 多渠道表主键重复

写入字段包括：

- `topic`
- `channel`
- `title`
- `contents`
- `platform`
- `author`
- `published_at`
- `url`
- `region`
- `hit_words`
- `polarity`
- `classification`

### 5.4 关系

会建立：

- `(Account)-[:POSTED]->(Post)`
- `(Post)-[:IN_PLATFORM]->(Platform)`

这些写入都使用 `MERGE`，因此是幂等的。

## 6. 后续触发链路怎么跑

证据层写完 `Post` 后，会根据配置继续向后触发。

### 6.1 Chunk 切块

触发条件：

- `enable_chunk_embedding=True`
- 或配置中开启 `enable_chunk_embedding`
- 或开启实体抽取时被强制开启

调用位置：

- [chunk_embedding.py](/f:/opinion-system/opinion-system/backend/src/graph/chunk_embedding.py)

实际做的事：

- 把 `Post.contents` 按字符切块
- 创建 `Chunk`
- 建立 `(Post)-[:HAS_CHUNK]->(Chunk)`

注意：

- 虽然文件名叫 `chunk_embedding.py`
- 但它这里不负责向量写入
- 它现在只负责切块和图结构写入

### 6.2 Entity / Claim 抽取

触发条件：

- `enable_entity_extraction=True`
- 或配置中开启 `enable_entity_extraction`

调用位置：

- [entity_extraction.py](/f:/opinion-system/opinion-system/backend/src/graph/entity_extraction.py)

当前有两种模式。

#### 轻量模式

当：

- `enable_entity_extraction=True`
- `enable_llm_extraction=False`

会走 `extract_entities_naive()`。

当前这个函数实际上是占位实现：

- 直接返回空列表

所以当前轻量模式的真实效果是：

- 可能加载 chunk
- 但不会真正抽出有效实体
- 也不会形成完整语义层

#### LLM 模式

当：

- `enable_entity_extraction=True`
- `enable_llm_extraction=True`

会对每个 chunk 调用 LLM，抽取：

- `entities`
- `claims`

然后写入：

- `Entity`
- `Claim`
- `(Chunk)-[:MENTIONS]->(Entity)`
- `(Post)-[:MENTIONS]->(Entity)`
- `(Chunk)-[:HAS_CLAIM]->(Claim)`
- `(Post)-[:HAS_CLAIM]->(Claim)`

这里 `Post` 级关系是聚合兼容层，方便上层检索和查询。

### 6.3 报告层构建

触发条件：

- 本次输入里检测到 `pdf/docx/txt/md`

调用位置：

- [report_layer.py](/f:/opinion-system/opinion-system/backend/src/graph/report_layer.py)

触发方式：

- `sync_after_upload(...)` 会先收集文档文件列表
- 结束证据层写入后，调用 `ingest_report_directory_to_report_layer(...)`

报告层会补建：

- `Report`
- `Section`
- `Finding`
- `Recommendation`
- `Metric`
- 报告侧写入的 `Topic`
- 报告侧写入的 `Event`

并桥接到证据层：

- `SUPPORTED_BY_POST`
- `SUPPORTED_BY_CHUNK`
- `DERIVED_FROM`
- 以及 `ABOUT_TOPIC`、`SUPPORTED_BY_EVENT` 等关系

这意味着：

- 文档既会成为证据层里的 `Post`
- 也会进一步生成面向 GraphRAG 的 `Finding` 中心结果层

### 6.4 图节点向量回填

最后会调用：

- [backfill_graph_node_embeddings.py](/f:/opinion-system/opinion-system/backend/src/graph/backfill_graph_node_embeddings.py)

当前默认处理标签：

- `Entity`
- `Claim`
- `Event`
- `Topic`
- `Finding`

它会：

- 读取这些节点上的文本字段
- 调 embedding API
- 把结果写回 Neo4j 节点的 `embedding`
- 确保每类节点的 Neo4j 向量索引存在

注意：

- `Chunk` 向量不在这里写
- 这个 backfill 是图节点向量，不是 LanceDB 文本块向量

## 7. Graph 能力状态是怎么判断的

入图结束后，会统计这些标签数量：

- `Post`
- `Chunk`
- `Entity`
- `Claim`
- `Topic`
- `Event`
- `Finding`

然后产出 `graph_capability`。

判断逻辑大致是：

- 有 `Entity/Claim/Finding` 这些语义节点：`full_graphrag`
- 只有 `Post/Chunk/Topic/Event` 这些结构节点：`structural_only`
- 什么都没形成：`empty`

这也是前端测试台里“弱化模式 / 完整模式”的来源。

## 8. 这条入口的真实边界

现在最容易混淆的点有三个。

### 8.1 它是统一入口，但不是所有格式都同等成熟

成熟度从高到低大致是：

- 文档类：`pdf/docx/txt/md`
- `csv`
- 历史上传链路下的表同步
- `jsonl` 直读

尤其要注意：

- 当前 `jsonl` 不是严格意义上的“本地 JSONL 直接解析入图”

### 8.2 “chunk_embedding” 不等于图向量

`chunk_embedding.py` 现在只做：

- 切块
- 建 `Chunk`
- 建 `HAS_CHUNK`

不做：

- Neo4j 节点向量写入

真正的图节点向量写入在：

- `backfill_graph_node_embeddings.py`

### 8.3 报告文档不是只进报告层

文档入图不是“直接只写 `Report`”。

实际是两段：

1. 先包装成 `Post`，进入证据层
2. 再额外构建报告层 `Report/Section/Finding/...`

这也是当前 GraphRAG 能够同时保留：

- 原始文档证据
- 抽象出的报告 Finding

## 9. 一句话总结

`sync_to_neo4j.py::sync_after_upload(...)` 当前做的不是单一“数据库同步”，而是：

“把历史上传数据、本地结构化文件和报告文档统一转成 Neo4j 里的证据层与报告层，并按配置继续触发 chunk、entity/claim、report layer 和图节点向量回填。”
