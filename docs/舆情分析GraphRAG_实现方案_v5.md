# 舆情分析 GraphRAG 实现方案 v5.1（增强版）

**编制时间**: 2026-03-19
**基于**: opinion-system-fluid-master 现有架构
**目标**: 强化知识支持能力 + RLHF 反馈优化
**版本说明**: 整合舆情分析方法论、案例库结构、舆情规律

---

## 零、舆情分析方法论基础

### 0.1 核心分析框架

#### 时间维度（事件脉络）
- **潜伏期** → **萌芽期** → **爆发期** → **衰退期**
- 或：蛰伏期 → 酝酿期 → 形成期 → 消退期

#### 核心分析维度（5C框架）
| 维度 | 英文 | 内涵 | 数据指标 |
|------|------|------|----------|
| 量 | Count | 声量、增速、峰值、平台分布 | 帖子数、互动量、搜索指数 |
| 质 | Quality | 情感极性、话题焦点、信息真实性 | 正/负/中性占比、话题聚类 |
| 人 | Actor | 关键意见领袖、关键节点、受众画像 | KOL影响力、传播路径中心性 |
| 场 | Arena | 主要平台、话语场风格 | 平台热度分布、情绪色彩 |
| 效 | Effect | 实际影响（搜索量/销量/投诉量） | 行为转化、舆论干预效果 |

#### 舆情规律理论（嵌入方案设计）
1. **沉默螺旋规律**: 群体压力下意见趋同 → 需识别优势意见与沉默声音
2. **议程设置规律**: 媒体与公众焦点互动 → 需追踪话题演变路径
3. **蝴蝶效应规律**: 微小事件指数级放大 → 需建立萌芽期预警
4. **生命周期规律**: 发生→发展→峰值→衰退 → 需分阶段策略响应
5. **博弈均衡规律**: 政府与网民策略互动 → 需评估回应效果
6. **社会燃烧规律**: 矛盾累积临界点爆发 → 需监测情绪积累

### 0.2 案例库结构（知识库核心）

```yaml
# 案例库JSON Schema（可直接导入Neo4j）
CaseTemplate:
  metadata:
    case_id: string          # YYYY-领域-关键词-序号
    event_type: [category]   # 消费争议/品牌危机/食品安全/医疗健康等
    domain: string           # 行业/领域
    geo_scope: string        # 地理范围
    monitoring_window: [start, end]
    keywords: [string]
    status: draft/complete/reviewed/archived

  actors:                    # 涉事主体
    - actor_id: string
      name: string
      type: person/company/regulator/media/platform
      role: igniter/amplifier/corrector/opponent/authority

  timeline:                  # 关键节点时间线
    - timestamp: datetime
      description: string
      actors: [actor_id]
      platform: string
      node_type: deny/clarify/apologize/escalation/cooldown

  platform_ecology:          # 平台生态
    - platform: weibo/douyin/xiaohongshu/news
      roles: [agenda-ignition/emotional-resonance/fact-checking]
      formats: [热搜/转评链/短视频/弹幕]

  emotion_clusters:          # 情绪结构
    - emotion: anger/anxiety/moral-outrage/sympathy
      polarity: negative/positive/mixed
      peak_phase: ignite/confront/diffuse

  issue_frames:              # 议题框架
    - frame_label: string
      core_claim: string
      narrative_patterns: [string]
      opposing_frames: [string]

  responses:                 # 主体回应
    - actor_id: string
      timestamp: datetime
      type: deny/clarify/apologize/counterattack
      tone_style: technical-bureaucratic/emotional/legalistic

  outcomes:
    trajectory: cooldown/oscillation/long-tail/institutionalized
    results: [regulatory-intervention/policy-revision/brand-damage]
```

---

## 一、现有架构回顾

### 已实现模块
- `neo4j_client.py`: 连接管理
- `schema.py`: 图结构初始化（约束、索引、向量索引）
- `chunker.py`: 文本切块（chunk_size=520, overlap=80）
- `embedder.py`: 向量化（BAAI/bge-small-zh-v1.5, 512维）
- `retriever.py`: 混合检索（向量 + 全文 + 图跳转）
- `pipeline.py`: 端到端问答流程

