# opinion-report 重建记录（2026-04-01）

## 目标

- 清空 `opinion-report`
- 从 `backend/data/report_data` 重新导入证据层
- 在证据层之上重建报告层
- 保留“证据层 + 报告层”两层结构

## 本次策略

- 证据层：
  - `Post`
  - `Chunk`
  - `Entity`
  - `Claim`
- 报告层：
  - `Report`
  - `Section`
  - `Finding`
  - `Recommendation`
  - `Metric`
  - `Topic`
  - `Event`

## 导入原则

- 先清空整库，再重新导入
- 报告层不再使用“每份报告一个最小壳子”
- 尽量按整篇报告的章节结构拆分
- 事件不再默认生成“代表事件”占位节点
- 平台优先从正文/标题识别，不再统一挂到“报告”平台
- Recommendation 只响应少量核心 Finding，减少噪声关系

## 注意

- 本次重建不触碰 `opinion-expert` 的业务模型；另行清空后保持为空
- 本记录用于追踪本次重建参数与结构策略
