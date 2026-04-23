# 舆情 GraphRAG 问题类型到检索路径映射表 v1

**编制时间**: 2026-03-20  
**适用范围**: opinion-system 双图谱 GraphRAG / RouterRAG 检索设计  
**目标**: 将“不同问题类型触发不同检索路径”的思路整理为可实现、可配置、可扩展的正式方案

---

## 一、文档目标

本文件用于回答一个核心问题：

**当用户提出不同类型的问题时，系统应该优先检索哪些节点，沿哪些关系扩展，何时跳转专家图，最终按什么结构输出结果。**

本文件是以下文档的配套落地稿：

- `舆情分析GraphRAG_节点归属与双图谱设计说明_v1.md`
- `舆情GraphRAG_skill调用链说明_v1.md`

---

## 二、统一检索原则

无论问题属于哪一类，系统都遵循同一条总链路：

1. 识别问题类型
2. 证据图首轮召回
3. 证据图内关系扩展
4. 命中桥接节点
5. 跳转专家图补充解释或策略
6. 融合排序
7. 按问题类型组织输出

这意味着：

- 不同问题类型不是使用完全不同的系统
- 而是在同一入口下，切换不同的检索模板

---

## 三、统一检索模板字段

为了便于实现，建议每一种问题类型都固定以下 6 个字段：

1. **首轮召回节点**
   第一批优先命中的节点类型。

2. **证据图扩展关系**
   在证据图内部优先允许展开的关系。

3. **桥接节点**
   从证据图跳到专家图时，优先使用的中间节点。

4. **专家图目标节点**
   专家增强阶段优先检索的节点类型。

5. **输出结构**
   最终回答的组织方式。

6. **策略倾向**
   对 RouterRAG 参数配置的高层要求。

---

## 四、问题类型总表

| 问题类型 | 目标 | 检索主轴 | 专家增强强度 |
| --- | --- | --- | --- |
| `fact` | 回答“是什么” | 证据图直取 | 低 |
| `explain` | 回答“为什么” | 证据图先行，专家图解释 | 高 |
| `compare` | 回答“像不像、差在哪” | 当前案例画像 + 相似案例召回 | 中高 |
| `decision` | 回答“怎么办” | 现状判断 + 策略桥接 | 很高 |
| `explore` | 回答“先摸全貌” | 多维平衡召回 | 中 |

---

## 五、`fact` 事实型问题检索路径

### 5.1 适用问题

- 发生了什么
- 哪个平台最活跃
- 谁是主要参与主体
- 当前有哪些关键帖子
- 指标数值是多少

### 5.2 检索目标

快速给出事实、对象、数值和证据来源，避免理论解释过度介入。

### 5.3 首轮召回节点

- `Case`
- `Event`
- `Platform`
- `Actor`
- `Post`
- `Finding`
- `IndicatorValue`
- `TimelineNode`

### 5.4 证据图扩展关系

- `(Case)-[:HAS_EVENT]->(Event)`
- `(Case)-[:HAS_ACTOR]->(Actor)`
- `(Case)-[:USES_PLATFORM]->(Platform)`
- `(Case)-[:HAS_TIMELINE]->(TimelineNode)`
- `(Event)-[:HAS_POST]->(Post)`
- `(Finding)-[:MEASURED_BY]->(IndicatorValue)`
- `(IndicatorValue)-[:DERIVED_FROM]->(Platform)`
- `(Evidence)-[:DERIVES_FROM]->(Post)`

### 5.5 桥接节点

- `Finding`

仅当用户需要指标定义或概念释义时，才建议桥接到专家图。

### 5.6 专家图目标节点

- `IndicatorDefinition`

### 5.7 推荐检索路径

#### 路径 A: 平台分布类

`Case -> Platform -> IndicatorValue -> Finding`

#### 路径 B: 主体识别类

`Case -> Actor -> TimelineNode / Event -> Post`

#### 路径 C: 事件还原类

`Case -> TimelineNode -> Event -> Post -> Evidence`

### 5.8 输出结构

1. 事实结论
2. 关键对象或关键数值
3. 对应证据来源
4. 必要时补充概念定义

### 5.9 策略倾向

- 偏 `normalrag`
- 专家增强默认关闭或弱化
- `llm_summary_mode = strict`

---

## 六、`explain` 解释型问题检索路径

### 6.1 适用问题

- 为什么会发酵
- 为什么判断为负面升级
- 为什么这个平台成为主战场
- 背后的传播机制是什么

### 6.2 检索目标

先找现象证据，再找解释框架，最终形成“证据支撑的解释”。

### 6.3 首轮召回节点

- `Finding`
- `Evidence`
- `Claim`
- `TimelineNode`
- `Response`
- `IndicatorValue`

### 6.4 证据图扩展关系