### 已有节点类型
- Platform, Account, Post, Chunk, SourceDoc
- Entity, Claim, Topic, Frame, Event

---

## 二、核心设计强化

### 2.1 Embedding 策略（三层分离）

```python
class MultiLayerEmbedder:
    """针对舆情分析的三层Embedding策略"""
    
    # 层1: 基础语义层（通用）
    semantic_model = "BAAI/bge-small-zh-v1.5"  # 通用文本理解
    
    # 层2: 领域适配层（舆情专用）
    domain_model = "embedding-domain-舆情分析-v1"  # 微调模型
    
    # 层3: 任务导向层（按分析类型）
    task_embeddings = {
        "趋势判断": "trend_vector",      # 时间序列特征
        "情绪分析": "sentiment_vector", # 情感极性特征
        "影响力评估": "impact_vector",  # 传播力度特征
    }
```

**Embedding 维度扩展**:
| 维度 | 向量类型 | 用途 |
|------|---------|------|
| 512维 | semantic | 基础语义匹配 |
| 256维 | domain | 舆情领域相关度 |
| 128维 × 3 | task-specific | 具体分析任务 |

### 2.2 Chunk 策略（按内容类型分级）

```python
class ContextAwareChunker:
    """根据内容类型采用不同chunk策略"""
    
    CHUNK_STRATEGIES = {
        # 政策/报告类：按章节结构切分
        "policy": {
            "method": "heading-based",
            "preserve_structure": True,
            "chunk_size": 2000,
            "fields": ["title", "section", "content", "source"]
        },
        # 案例/事件类：按事件要素切分（对接案例库模板）
        "case": {
            "method": "event要素",
            "preserve_structure": True, 
            "chunk_size": 1500,
            "fields": ["case_id", "actor", "timestamp", "description", "platform", "node_type"]
        },
        # 方法论文献：按逻辑段落切分
        "methodology": {
            "method": "passage",
            "preserve_structure": False,
            "chunk_size": 800,
            "fields": ["theory_name", "core_concept", "network_manifestation", "case_example"]
        },
        # 日常舆情数据：按帖子/会话切分
        "post": {
            "method": "post",
            "preserve_structure": True,
            "chunk_size": 500,
            "fields": ["post_id", "author", "content", "timestamp", "platform", "emotion"]
        },
        # 回应/声明类：按主体+时间+类型切分
        "response": {
            "method": "response",
            "preserve_structure": True,
            "chunk_size": 800,
            "fields": ["actor_id", "timestamp", "response_type", "tone_style", "content_summary"]
        }
    }
    
    def extract_chunk_metadata(self, text: str, chunk_type: str) -> dict:
        """提取chunk元数据，适配案例库结构"""
        if chunk_type == "case":
            # 从案例文本中提取关键要素
            return {
                "case_id": self.extract_case_id(text),
                "trigger_time": self.extract_timestamp(text, "trigger"),
                "actors": self.extract_actors(text),
                "emotion_clusters": self.extract_emotions(text),
                "stage": self.detect_stage(text)  # ignite/confront/diffuse/reflect/institutional
            }
        elif chunk_type == "methodology":
            return {
                "theory_name": self.extract_theory_name(text),
                "core_concept": self.extract_concept(text),
                "network_manifestation": self.extract_network_pattern(text),
                "case_example": self.extract_example(text)
            }
        return {}
```

### 2.3 Node/Relationship 设计优化

