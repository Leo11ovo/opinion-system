# RouterRAG 最小闭环改造复盘说明 v1

**时间**: 2026-03-20  
**目标**: 在不大改架构的前提下，让 RouterRAG 具备“可实验、可反馈、可评测、可复盘”的最小闭环。

---

## 1. 本次改造解决了什么

本次改造重点不是重构 GraphRAG，而是给现有 RouterRAG 增加一条可执行的迭代路径：

1. 检索请求可带实验信息（`experiment_tag`）与问题类型（`question_type`）。
2. 系统可按问题类型自动套用参数预设（可关闭）。
3. 检索结果可带追踪信息（`trace_id`），用于后续反馈对齐。
4. 增加反馈提交/查询接口，反馈先落本地 JSONL。
5. 评测支持实验标签与 A/B 对比输出。
6. 增加一键 mini 评测脚本，便于周迭代复跑。

---

## 2. 改造范围（代码文件）

### 2.1 检索链路
- `backend/src/utils/rag/ragrouter/router_retrieve_data.py`

新增内容：
- 问题类型预设表 `QUESTION_TYPE_PRESETS`
- 问题类型自动识别 `detect_question_type(query)`
- `router_retrieve(...)` 新参数：
  - `question_type`
  - `experiment_tag`
  - `trace_id`
  - `use_question_preset`
- `retrieve_documents(...)` 同步支持以上参数并透传
- 返回结果新增调试与复盘字段：
  - `trace_id`
  - `experiment_tag`
  - `question_type`
  - `preset_applied`
  - `preset_config`

### 2.2 API 层
- `backend/server.py`

更新内容：
- `POST /api/rag/routerrag/retrieve` 支持新参数透传：
  - `question_type`
  - `experiment_tag`
  - `trace_id`
  - `use_question_preset`
- 新增反馈接口：
  - `POST /api/rag/routerrag/feedback`
  - `GET /api/rag/routerrag/feedback`
- `POST /api/rag/evaluate` 支持：
  - 单实验：`experiment_tag`
  - A/B 对比：`compare_tag`

### 2.3 反馈存储
- `backend/src/rag/feedback/store.py`
- `backend/src/rag/feedback/__init__.py`

能力：
- `append_feedback(topic, record)`：追加写入 JSONL
- `list_feedback(topic, limit, experiment_tag)`：按条件读取

默认落盘目录：
- `backend/data/rag_feedback/{topic}.jsonl`

### 2.4 评测模块
- `backend/src/rag/evaluator/core.py`
- `backend/src/rag/evaluator/__init__.py`
- `backend/src/rag/evaluator/run_mini_eval.py`

更新内容：
- `EvaluationDataItem` 支持 `question_type`
- `run_evaluation(...)` 支持 `experiment_tag`
- 新增 `run_evaluation_compare(...)` 输出 baseline/candidate 与 delta
- 新增脚本 `run_mini_eval.py`（单实验与 A/B 都可跑）

---

## 3. 参数与行为说明

## 3.1 新增请求参数（RouterRAG 检索）

可选参数：
- `question_type`: `fact/explain/compare/decision/explore`
- `experiment_tag`: 实验版本标签（如 `baseline`、`candidate_v2`）
- `trace_id`: 外部传入追踪 ID（不传则系统生成）
- `use_question_preset`: 是否应用问题类型预设（默认 `true`）

## 3.2 问题类型预设逻辑

执行顺序：
1. 若请求传了 `question_type`，优先使用。
2. 否则用 `detect_question_type` 自动识别。
3. 若 `use_question_preset=true`，应用对应预设参数（mode/topk/expert 开关/summary mode）。
4. 若 `use_question_preset=false`，走请求参数原值。

---

## 4. 反馈数据结构（最小版）

提交接口 `POST /api/rag/routerrag/feedback` 支持以下字段：

- `topic`（必填）
- `trace_id`
- `experiment_tag`
- `question`
- `question_type`
- `scores`（对象，建议 1-5 分）
- `bad_reason`（如：漏召回/不相关/建议空泛）
- `note`
- `operator`

系统会自动补：
- `created_at`（UTC 时间）

---

## 5. 评测使用方式

## 5.1 评测数据样例（JSON）

```json
{
  "name": "mini-eval",
  "version": "v1",
  "items": [
    {
      "question": "某事件为什么会从萌芽期快速进入爆发期？",
      "question_type": "explain",
      "answer_gold": "..."
    }
  ]
}
```

## 5.2 一键运行（单实验）

```bash
python -m src.rag.evaluator.run_mini_eval --topic 控烟 --eval-data path/to/eval-mini.json --mode mixed --tag baseline
```

## 5.3 一键运行（A/B 对比）

```bash
python -m src.rag.evaluator.run_mini_eval --topic 控烟 --eval-data path/to/eval-mini.json --mode mixed --tag baseline --compare-tag candidate_v2
```

输出目录默认：
- `backend/reports/rag_eval/*.json`

---

## 6. 推荐复盘模板（每周）

每周复盘建议只回答四个问题：

1. 哪类问题（fact/explain/compare/decision/explore）表现最差？
2. 差在召回还是生成？
3. 哪个 `experiment_tag` 相比 baseline 有净提升？
4. 下周只改哪 1-2 个参数？

建议固定看三项指标：
- `precision_avg`
- `recall_avg`
- `judge_correct_ratio`

---

## 7. 当前边界与注意事项

1. 反馈先存本地 JSONL，暂未做数据库化与并发锁增强。
2. 问题类型自动识别是规则法，优先追求稳定可跑，不是最优准确率。
3. 预设参数是“默认策略”，不是强制最优；可通过 `use_question_preset=false` 关闭。
4. 当前 A/B 对比是离线重复跑评测集，不是在线流量实验。

---

## 8. 下一步（保持轻量）

建议按优先级逐步增强：

1. 把反馈 JSONL 周期归档（按周切分文件）。
2. 给 `bad_reason` 做固定枚举统计面板。
3. 在评测报告里增加“按 question_type 分组均值”。
4. 每周只允许变更一组 preset，降低试验噪音。

---

## 9. 一句话总结

这版改造已经让 RouterRAG 从“只能跑检索”升级为“能标记实验、收集反馈、做 A/B 评测并形成周复盘”的可迭代系统，复杂度可控，适合当前阶段持续快跑。