- `(Finding)-[:SUPPORTED_BY]->(Evidence)`
- `(Claim)-[:SUPPORTED_BY]->(Evidence)`
- `(Evidence)-[:DERIVES_FROM]->(Post)`
- `(TimelineNode)-[:LEADS_TO]->(TimelineNode)`
- `(Actor)-[:RESPONDS_WITH]->(Response)`
- `(Finding)-[:MEASURED_BY]->(IndicatorValue)`

### 6.5 桥接节点

- `Finding`
- `Case`

### 6.6 专家图目标节点

- `Theory`
- `IssueFrame`
- `Dimension`
- `IndicatorDefinition`
- `Method`

### 6.7 桥接关系

- `(Finding)-[:EXPLAINED_BY]->(Theory)`
- `(Case)-[:USES_FRAME]->(IssueFrame)`
- `(Finding)-[:MEASURES]->(IndicatorDefinition)`

### 6.8 专家图扩展关系

- `(IssueFrame)-[:RELATES_TO]->(Theory)`
- `(Theory)-[:APPLIES_TO]->(Dimension)`
- `(Dimension)-[:HAS_INDICATOR]->(IndicatorDefinition)`
- `(Method)-[:USES]->(IndicatorDefinition)`
- `(Method)-[:FOCUSES_ON]->(Dimension)`

### 6.9 推荐检索路径

#### 路径 A: 发酵原因类

`Finding -> Evidence -> Post -> TimelineNode -> Theory -> IssueFrame`

#### 路径 B: 判断依据类

`Finding -> IndicatorValue -> Evidence -> Theory -> Dimension -> IndicatorDefinition`

### 6.10 输出结构

1. 现象结论
2. 关键证据链
3. 理论解释
4. 判断结论

### 6.11 策略倾向

- 使用 `mixed`
- 强启专家增强
- `llm_summary_mode = supplement`

---

## 七、`compare` 对比型问题检索路径

### 7.1 适用问题

- 和过去哪个事件相似
- 和某案例相比有什么不同
- 是否属于同一类舆情模式

### 7.2 检索目标

先生成当前案例画像，再召回相似案例，最后给出相似点与差异点。

### 7.3 首轮召回节点

- `Case`
- `Finding`
- `IssueFrame`
- `TimelineNode`
- `Platform`
- `Actor`
- `Response`
- `IndicatorValue`

### 7.4 当前案例画像维度

建议至少抽取以下 6 维：

- 议题框架
- 主体类型
- 平台分布
- 时间线阶段
- 指标特征
- 回应动作

### 7.5 证据图扩展关系

- `(Case)-[:HAS_ACTOR]->(Actor)`
- `(Case)-[:USES_PLATFORM]->(Platform)`
- `(Case)-[:HAS_TIMELINE]->(TimelineNode)`
- `(Finding)-[:MEASURED_BY]->(IndicatorValue)`
- `(Actor)-[:RESPONDS_WITH]->(Response)`

### 7.6 桥接节点

- `Case`
- `Finding`
- `Response`

### 7.7 专家图目标节点

- `IssueFrame`
- `Theory`
- `Strategy`
- `IndicatorDefinition`

### 7.8 桥接关系

- `(Case)-[:USES_FRAME]->(IssueFrame)`
- `(Case)-[:EXEMPLIFIES]->(Theory)`
- `(Response)-[:INSTANCE_OF]->(Strategy)`
- `(Finding)-[:MEASURES]->(IndicatorDefinition)`

### 7.9 推荐检索路径

#### 路径 A: 案例相似类

`当前 Case -> IssueFrame / Theory -> 相似 Case`

#### 路径 B: 指标特征对比类

`当前 Case -> Finding -> IndicatorValue / IndicatorDefinition -> 相似 Case`

#### 路径 C: 回应动作对比类

`当前 Case -> Response -> Strategy -> 相似 Case`

### 7.10 输出结构

1. 最相似案例
2. 相似点
3. 差异点
4. 差异带来的判断

### 7.11 策略倾向

- 使用 `mixed`
- 扩大召回范围
- 强化案例级排序

---

## 八、`decision` 决策型问题检索路径

### 8.1 适用问题

- 现在应该怎么回应
- 哪种策略更合适
- 后续怎么避免进一步升级
- 当前最优处置方式是什么

### 8.2 检索目标

先判断当前局面，再从专家图中找到策略类型和适用条件，形成可解释的建议。

### 8.3 首轮召回节点

- `Case`
- `Finding`
- `Response`
- `TimelineNode`
- `Actor`
- `IndicatorValue`

### 8.4 证据图扩展关系

- `(Case)-[:HAS_TIMELINE]->(TimelineNode)`
- `(Actor)-[:RESPONDS_WITH]->(Response)`
- `(Finding)-[:MEASURED_BY]->(IndicatorValue)`
- `(Finding)-[:SUPPORTED_BY]->(Evidence)`
- `(TimelineNode)-[:INVOLVES]->(Actor)`

### 8.5 桥接节点

- `Response`
- `Finding`
- `Case`

### 8.6 专家图目标节点

- `Strategy`
- `Theory`
- `IssueFrame`
- `Method`