#### 节点类型扩展
```cypher
// ====== 舆情分析核心节点 ======

// 案例节点（Case）- 对接案例库模板
(Case:Case {
    case_id: string,              // YYYY-领域-关键词-序号
    case_title: string,           // 案例名称
    event_type: list,             // [消费争议,品牌危机,食品安全...]
    domain: string,               // 行业/领域
    geo_scope: string,            // 地理范围
    keywords: list,               // 核心关键词
    status: string,               // draft/complete/reviewed/archived
    one_line_summary: string,     // 一句话摘要
    stage: string,                // ignite/confront/diffuse/reflect/institutional
    trajectory: string            // cooldown/oscillation/long-tail/institutionalized
})

// 主体节点（Actor）- 涉事方
(Actor:Actor {
    actor_id: string,
    name: string,
    type: string,                 // person/company/regulator/media/platform/public/ngo
    role: string,                 // igniter/amplifier/corrector/opponent/authority/witness
    aliases: list,
    influence_score: float,       // 影响力评分
    verified: boolean             // 是否认证
})

// 平台节点（Platform）- 传播渠道
(Platform:Platform {
    platform_id: string,          // weibo/douyin/xiaohongshu/news/forum
    platform_name: string,
    roles: list,                  // agenda-ignition/emotional-resonance/fact-checking/rumor-spread
    user_scale: string,           // 用户规模
    verification_level: string    // 信息审核级别
})

// 时间线节点（TimelineNode）
(TimelineNode:TimelineNode {
    node_id: string,
    timestamp: datetime,
    description: string,
    node_type: string,            // deny/clarify/apologize/counterattack/litigation/escalation/cooldown
    platform: string,
    event_phase: string           // 潜伏期/萌芽期/爆发期/衰退期
})

// 情绪簇节点（EmotionCluster）
(EmotionCluster:EmotionCluster {
    emotion: string,              // anger/anxiety/moral-outrage/sympathy/fatigue
    polarity: string,             // negative/neutral/positive/mixed
    intensity: float,             // 强度 0-1
    peak_phase: string,           // 峰值阶段
    trigger_mechanism: string     // 触发机制说明
})

// 议题框架节点（IssueFrame）
(IssueFrame:IssueFrame {
    frame_label: string,
    core_claim: string,           // 核心主张 ≤120字
    narrative_patterns: list,     // 典型叙事模式 3-8条
    support_groups: list,         // 支持群体
    opposing_frames: list,        // 对立框架
    frame_frequency: integer      // 出现频次
})

// 舆情规律节点（Theory）- 方法论
(Theory:Theory {
    theory_id: string,
    theory_name: string,          // 沉默螺旋/议程设置/蝴蝶效应/生命周期/博弈均衡/社会燃烧
    core_concept: string,
    network_manifestation: string,// 网络表现
    case_example: string,         // 案例佐证
    governance_insight: string    // 治理启示
})

// 回应节点（Response）
(Response:Response {
    response_id: string,
    timestamp: datetime,
    response_type: string,        // deny/clarify/apologize/counterattack/litigation/remediation
    tone_style: string,           // technical-bureaucratic/emotional/legalistic/conciliatory
    content_summary: string,
    effectiveness: float          // 回应效果评分
})

// 指标节点（Indicator）- 量化指标
(Indicator:Indicator {
    indicator_id: string,
    name: string,                 // 声量/情感/传播力/响应时效
    value: float,
    unit: string,
    time_range: string,
    source_platform: string
})

// 原有节点增强
(Entity {
    entity_id: string,
    canonical_name: string,
    aliases: list,
    entity_type: string,          // person/org/location/product/event
    confidence: float,
    extraction_source: string,    // manual/llm/nlp
    feedback_score: float,
    updated_at: datetime
})
```

