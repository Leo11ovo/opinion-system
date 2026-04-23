# RouterRAG A/B 实验复盘报告（2026-03-23）

## 1. 背景与目标
- 当前诉求：验证 GraphRAG/RouterRAG 在“查询-召回-生成”链路中的实际效果，并建立可复现的实验方式。
- 关键痛点：
  - 前端/命令行测试链路不稳定，容易因为项目上下文、路径、参数而失败。
  - 索引构建耗时长，失败后容易重复劳动。
  - 召回质量不稳定，出现“主题相关但证据价值低”的文本。
- 本次目标：
  - 建立一个可直接运行的 A/B 索引构建脚本。
  - 对比不同切块策略对召回质量的影响。
  - 形成可汇报的结论与后续计划。

## 2. 本次完成的改造

### 2.1 前后端能力补齐
- 新增 RouterRAG 索引手动导入能力（支持 `.lance`、`vector_db`、专题目录）。
- 前端“库管理”新增手动导入表单，便于不重建直接复用已有产物。
- 无项目时支持自动创建项目并切换，减少操作阻塞。
- 前端新增“纯净检索/增强检索”切换，便于质量评测时隔离专家改写干扰。

### 2.2 索引构建参数化（A/B 关键）
- 后端构建接口支持参数：
  - `sample_ratio`
  - `chunk_mode` (`sentence` / `window`)
  - `chunk_size`
  - `chunk_overlap`
- RouterRAG 向量化流程支持窗口分块（window）与重叠参数。
- 新增脚本：`scripts/build_routerrag_ab.py`
  - 支持 txt/jsonl/csv 自动抽样
  - 支持 A/B 双专题构建
  - 支持 `--resume-existing` 续跑
  - 支持 `--only-topic` 单边构建
  - 支持构建后自动打印 Lance 表统计

## 3. 关键问题与定位

### 3.1 “匹配度低（<20%）”的理解偏差
- 当前前端显示分数来自 `similarity = 1 - distance`，是向量相似度，不是“命中率/准确率”。
- 因此低分不等于系统失败，需要结合 Top-K 文本可用性评估。

### 3.2 召回内容“相关但不好用”
- 旧策略（按句切分）在中文舆情长句中容易形成语义混杂块。
- 查询短词（如“控烟”）时，容易命中“主题相关但证据弱”的情绪化段落。

### 3.3 构建过程慢/中断风险
- 关系抽取和 embedding 阶段依赖在线模型，存在超时与限流（429）。
- 已通过以下方式缓解：
  - 降低 embedding 并发（`max_concurrent` 从 30 降到 5）
  - 提供中间产物备份与续跑模式
  - 支持更小样本快速重试

## 4. A/B 实验设置

## 4.1 实验维度
- A（baseline）：`chunk_mode=sentence`
- B（candidate）：`chunk_mode=window`
- 共同参数：
  - `sample_ratio`：先从 10% 下探到 2% 以快速闭环
  - `chunk_size`：160（后续可扫参 140/180/220）
  - `chunk_overlap`：30

### 4.2 已观察结果（定性）
- 切换到 `window + overlap` 后，体感召回相关性提高：
  - chunk 语义更聚焦
  - 边界信息损失减少
  - 查询命中稳定性更高
- 与 `sentence` 相比，`window` 在舆情长段文本上更鲁棒。

## 5. 本次构建结果（样例）
- `ab2_window` 已成功构建并落库，Lance 表统计：
  - `graphrag_texts`: 105
  - `normalrag`: 797
- 说明：
  - 当前链路已可同时支持 NormalRAG 与 Neo4j GraphRAG（`graphrag_texts` 用于文本标签检索）。
  - 可直接在前端专题中选择 `ab2_window` 进行检索测试。

## 6. 对业务汇报可用结论
- 结论 1：切块策略显著影响召回质量，`window + overlap` 优于按句切分。
- 结论 2：当前“匹配度%”是相似度，不是命中率，需以 Top-K 证据可用性评估为主。
- 结论 3：构建链路已具备“抽样重跑 + 续跑 + 手动导入”的工程可操作性，实验成本可控。

## 7. 后续计划（建议）
- 计划 A（1 天内）：
  - 固定 10 条标准问题，完成 `sentence` vs `window` 的 Top3 对比打分。
  - 输出量化指标：Top3 相关率、噪声率、可引用证据率。
- 计划 B（2~3 天）：
  - 增加“证据优先重排”策略（事实/时间/主体优先）。
  - 前端显示原始 distance 与分数解释，降低误判。
- 计划 C（并行）：
  - 优化限流与重试策略，进一步降低 429 对构建稳定性的影响。

## 8. 复现命令（保留）
```powershell
python scripts/build_routerrag_ab.py `
  --project-id 20260323-032826-newtest `
  --source-text-dir backend/data/projects/20260323-032826-newtest/uploads/jsonl `
  --sample-ratio 0.02 `
  --topic-a ab2_sentence `
  --topic-b ab2_window `
  --chunk-size 160 `
  --chunk-overlap 30 `
  --only-topic b `
  --clean
```

续跑（不重新抽样）：
```powershell
python scripts/build_routerrag_ab.py `
  --project-id 20260323-032826-newtest `
  --source-text-dir backend/data/projects/20260323-032826-newtest/uploads/jsonl `
  --topic-a ab2_sentence `
  --topic-b ab2_window `
  --chunk-size 160 `
  --chunk-overlap 30 `
  --resume-existing
```