### 8.7 桥接关系

- `(Response)-[:INSTANCE_OF]->(Strategy)`
- `(Response)-[:EVALUATED_BY]->(Theory)`
- `(Case)-[:USES_FRAME]->(IssueFrame)`
- `(Theory)-[:GUIDES]->(Strategy)`
- `(Strategy)-[:ADDRESSES]->(IssueFrame)`

### 8.8 推荐检索路径

#### 路径 A: 现实回应评估类

`Case -> Response -> Strategy -> Theory`

#### 路径 B: 当前处境到策略类

`Case -> Finding / TimelineNode -> Theory -> Strategy`

#### 路径 C: 议题框架到治理策略类

`Case -> IssueFrame -> Strategy`

### 8.9 输出结构

1. 当前局面判断
2. 关键证据
3. 可选策略及适用条件
4. 推荐策略与原因

### 8.10 策略倾向

- 使用 `mixed`
- 最高强度专家增强
- 强化桥接关系命中

---

## 九、`explore` 探索型问题检索路径

### 9.1 适用问题

- 这个事件整体怎么看
- 先帮我摸一下这个议题
- 有哪些值得关注的方向
- 先做一个整体研判

### 9.2 检索目标

构建事件全貌，不急于只回答某一个点，而是给出多维观察框架。

### 9.3 首轮召回节点

- `Case`
- `Finding`
- `TimelineNode`
- `Actor`
- `Platform`
- `IssueFrame`
- `Theory`
- `Response`

### 9.4 证据图扩展关系

- `(Case)-[:HAS_TIMELINE]->(TimelineNode)`
- `(Case)-[:HAS_ACTOR]->(Actor)`
- `(Case)-[:USES_PLATFORM]->(Platform)`
- `(Actor)-[:RESPONDS_WITH]->(Response)`
- `(Finding)-[:SUPPORTED_BY]->(Evidence)`

### 9.5 桥接节点

- `Case`
- `Finding`
- `Response`

### 9.6 专家图目标节点

- `IssueFrame`
- `Theory`
- `Dimension`
- `Strategy`

### 9.7 推荐检索路径

#### 路径 A: 全貌摸底类

`Case -> TimelineNode / Actor / Platform / Finding`

#### 路径 B: 初步解释类

`Case / Finding -> IssueFrame / Theory`

#### 路径 C: 后续关注点类

`Response -> Strategy`

### 9.8 输出结构

1. 事件概况
2. 关键主体与平台
3. 当前阶段与主要问题
4. 可能的解释框架
5. 建议继续关注的方向

### 9.9 策略倾向

- 使用 `mixed`
- 中等强度专家增强
- 以平衡检索为主

---

## 十、问题类型与桥接强度对照

| 问题类型 | 证据图权重 | 专家图权重 | 桥接强度 | 建议输出风格 |
| --- | --- | --- | --- | --- |
| `fact` | 很高 | 很低 | 低 | 简洁、事实优先 |
| `explain` | 高 | 高 | 高 | 证据加解释 |
| `compare` | 高 | 中高 | 中高 | 对照式 |
| `decision` | 中高 | 很高 | 很高 | 建议式 |
| `explore` | 高 | 中 | 中 | 全貌式 |

---

## 十一、建议的工程实现方式

为便于后端落地，建议把上述映射固化为配置表，而不是写死在多处逻辑里。

建议最少拆成以下几类配置：

1. **问题类型识别规则**
   负责把用户问题判成 `fact / explain / compare / decision / explore`

2. **首轮召回节点配置**
   负责定义每类问题优先命中的节点类型

3. **关系扩展白名单**
   负责定义每类问题允许优先扩展的关系

4. **桥接关系配置**
   负责定义从证据图进入专家图的高价值跳转

5. **答案模板配置**
   负责定义每类问题的输出结构

6. **RouterRAG 参数预设**
   负责把高层策略映射到 `mode`、`topk`、`expert overlay` 等参数

---

## 十二、下一步最值得做的工作

在这份映射表基础上，后续建议按以下顺序推进：

1. 先把 5 类问题的“首轮召回节点 + 关系白名单”配置化
2. 再把“桥接关系”配置化
3. 再把“答案结构模板”配置化
4. 最后再调整 RouterRAG 参数细节

原因是：

- 节点和关系路径决定能不能找对东西
- 参数只是放大或缩小这条路径的效果

因此，真正的第一优先级不是继续调 `topk`，而是先把检索路径 schema 固定下来。

---

## 十三、结论

这份映射表的核心价值在于把“问题分类”与“双图谱检索”正式对齐：

- `fact` 侧重证据直取
- `explain` 侧重证据到理论的桥接
- `compare` 侧重案例画像与相似案例召回
- `decision` 侧重现状判断到策略建议的桥接
- `explore` 侧重事件全貌与后续研判方向

这意味着下一阶段 GraphRAG 改造的重点已经明确：

**不是继续堆节点，而是把不同问题类型对应的检索路径正式固化。**