#### 关系类型扩展
```cypher
// ====== 舆情分析核心关系 ======

// 案例关联关系
(case:Case)-[:HAS_ACTOR]->(actor:Actor)
(case:Case)-[:CONTAINS_TIMELINE]->(node:TimelineNode)
(case:Case)-[:EXHIBITS_EMOTION]->(emotion:EmotionCluster)
(case:Case)-[:USES_FRAME]->(frame:IssueFrame)
(case:Case)-[:HAS_OUTCOME]->(outcome:Outcome)

// 传播关系
(actor:Actor)-[:POSTED_ON {platform, timestamp, content}]->(post:Post)
(post:Post)-[:SPREAD_VIA]->(platform:Platform)
(post:Post)-[:TRIGGERED_BY]->(event:Event)
(platform:Platform)-[:RESONATES_WITH]->(another_platform:Platform)

// 时间线关系
(node1:TimelineNode)-[:LEADS_TO]->(node2:TimelineNode)
(node:TimelineNode)-[:INVOLVES]->(actor:Actor)
(node:TimelineNode)-[:OCCURRED_ON]->(platform:Platform)

// 情绪传导关系
(emotion1:EmotionCluster)-[:TRANSFORMS_TO]->(emotion2:EmotionCluster)
(emotion:EmotionCluster)-[:DRIVES]->(post:Post)

// 议题框架关系
(frame1:IssueFrame)-[:OPPOSES]->(frame2:IssueFrame)
(frame:IssueFrame)-[:SUPPORTS]->(narrative:Narrative)

// 回应关系
(actor:Actor)-[:RESPONDS_WITH]->(response:Response)
(response:Response)-[:TARGETS]->(issue:IssueFrame)
(response:Response)-[:EFFECTS {trajectory_change}]->(case:Case)

// 方法论应用关系
(case:Case)-[:EXEMPLIFIES]->(theory:Theory)
(theory:Theory)-[:APPLIES_TO]->(indicator:Indicator)
(theory:Theory)-[:GUIDES]->(strategy:Strategy)

// 指标测量关系
(indicator:Indicator)-[:MEASURES]->(dimension:Dimension)  # 量/质/人/场/效
(indicator:Indicator)-[:DERIVED_FROM]->(platform:Platform)

// 反馈闭环关系
(chunk:Chunk)-[:FEEDBACK {score: float, feedback: string}]->(chunk)
(entity:Entity)-[:HUMAN_CORRECTED {correction: string}]->(entity)
(case:Case)-[:FEEDBACK_VALIDATED {score, detail}]->(case)

// 原有关系保留
(p1:Person)-[:COLLABORATES]->(p2:Person)
(e1:Entity)-[:SUPPORTS]->(claim:Claim)
(e1:Entity)-[:REFUTES]->(claim:Claim)
(topic1:Topic)-[:LEADS_TO]->(topic2:Topic)
(post:Post)-[:DERIVES_FROM]->(event:Event)
(method:Method)-[:APPLIES_TO]->(indicator:Indicator)
(method:Method)-[:CITES]->(reference:Reference)
(indicator:Indicator)-[:MEASURES]->(concept:Concept)
```

---

## 三、RLHF 反馈机制设计

### 3.1 反馈数据模型

```python
class FeedbackRecord:
    """人类反馈记录"""
    query: str                      # 用户问题
    retrieved_chunks: List[str]     # 召回的chunk_id
    generated_answer: str           # 生成的答案
    feedback_type: str              # correct/incorrect/incomplete
    feedback_detail: str            # 详细反馈
    user_id: str                    # 反馈用户
    created_at: datetime

class OpinionFeedbackRecord(FeedbackRecord):
    """舆情分析专用反馈"""
    # 维度准确性反馈（5C框架）
    dimension_accuracy: {
        "count": float,     # 量（声量/增速）判断是否准确
        "quality": float,   # 质（情感/话题）判断是否准确
        "actor": float,     # 人（KOL识别）是否准确
        "arena": float,     # 场（平台分布）是否准确
        "effect": float     # 效（影响评估）是否准确
    }
    
    # 阶段判断反馈
    stage_accuracy: float           # 潜伏/萌芽/爆发/衰退判断
    trajectory_accuracy: float      # 走向判断（cooldown/oscillation等）
    
    # 规律识别反馈
    theory_identified: List[str]    # 识别出的舆情规律
    theory_accuracy: Dict[str, float]  # 各规律识别准确度
    
    # 案例匹配反馈
    case_similarity: float          # 相似案例推荐相关度
    case_relevance: List[str]       # 相关案例列表
```

### 3.2 反馈闭环流程

```
用户提问 → GraphRAG召回 → 生成答案 → 用户反馈
     ↓                                    ↓
  评估答案    ←←←←←←←←←←←←←←←←←←←  反馈记录
     ↓
  维度校验 → 阶段判断 → 规律识别 → 案例匹配
     ↓
  更新权重 ←← 反馈分析 → 识别问题类型
     ↓
  优化策略 → 调整召回/重排/生成参数
```

### 3.3 反馈驱动的优化

```python
class FeedbackOptimizer:
    """基于反馈持续优化RAG系统"""
    
    def analyze_feedback(self, feedback_records: List[FeedbackRecord]):
        """分析反馈，识别系统性问题"""
        issues = {
            "missing_entity": [],      # 漏召回实体
            "wrong_chunk": [],         # 召错chunk
            "incomplete_answer": [],   # 答案不完整
            "factual_error": [],       # 事实错误
        }
        # 统计分析各类问题占比
        # 生成优化建议
        return optimization_report
    
    def retrain_embedding(self, positive_samples, negative_samples):
        """基于反馈数据微调embedding模型"""
        # 收集正例（用户认为相关的）
        # 收集负例（用户认为不相关的）
        # 训练领域适配的embedding
    
    def update_chunk_weights(self, chunk_performance: Dict[str, float]):
        """根据反馈调整chunk重要度权重"""
        # 高频召回且正确的chunk → 增加向量权重
        # 频繁出错召回的chunk → 降低权重或标记

class OpinionFeedbackAnalyzer:
    """舆情分析专用反馈分析"""
    
    def analyze_feedback(self, feedback_records: List[OpinionFeedbackRecord]):
        """分析反馈，识别系统性问题"""
        issues = {
            # 维度判断问题
            "count_error": [],       # 声量/增速判断错误
            "quality_error": [],     # 情感/话题判断错误
            "actor_error": [],       # KOL识别遗漏/错误
            "arena_error": [],       # 平台分布判断错误
            "effect_error": [],       # 影响评估偏差
            
            # 阶段/走向判断问题
            "stage_error": [],       # 生命周期阶段判断错误
            "trajectory_error": [],  # 舆情走向预判错误
            
            # 规律识别问题
            "theory_miss": [],       # 未识别出的舆情规律
            "theory_false": [],      # 误判的舆情规律
            
            # 案例匹配问题
            "case_miss": [],         # 遗漏的相关案例
            "case_irrelevant": [],  # 推荐的无关案例
        }
        
        # 统计分析各类问题占比
        # 生成维度准确性报告
        # 输出优化建议
        return {
            "accuracy_by_dimension": self.calc_dimension_accuracy(feedback_records),
            "stage_accuracy": self.calc_stage_accuracy(feedback_records),
            "theory_accuracy": self.calc_theory_accuracy(feedback_records),
            "optimization_suggestions": self.generate_suggestions(issues)
        }
    
    def get_case_patterns(self, correct_cases: List[dict]) -> dict:
        """从正确案例中提取规律模式"""
        return {
            "event_type_patterns": self.extract_event_types(correct_cases),
            "actor_role_patterns": self.extract_actor_roles(correct_cases),
            "emotion_evolution_patterns": self.extract_emotion_patterns(correct_cases),
            "response_effectiveness": self.analyze_response_effectiveness(correct_cases),
            "stage_transition_signals": self.extract_stage_signals(correct_cases)
        }

class OpinionRAGOptimizer:
    """舆情RAG专项优化"""
    
    def optimize_dimension_weight(self, dimension_errors: dict):
        """优化分析维度权重（5C框架）"""
        # 调整 量/质/人/场/效 各维度在召回中的权重
        
    def improve_stage_detection(self, stage_errors: list):
        """改进阶段检测模型"""
        # 优化潜伏→萌芽→爆发→衰退的判断逻辑
        
    def enhance_theory_recognition(self, theory_errors: dict):
        """增强舆情规律识别能力"""
        # 针对沉默螺旋、议程设置、蝴蝶效应等的识别优化
        
    def refine_case_matching(self, case_errors: list):
        """改进案例匹配算法"""
        # 提高相似案例推荐的准确度
```

---

## 四、调用接口设计

### 4.1 基础调用（配置后可用）

```python
from rag.pipeline import GraphRAGPipeline

# 初始化（读取neo4j.yaml配置）
rag = GraphRAGPipeline()

# 基础问答
result = rag.query("分析近期食品安全舆情的发展趋势")
print(result["answer"])
```

### 4.2 高级调用（自定义参数）

```python
# 自定义召回策略
result = rag.query(
    question="XXX事件中意见领袖有哪些",
    top_k=10,
    retrieval_mode="hybrid",  # vector/fulltext/graph
    filters={
        "platform": "weibo",
        "time_range": "2025-01-01:2025-12-31",
        "entity_type": "person"
    },
    include_sources=True
)
```

### 4.3 反馈提交接口

```python
# 提交反馈
rag.submit_feedback(
    query="...",
    feedback_type="incorrect",
    detail="召回的案例与问题不相关"
)

# 查看反馈统计
stats = rag.get_feedback_stats()
```

### 4.4 舆情分析专用接口（新增）

```python
# ====== 舆情分析专用接口 ======

# 维度分析（5C框架）
result = rag.analyze_dimension(
    target_event="某品牌食品安全事件",
    dimensions=["count", "quality", "actor", "arena", "effect"],
    time_range="2025-01-01:2025-03-01"
)
# 返回: {count: {声量, 增速, 峰值}, quality: {情感分布, 话题聚类}, ...}

# 阶段判断
result = rag.detect_stage(
    event="某政策舆情",
    current_data={"posts": [...], "trends": [...]}
)
# 返回: {stage: "爆发期", confidence: 0.85, signals: [...]}

# 规律识别
result = rag.identify_theory(
    event="某群体性事件",
    timeline=[...]
)
# 返回: {theories: ["沉默螺旋", "群体极化"], confidence: 0.78}

# 案例匹配
result = rag.match_similar_cases(
    current_event={"type": "品牌危机", "domain": "食品", "stage": "爆发期"},
    top_k=5
)
# 返回: [{case_id, similarity, key_diff, lessons}, ...]

# 综合分析报告
result = rag.generate_opinion_report(
    event="某企业舆情事件",
    include_sections=["维度分析", "阶段判断", "规律识别", "相似案例", "应对建议"]
)
# 返回: 完整的舆情分析报告

# 回应效果评估
result = rag.evaluate_response(
    event_id="2025-食品-某事件-001",
    response_actor="企业官方",
    response_content="..."
)
# 返回: {effectiveness: 0.72, trajectory_prediction: "cooldown", suggestions: [...]}
```

### 4.5 舆情反馈提交接口（新增）

```python
# 维度准确性反馈
rag.submit_dimension_feedback(
    query="分析某事件的声量趋势",
    dimension="count",
    accuracy=0.6,
    detail="声量数据偏低，实际峰值达到XXX"
)

# 阶段判断反馈
rag.submit_stage_feedback(
    event_id="2025-xxx-001",
    predicted_stage="爆发期",
    actual_stage="萌芽期",
    correct_prediction=False
)

# 规律识别反馈
rag.submit_theory_feedback(
    event_id="2025-xxx-001",
    identified_theories=["蝴蝶效应", "议程设置"],
    actual_theories=["沉默螺旋", "社会燃烧"],
    missing_theories=["沉默螺旋"],
    false_theories=[]
)
```

---

## 五、部署与配置

### 5.1 环境配置

```yaml
# config/rag.yaml
rag:
  neo4j:
    uri: "neo4j+s://b25c654b.databases.neo4j.io"
    user: "neo4j"
    password: "${NEO4J_PASSWORD}"
  
  embedding:
    model: "BAAI/bge-small-zh-v1.5"
    dimension: 512
    
  chunking:
    default_size: 520
    default_overlap: 80
    
  feedback:
    enabled: true
    storage: "neo4j"  # 或 postgres
```

### 5.2 调用权限管理

```python
# 简单的配置管理
class RAGAccessControl:
    """RAG调用权限控制"""
    
    ALLOWED_CONFIGS = {
        "public": {"top_k": 5, "modes": ["vector"]},
        "researcher": {"top_k": 15, "modes": ["vector", "fulltext", "graph"]},
        "admin": {"top_k": 30, "modes": ["all"], "feedback": True},
    }
```

---

## 六、实施路线图

### Phase 1: 基础建设（1-2周）
- [ ] 完善 schema（新增节点类型）
- [ ] 优化 chunker（按内容类型分级）
- [ ] 实现三层 embedding

### Phase 2: 反馈系统（2-3周）
- [ ] 建立反馈数据模型
- [ ] 开发反馈提交接口
- [ ] 实现基础统计分析

### Phase 3: 智能优化（3-4周）
- [ ] 反馈分析引擎
- [ ] 召回策略自动调整
- [ ] embedding 微调流程

### Phase 4: 开放调用（持续）
- [ ] API 接口开发
- [ ] 权限管理系统
- [ ] 使用文档编写

---

## 七、知识库初始化（预置内容）

### 7.1 舆情规律节点（预置）

```cypher
// 初始化舆情规律节点（从方法论文档导入）
CREATE (t1:Theory {
    theory_id: "theory_001",
    theory_name: "沉默螺旋规律",
    core_concept: "群体压力下的意见趋同，个体在感知自身意见属少数时因恐惧孤立而保持沉默",
    network_manifestation: "在群体性事件中，点赞、转发等行为无形施加压力，使异议声音被淹没",
    case_example: "药家鑫案：支持严惩的言论占据主流，质疑司法公正的理性讨论迅速沉寂",
    governance_insight: "需关注优势意见与沉默声音的平衡，避免一边倒的舆论假象"
})

CREATE (t2:Theory {
    theory_id: "theory_002",
    theory_name: "议程设置规律",
    core_concept: "媒体通过选择性报道影响公众关注焦点，形成政府、媒体与网民的双向议程竞争",
    network_manifestation: "热点事件经微博、论坛等平台发酵后，传统媒体跟进报道，放大舆情声势",
    case_example: "厦门PX事件：网民联名抗议迫使政府将项目迁址，体现公众议程反推政策调整",
    governance_insight: "政府需主动设置议程，引导舆论走向"
})

CREATE (t3:Theory {
    theory_id: "theory_003",
    theory_name: "蝴蝶效应规律",
    core_concept: "复杂系统中微小变化可能引发连锁反应，网络的低门槛与即时性使局部事件迅速演变为全局危机",
    network_manifestation: "谣言或不实信息通过转发、评论几何级扩散",
    case_example: "浙江瑞安戴海静事件：一则官员涉案谣言触发大规模聚集",
    governance_insight: "需建立舆情萌芽期预警机制，截断负面信息传播链"
})

CREATE (t4:Theory {
    theory_id: "theory_004",
    theory_name: "生命周期规律",
    core_concept: "舆情遵循发生—发展—峰值—衰退的周期律，各阶段主导因素各异",
    network_manifestation: "初始期依赖敏感事件触发，扩散期受群体情绪驱动，消退期依赖政策干预或注意力转移",
    case_example: "药家鑫案：教授观点引发全网辩论后逐渐消退",
    governance_insight: "需针对不同阶段采取差异化策略"
})

CREATE (t5:Theory {
    theory_id: "theory_005",
    theory_name: "博弈均衡规律",
    core_concept: "舆情是政府与网民在信息控制与利益诉求间的动态博弈，合作策略可实现双赢",
    network_manifestation: "政府封锁信息会激发网民逆反心理，公开信息、理性表达利于舆情平息",
    case_example: "瓮安事件：信息不透明加剧打砸抢烧；乌坎事件后期政府协商化解矛盾",
    governance_insight: "建立政府与网民的合作博弈机制"
})

CREATE (t6:Theory {
    theory_id: "theory_006",
    theory_name: "社会燃烧规律",
    core_concept: "类比燃烧三要素：可燃物（社会矛盾）、助燃剂（触发事件）、点火温度（情绪煽动）共同引发舆情燃烧",
    network_manifestation: "土地纠纷长期累积+村干部贪腐曝光+网络动员，三者叠加最终爆发群体性抗议",
    case_example: "广东乌坎事件",
    governance_insight: "需监测社会矛盾累积，及时化解潜在可燃物"
})
```

### 7.2 分析维度指标（预置）

```cypher
// 初始化5C分析维度指标
CREATE (d1:Indicator {
    indicator_id: "count_volume",
    name: "声量",
    description: "舆情信息总量，包括发帖数、评论数、转发数等",
    unit: "条",
    dimension: "count"
})

CREATE (d2:Indicator {
    indicator_id: "count_growth",
    name: "增速",
    description: "舆情信息增长速率",
    unit: "%",
    dimension: "count"
})

CREATE (d3:Indicator {
    indicator_id: "count_peak",
    name: "峰值",
    description: "舆情信息量的最高点",
    unit: "条/小时",
    dimension: "count"
})

CREATE (d4:Indicator {
    indicator_id: "quality_sentiment",
    name: "情感极性",
    description: "正面/中性/负面情感占比",
    unit: "%",
    dimension: "quality"
})

CREATE (d5:Indicator {
    indicator_id: "quality_topic",
    name: "话题焦点",
    description: "主要讨论话题及分布",
    unit: "个",
    dimension: "quality"
})

CREATE (d6:Indicator {
    indicator_id: "actor_kol",
    name: "KOL影响力",
    description: "关键意见领袖的影响力评分",
    unit: "分",
    dimension: "actor"
})

CREATE (d7:Indicator {
    indicator_id: "arena_platform",
    name: "平台分布",
    description: "各平台舆情热度分布",
    unit: "%",
    dimension: "arena"
})

CREATE (d8:Indicator {
    indicator_id: "effect_behavior",
    name: "行为转化",
    description: "舆情引发的实际行为（搜索量/销量变化/投诉量）",
    unit: "变化率%",
    dimension: "effect"
})
```

### 7.3 案例库模板导入

```python
# 从案例库模板初始化知识库
def init_case_template():
    """导入案例库结构到Neo4j"""
    
    # 创建案例索引
    create_index("Case", "case_id", "unique")
    create_index("Case", "event_type")
    create_index("Case", "stage")
    create_index("Case", "status")
    
    # 创建主体索引
    create_index("Actor", "actor_id", "unique")
    create_index("Actor", "type")
    create_index("Actor", "role")
    
    # 创建平台索引
    create_index("Platform", "platform_id", "unique")
    
    # 创建时间线索引
    create_index("TimelineNode", "timestamp")
    create_index("TimelineNode", "event_phase")
    
    # 创建理论索引
    create_index("Theory", "theory_name", "unique")
    
    print("案例库结构初始化完成")
```

### 7.4 样例案例导入

```python
# 导入一个示例案例（罗永浩-西贝预制菜事件）
def load_sample_case():
    """加载示例案例到知识库"""
    
    # 可从已有案例文档导入
    # 位置: ~/Documents/sanhu_vault/Projects/舆情分析及系统开发/罗永浩—西贝"预制菜"争议事件.md
    
    sample_case = {
        "case_id": "2025-餐饮-预制菜-001",
        "case_title": "罗永浩西贝预制菜争议事件",
        "event_type": ["消费争议", "食品安全"],
        "domain": "餐饮",
        "stage": "消退期",
        "trajectory": "cooldown"
    }
    
    # 导入到Neo4j
    create_case(sample_case)
    print(f"案例 {sample_case['case_id']} 导入完成")
```

---

## 八、Neo4j 连接信息

```
URI: neo4j+s://b25c654b.databases.neo4j.io
用户名: neo4j
密码: CwFz9qFpcslgLWlK3TdYyBi8rU6f13mCjGJP73TLzPQ
数据库: neo4j
```

---

*注：本方案基于现有 opinion-system-fluid-master 架构强化，整合舆情分析方法论文档（~/Documents/sanhu_vault/Projects/舆情分析及系统开发/舆情分析方法论.md）和案例库模板结构，重点解决"减少大模型幻觉"、"支持舆情分析维度校验"和"RLHF持续进化"三个核心需求。*

*v5.1更新：增加舆情分析方法论基础（0.1-0.2）、增强Chunk策略（2.2）、扩展节点/关系类型（2.3）、舆情专用反馈机制（3.1-3.3）、专用API接口（4.4-4.5）、知识库初始化（第七章）。*