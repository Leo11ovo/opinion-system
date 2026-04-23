"""
RAG检索系统
功能：时间智能过滤、三种检索策略（GraphRAG/NormalRAG/TagRAG）、多跳查询、可配置参数
"""
import asyncio
import json
import lancedb
import yaml
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from ...setting.paths import get_project_root, get_configs_root
from ...setting.env_loader import get_api_key
from ...setting.settings import settings
from ...logging.logging import setup_logger, log_success, log_error, log_module_start
from ...ai.qwen import QwenClient
from src.rag.retrievers import GraphRAGFormatter, GraphRAGRetriever

QUESTION_TYPE_PRESETS: Dict[str, Dict[str, Any]] = {
    "fact": {
        "mode": "normalrag",
        "topk_graphrag": 3,
        "topk_normalrag": 8,
        "topk_tagrag": 2,
        "enable_expert_overlay": False,
        "enable_expert_rewrite": False,
        "enable_expert_hints": False,
        "enable_expert_answer_structure": False,
        "llm_summary_mode": "strict",
    },
    "explain": {
        "mode": "mixed",
        "topk_graphrag": 4,
        "topk_normalrag": 8,
        "topk_tagrag": 3,
        "enable_expert_overlay": True,
        "enable_expert_rewrite": True,
        "enable_expert_hints": True,
        "enable_expert_answer_structure": True,
        "llm_summary_mode": "supplement",
    },
    "compare": {
        "mode": "mixed",
        "topk_graphrag": 5,
        "topk_normalrag": 10,
        "topk_tagrag": 4,
        "enable_expert_overlay": True,
        "enable_expert_rewrite": True,
        "enable_expert_hints": True,
        "enable_expert_answer_structure": True,
        "llm_summary_mode": "supplement",
    },
    "decision": {
        "mode": "mixed",
        "topk_graphrag": 6,
        "topk_normalrag": 10,
        "topk_tagrag": 5,
        "enable_expert_overlay": True,
        "enable_expert_rewrite": True,
        "enable_expert_hints": True,
        "enable_expert_answer_structure": True,
        "llm_summary_mode": "supplement",
    },
    "explore": {
        "mode": "mixed",
        "topk_graphrag": 3,
        "topk_normalrag": 8,
        "topk_tagrag": 3,
        "enable_expert_overlay": True,
        "enable_expert_rewrite": True,
        "enable_expert_hints": True,
        "enable_expert_answer_structure": True,
        "llm_summary_mode": "strict",
    },
}


def detect_question_type(query: str) -> str:
    text = str(query or "").strip()
    if not text:
        return "explore"
    if re.search(r"(怎么办|如何应对|策略|建议|处置|治理)", text):
        return "decision"
    if re.search(r"(对比|比较|差异|像不像|相似|类似)", text):
        return "compare"
    if re.search(r"(为什么|原因|机理|如何解释|背后)", text):
        return "explain"
    if re.search(r"(发生了什么|谁|哪里|多少|何时|数据|现状)", text):
        return "fact"
    return "explore"


def get_available_router_topics():
    """
    获取可用的RouterRAG专题列表。

    Returns:
        List[str]: 专题名称列表
    """
    topics = []
    try:
        router_dir = get_project_root() / "src" / "utils" / "rag" / "ragrouter"
        if router_dir.exists():
            topics = [d.name for d in router_dir.iterdir()
                     if d.is_dir() and (d / "normal_db").exists()]
            log_success(None, f"Found {len(topics)} RouterRAG topics: {topics}", "RouterRAG")
        else:
            log_error(None, f"RouterRAG directory not found: {router_dir}", "RouterRAG")
    except Exception as e:
        log_error(None, f"Failed to get RouterRAG topics: {e}", "RouterRAG")

    return topics


@dataclass
class TimeRange:
    """时间范围"""
    has_time: bool
    time_text: str
    matched_docs: List[str]


@dataclass
class SearchParams:
    """检索参数
    
    说明：
    - 所有检索使用向量距离（cosine distance）
    - 距离值越小表示越相似（0表示完全相同，1表示完全不相关）
    - 所有结果已按距离从小到大排序
    """
    query_topic: str
    query_text: str
    search_mode: str  # mixed/graphrag/normalrag/tagrag
    topk_graphrag: int = 3  # Neo4j GraphRAG返回命中数量上限
    topk_normalrag: int = 5
    topk_tagrag: int = 5
    enable_query_expansion: bool = True  # 是否启用查询扩展/重写
    enable_llm_summary: bool = True  # 是否启用LLM整理结果
    llm_summary_mode: str = "strict"  # strict(严格模式)/supplement(补充模式)
    return_format: str = "both"  # both(都返回)/llm_only(仅LLM整理)/index_only(仅索引结果)
    enable_expert_overlay: bool = True  # 是否启用专家图谱外挂
    enable_expert_rewrite: bool = True  # 是否启用专家查询改写
    enable_expert_hints: bool = True  # 是否启用专家提示重排
    enable_expert_answer_structure: bool = True  # 是否启用结构化回答模板


@dataclass
class NormalRAGResult:
    """NormalRAG检索结果"""
    sentences: List[Dict]


@dataclass
class TagRAGResult:
    """TagRAG检索结果"""
    text_blocks: List[Dict]

class LLMHelper:
    """LLM辅助类 - 用于时间提取、匹配和结果整理"""
    
    def __init__(self, qwen_client: QwenClient, logger, model: str, prompts_file: str):
        self.qwen_client = qwen_client
        self.logger = logger
        self.model = model
        
        # 加载提示词配置
        self.prompts = self._load_prompts(prompts_file)
    
    def _load_prompts(self, prompts_file: str) -> Dict[str, Any]:
        """加载提示词配置文件"""
        try:
            prompts_dir = get_configs_root() / "prompt" / "router_retrieve"
            candidates = [prompts_file, "默认.yaml", "控烟.yaml", "test.yaml"]
            seen = set()
            ordered_candidates = []
            for name in candidates:
                key = str(name or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                ordered_candidates.append(key)

            for name in ordered_candidates:
                prompts_path = prompts_dir / name
                if not prompts_path.exists():
                    continue
                with open(prompts_path, "r", encoding="utf-8") as f:
                    prompts = yaml.safe_load(f) or {}
                if not isinstance(prompts, dict):
                    continue
                if name != prompts_file:
                    log_error(self.logger, f"提示词文件不存在或不可用: {prompts_file}，已回退到 {name}", "llm")
                return prompts

            log_error(self.logger, f"未找到可用提示词文件: {prompts_file}", "llm")
            return {}
        except Exception as e:
            log_error(self.logger, f"加载提示词配置失败: {str(e)}", "llm")
            return {}
    
    async def call_api(self, prompt: str, max_tokens: int = 2000, retry: int = 3) -> str:
        """调用API（使用系统QwenClient，支持重试，增加超时时间）"""
        import asyncio
        import aiohttp
        
        for attempt in range(retry):
            try:                
                # 由于QwenClient超时设置较短（60秒），对于大量数据的总结可能不够
                # 这里直接调用API，使用更长的超时时间（180秒）
                headers = {
                    "Authorization": f"Bearer {self.qwen_client.api_key}",
                    "Content-Type": "application/json"
                }
                data = {
                    "model": self.model,
                    "input": {"messages": [{"role": "user", "content": prompt}]},
                    "parameters": {"max_tokens": max_tokens}
                }
                
                # 使用更长的超时时间
                timeout = aiohttp.ClientTimeout(total=180, connect=10, sock_read=120)
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                        json=data,
                        headers=headers
                    ) as resp:
                        if resp.status == 200:
                            response_data = await resp.json()
                            text = response_data.get('output', {}).get('text', '')
                            usage = response_data.get('usage', {})
                            
                            if text:
                                return text
                            else:
                                log_error(self.logger, "API返回200但text为空", "llm")
                                return ""
                        else:
                            # 非200状态码
                            error_body = await resp.text()
                            if attempt < retry - 1:
                                wait_time = (attempt + 1) * 5
                                log_error(self.logger, f"HTTP {resp.status}（尝试{attempt+1}/{retry}），{wait_time}秒后重试...", "llm")
                                log_error(self.logger, f"错误: {error_body[:300]}", "llm")
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                log_error(self.logger, f"HTTP {resp.status}，已重试{retry}次", "llm")
                                log_error(self.logger, f"错误详情: {error_body}", "llm")
                                return ""
                        
            except asyncio.TimeoutError:
                if attempt < retry - 1:
                    wait_time = (attempt + 1) * 5
                    log_error(self.logger, f"请求超时（尝试{attempt+1}/{retry}），{wait_time}秒后重试...", "llm")
                    log_error(self.logger, f"提示：当前提示词{len(prompt)}字符，如果持续超时请减少topk参数", "llm")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    log_error(self.logger, f"请求超时，已重试{retry}次（超时限制：180秒）", "llm")
                    log_error(self.logger, f"提示词长度: {len(prompt)}字符，可能过长导致处理超时", "llm")
                    log_error(self.logger, "建议：1.减少topk参数 2.使用--no-llm-summary跳过LLM整理", "llm")
                    return ""
                    
            except Exception as e:
                if attempt < retry - 1:
                    wait_time = (attempt + 1) * 5
                    log_error(self.logger, f"调用异常: {str(e)}，{wait_time}秒后重试...", "llm")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    log_error(self.logger, f"调用失败，已重试{retry}次: {str(e)}", "llm")
                    import traceback
                    log_error(self.logger, traceback.format_exc(), "llm")
                    return ""
        
        return ""
    
    async def summarize_results(self, query: str, search_results: Dict[str, Any], mode: str = "strict") -> str:
        """使用LLM整理检索结果为结构化资料
        
        Args:
            query: 用户查询
            search_results: 检索结果
            mode: 总结模式
                - strict: 严格模式，只根据检索到的资料回答
                - supplement: 补充模式，可以结合资料库进行合理补充
        """
        # 构建上下文
        context_parts = []
        neo4jrag = search_results.get("neo4jrag", {}) or {}
        expert_nodes = neo4jrag.get("expert_nodes", []) if isinstance(neo4jrag, dict) else []
        expert_guidance_text = str(search_results.get("expert_guidance") or "").strip()
        has_expert_evidence = bool(expert_guidance_text or expert_nodes)

        context_parts.append(
            "【Evidence Priority】\n"
            "1) 事实证据: Opinion业务图谱命中\n"
            "2) 专家图谱: 仅用于任务拆解、方法选择、回答结构约束（非事实证据）\n"
            "严禁把专家图谱节点/指导文本当作事实依据。"
        )

        # Planning Context + Answer Structure（外挂层，仅影响总结提示词）
        retrieval_plan = search_results.get("retrieval_plan") or {}
        answer_structure = search_results.get("answer_structure") or {}
        if answer_structure.get("applied") and retrieval_plan:
            route_steps = retrieval_plan.get("route", {}).get("steps", []) or []
            route_text = []
            for step in route_steps:
                stage = str(step.get("stage") or "").strip()
                items = [str(x).strip() for x in (step.get("items") or []) if str(x).strip()]
                if stage and items:
                    route_text.append(f"- {stage}: {', '.join(items)}")
            context_parts.append(
                "【Planning Context】\n"
                f"- scenario: {', '.join(retrieval_plan.get('scenario', []) or [])}\n"
                f"- goals: {', '.join(retrieval_plan.get('goals', []) or [])}\n"
                f"- dimensions: {', '.join(retrieval_plan.get('dimensions', []) or [])}\n"
                f"- tasks: {', '.join(retrieval_plan.get('tasks', []) or [])}\n"
                f"- methods: {', '.join(retrieval_plan.get('methods', []) or [])}\n"
                f"{chr(10).join(route_text)}\n\n"
                "【Answer Template】\n"
                "请按以下结构组织回答：\n"
                "1) Task\n2) Method\n3) Evidence\n4) Conclusion/Gap"
            )

        # Neo4j Expert结果（主图谱来源）
        if expert_guidance_text:
            context_parts.append("\n【专家图谱指导（仅方向，不可作事实证据）】")
            context_parts.append(expert_guidance_text)

        if expert_nodes:
            context_parts.append("\n【Neo4j专家图谱命中（仅方向，不可作事实证据）】")
            for i, node in enumerate(expert_nodes, 1):
                name = node.get("entity_name") or "未知节点"
                labels = ",".join(node.get("labels") or [])
                text = str(node.get("text_content") or "")
                source = node.get("source_doc") or ""
                connections = node.get("connections") or []
                context_parts.append(f"\n命中{i}: {name} ({labels})")
                context_parts.append(f"内容: {text}")
                if source:
                    context_parts.append(f"来源: {source}")
                if connections:
                    conn = ", ".join([str(c.get("name") or "") for c in connections if c.get("name")])
                    if conn:
                        context_parts.append(f"关联: {conn}")

        # opinion业务图谱结果（finding-centric）
        opinion_graph = search_results.get("opinion_graph", {}) or {}
        graph_hits = opinion_graph.get("hits", []) if isinstance(opinion_graph, dict) else []
        if graph_hits:
            context_parts.append("\n【Opinion业务图谱 Finding 命中】")
            capped_hits = graph_hits[:6] if has_expert_evidence else graph_hits
            for i, hit in enumerate(capped_hits, 1):
                seed = hit.get("seed") or {}
                context_parts.append(
                    f"\n命中{i}: Finding={hit.get('finding_title') or hit.get('finding_id') or ''} "
                    f"score={hit.get('score', '')} seed={seed.get('label', '')}:{seed.get('node_id', '')} mode={seed.get('mode', '')}"
                )
                if hit.get("finding_statement"):
                    context_parts.append(f"结论: {str(hit.get('finding_statement') or '')}")
                if hit.get("topics"):
                    context_parts.append(f"Topics: {', '.join([str(x) for x in hit.get('topics', []) if x])}")
                if hit.get("platforms"):
                    context_parts.append(f"Platforms: {', '.join([str(x) for x in hit.get('platforms', []) if x])}")
                if hit.get("events"):
                    context_parts.append(f"Events: {', '.join([str(x) for x in hit.get('events', []) if x])}")
                if hit.get("claims"):
                    context_parts.append(f"Claims: {'; '.join([str(x) for x in hit.get('claims', []) if x])}")
                if hit.get("post_titles"):
                    context_parts.append(f"Posts: {'; '.join([str(x) for x in hit.get('post_titles', []) if x])}")
                if hit.get("recommendations"):
                    context_parts.append(f"Recommendations: {'; '.join([str(x) for x in hit.get('recommendations', []) if x])}")
                related = hit.get("related_findings") or []
                if related:
                    context_parts.append(
                        "Related: " + "; ".join([str(x.get("finding_title") or x.get("finding_id") or "") for x in related if isinstance(x, dict)])
                    )

        # GraphRAG结果（finding/evidence 统一口径）
        if 'graphrag' in search_results and search_results['graphrag']:
            graphrag = search_results['graphrag']
            findings = graphrag.get('findings', []) or []
            capability = graphrag.get('capability', {}) or {}
            evidence = graphrag.get('evidence', {}) or {}
            if capability:
                context_parts.append("\n【GraphRAG 状态】")
                context_parts.append(
                    f"mode={capability.get('mode', '')}; degraded={capability.get('is_degraded', False)}; summary={capability.get('summary', '')}"
                )
            if evidence:
                context_parts.append("\n【GraphRAG 证据统计】")
                context_parts.append(json.dumps(evidence, ensure_ascii=False))
            if findings:
                context_parts.append("\n【GraphRAG Finding 主结果】")
                for i, item in enumerate(findings[:6] if has_expert_evidence else findings, 1):
                    context_parts.append(f"\nFinding{i}: {item.get('finding_title') or item.get('finding_id') or ''}")
                    context_parts.append(f"Statement: {item.get('finding_statement') or ''}")
                    context_parts.append(
                        f"Scores: final={item.get('score', '')}, graph={item.get('graph_score', '')}, evidence={item.get('evidence_score', '')}"
                    )
                    if item.get('topics'):
                        context_parts.append(f"Topics: {', '.join([str(x) for x in item.get('topics', []) if x])}")
                    if item.get('events'):
                        context_parts.append(f"Events: {', '.join([str(x) for x in item.get('events', []) if x])}")
                    if item.get('claims'):
                        context_parts.append(f"Claims: {'; '.join([str(x) for x in item.get('claims', []) if x])}")
                    if item.get('post_titles'):
                        context_parts.append(f"Posts: {'; '.join([str(x) for x in item.get('post_titles', []) if x])}")
        
        # TagRAG结果
        if 'tagrag' in search_results and search_results['tagrag']:
            text_blocks = search_results['tagrag'].get('text_blocks', [])
            if text_blocks:
                context_parts.append("\n【相关文本块】")
                capped_blocks = text_blocks[:8] if has_expert_evidence else text_blocks
                for i, t in enumerate(capped_blocks, 1):
                    context_parts.append(f"\n文本块{i}:")
                    context_parts.append(f"标签: {t.get('text_tag', '')}")
                    context_parts.append(f"完整内容: {t.get('text', '')}")  # 使用完整text
                    context_parts.append(f"来源: {t.get('doc_name', '')} (文档ID:{t.get('doc_id', '')})")
        
        context = "\n".join(context_parts)
        
        # 根据模式选择不同的提示词
        if mode == "strict":
            prompt_template = self.prompts.get('result_summary_strict', {}).get('prompt', '')
            mode_text = "严格模式"
        else:  # supplement
            prompt_template = self.prompts.get('result_summary_supplement', {}).get('prompt', '')
            mode_text = "补充模式"
        
        if not prompt_template:
            log_error(self.logger, f"未找到{mode}模式的提示词配置", "llm")
            return ""
        
        prompt = prompt_template.format(query=query, context=context)
        
        summary = await self.call_api(prompt, max_tokens=3000)
        
        if summary:
            log_success(self.logger, f"资料整理完成：共 ({len(summary)}字)", "RouterRetrieve")
        else:
            log_error(self.logger, "资料整理失败", "RouterRetrieve")
        
        return summary
    
    async def extract_time_from_query(self, query: str) -> Dict[str, Any]:
        """从查询中提取时间标签"""
        # 从配置文件加载提示词
        prompt_template = self.prompts.get('time_extraction', {}).get('prompt', '')
        if not prompt_template:
            log_error(self.logger, "未找到time_extraction提示词配置", "llm")
            return {"has_time": False, "time_text": ""}
        
        prompt = prompt_template.format(query=query)
        response = await self.call_api(prompt)
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
            return {"has_time": False, "time_text": ""}
        except:
            return {"has_time": False, "time_text": ""}
    
    async def match_time_with_docs(self, query_time: str, doc_times: Dict[str, str]) -> List[str]:
        """匹配查询时间与文档时间范围"""
        doc_time_list = "\n".join([f"- ID={doc_id}: {time}" for doc_id, time in doc_times.items()])
        
        # 从配置文件加载提示词
        prompt_template = self.prompts.get('time_matching', {}).get('prompt', '')
        if not prompt_template:
            log_error(self.logger, "未找到time_matching提示词配置", "llm")
            return []
        
        prompt = prompt_template.format(query_time=query_time, doc_time_list=doc_time_list)
        response = await self.call_api(prompt)
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                matched = result.get("matched_doc_ids", [])
                matched = [str(doc_id).strip() for doc_id in matched]
                return matched
            return []
        except:
            return []
    
    async def expand_query(self, original_query: str) -> str:
        """查询扩展/重写：将用户查询扩展为更完整、更适合检索的查询
        
        Args:
            original_query: 原始用户查询
            
        Returns:
            str: 扩展后的查询文本
        """
        # 从配置文件加载提示词，如果没有则使用默认提示词
        prompt_template = self.prompts.get('query_expansion', {}).get('prompt', '')
        
        if not prompt_template:
            # 使用默认提示词
            prompt_template = """你是一个专业的查询扩展助手。请将用户查询扩展为更适合信息检索的查询文本。

要求：
1. 保持原查询的核心意图不变
2. 补充相关的同义词、近义词和相关概念
3. 将口语化表达转换为更规范的检索查询
4. 如果查询已经很完整，可以保持原样或稍作优化
5. 扩展后的查询应该更有利于在知识库中检索到相关信息

用户查询：{query}

请直接返回扩展后的查询文本，不要添加任何解释或说明。"""
        
        prompt = prompt_template.format(query=original_query)
        expanded_query = await self.call_api(prompt, max_tokens=500)
        
        if expanded_query:
            # 清理返回结果（去除可能的格式标记）
            expanded_query = expanded_query.strip()
            # 如果返回的是JSON格式，尝试提取
            try:
                json_match = re.search(r'\{.*\}', expanded_query, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                    expanded_query = result.get('expanded_query', expanded_query)
            except:
                pass
            
            log_success(self.logger, f"查询扩展完成: {original_query[:50]}... -> {expanded_query[:50]}...", "QueryExpansion")
            return expanded_query
        else:
            log_error(self.logger, "查询扩展失败，使用原始查询", "QueryExpansion")
            return original_query

class EmbeddingGenerator:
    """向量生成器"""
    
    def __init__(self, logger, model: str = None):
        from ..embedding import get_async_client
        self.logger = logger
        # 获取配置好的AsyncClient
        try:
            self.client, self.model_name, self.dimension = get_async_client()
            # 如果传入了model且不为空，优先使用传入的? 不，应该优先使用配置的。
            # 但为了兼容性，如果配置的model为空，使用传入的。
            # get_async_client已经保证model有值 (from config or default).
            
            # 记录使用的模型
            log_success(self.logger, f"Embedding模型: {self.model_name}", "RouterRAG")
        except Exception as e:
            log_error(self.logger, f"EmbeddingClient初始化失败: {e}", "Embedding")
            self.client = None
    
    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """生成单个向量"""
        if not self.client:
            return None
            
        from ..embedding import generate_embedding_async
        try:
            return await generate_embedding_async(self.client, text, self.model_name)
        except Exception as e:
            log_error(self.logger, f"向量生成失败: {str(e)}", "embedding")
            return None



class AdvancedRAGSearcher:
    """高级RAG检索系统 - 支持时间过滤、三种检索策略、多跳查询、多主题数据库"""
    
    def __init__(self, topic: str, logger, qwen_client: QwenClient, 
                 llm_model: str, embedding_model: str, prompts_file: str,
                 db_base_path: Optional[Path] = None):
        self.topic = topic
        self.logger = logger
        self.qwen_client = qwen_client
        
        # 根据主题确定数据库路径：{base}/{主题}数据库/vector_db
        if db_base_path is None:
            rag_base = Path(__file__).parent
            self.db_path = rag_base / f"{topic}数据库" / "vector_db"
        else:
            self.db_path = db_base_path / "vector_db"
        
        if not self.db_path.exists():
            log_error(self.logger, f"数据库不存在: {self.db_path}", "searcher")
            raise FileNotFoundError(f"数据库不存在: {self.db_path}")
        
        # 初始化辅助工具
        self.embedding_gen = EmbeddingGenerator(logger, embedding_model)
        self.llm_helper = LLMHelper(qwen_client, logger, llm_model, prompts_file)
        
        # 连接数据库
        self.db = lancedb.connect(str(self.db_path))
        
        # 缓存表
        self.tables = {}
        self._load_tables()
        
        # 加载文档时间映射
        self.doc_times = self._load_doc_times()
    
    def _load_tables(self) -> None:
        """加载所有表"""
        # GraphRAG 已统一走 Neo4j 业务图谱；这里仅保留
        # - normalrag: 句子检索
        # - graphrag_texts: TagRAG 文本块检索
        table_names = ["normalrag", "graphrag_texts"]
        for name in table_names:
            try:
                self.tables[name] = self.db.open_table(name)
                count = self.tables[name].count_rows()
                log_success(self.logger, f"载入表: {name} ({count}条)", "RouterRetrieve")
            except Exception as e:
                log_error(self.logger, f"无法加载表 {name}: {str(e)}", "searcher")
    
    def _load_doc_times(self) -> Dict[str, str]:
        """加载文档时间映射"""
        doc_times = {}
        try:
            texts_table = self.tables.get("graphrag_texts")
            if texts_table:
                df = texts_table.to_pandas()
                for _, row in df.iterrows():
                    doc_id = row['doc_id']
                    time = row['time']
                    if doc_id not in doc_times:
                        doc_times[doc_id] = time
                
        except Exception as e:
            log_error(self.logger, f"无法加载文档时间: {str(e)}", "searcher")
        
        return doc_times

    @staticmethod
    def _dedup_terms(values: List[Any], max_items: int = 8, max_len: int = 24) -> List[str]:
        terms: List[str] = []
        seen = set()
        for raw in values:
            token = str(raw or "").strip()
            if not token or len(token) > max_len:
                continue
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            terms.append(token)
            if len(terms) >= max_items:
                break
        return terms

    def _build_rewrite_terms(self, retrieval_plan: Dict[str, Any], hints: Dict[str, Any], max_items: int = 8) -> List[str]:
        candidates: List[Any] = []
        candidates.extend(retrieval_plan.get("tasks", []) or [])
        candidates.extend(retrieval_plan.get("methods", []) or [])
        candidates.extend(retrieval_plan.get("dimensions", []) or [])
        candidates.extend((hints or {}).get("keywords", []) or [])
        candidates.extend((hints or {}).get("time_terms", []) or [])
        return self._dedup_terms(candidates, max_items=max_items)

    @staticmethod
    def _hint_score(text: str, positive_terms: List[str], negative_terms: List[str]) -> float:
        if not text:
            return 0.0
        score = 0.0
        for token in positive_terms:
            if token and token in text:
                score += 0.08
        for token in negative_terms:
            if token and token in text:
                score -= 0.08
        if score > 0.30:
            return 0.30
        if score < -0.24:
            return -0.24
        return score

    def _rerank_items_by_hints(
        self,
        items: List[Dict[str, Any]],
        positive_terms: List[str],
        negative_terms: List[str],
        *,
        text_keys: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        if not items or (not positive_terms and not negative_terms):
            return items
        keys = text_keys or ["text", "description", "name", "source", "target", "text_tag"]
        scored: List[Tuple[float, int, Dict[str, Any]]] = []
        for idx, item in enumerate(items):
            merged_text_parts: List[str] = []
            for k in keys:
                val = item.get(k)
                if isinstance(val, str) and val:
                    merged_text_parts.append(val)
            merged_text = "\n".join(merged_text_parts)
            hint_score = self._hint_score(merged_text, positive_terms, negative_terms)
            clone = dict(item)
            if hint_score != 0.0:
                clone["expert_hint_score"] = round(hint_score, 4)
            scored.append((hint_score, idx, clone))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [x[2] for x in scored]
    
    async def _process_time_filter(self, query: str) -> TimeRange:
        """处理时间过滤"""
        
        # 1. 提取查询中的时间
        time_info = await self.llm_helper.extract_time_from_query(query)
        has_time = time_info.get("has_time", False)
        time_text = time_info.get("time_text", "")
        
        if not has_time:
            return TimeRange(has_time=False, time_text="", matched_docs=[])
        
        log_success(self.logger, f"查询包含时间范围: {time_text}", "RouterRetrieve")
        
        # 2. 与文档时间进行匹配
        if not self.doc_times:
            log_error(self.logger, "无文档时间信息，将进行全库检索", "time")
            return TimeRange(has_time=False, time_text=time_text, matched_docs=[])
        
        matched_doc_ids = await self.llm_helper.match_time_with_docs(time_text, self.doc_times)
        
        if not matched_doc_ids:
            return TimeRange(has_time=False, time_text=time_text, matched_docs=[])
        
        log_success(self.logger, f"文档匹配完成: {', '.join(matched_doc_ids)}", "RouterRetrieve")
        
        return TimeRange(has_time=True, time_text=time_text, matched_docs=matched_doc_ids)

    def _has_tagrag_table(self) -> bool:
        return bool(self.tables.get("graphrag_texts"))

    def _build_neo4j_graphrag(self, hits: List[Dict[str, Any]], topk: int) -> Dict[str, Any]:
        """将 Neo4j finding-centric 命中统一映射为 graphrag 输出结构。"""
        return GraphRAGFormatter().format(hits, topk)

    def _search_opinion_graph(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        return GraphRAGRetriever().retrieve(query, top_k)
    
    async def _normalrag_search(self, query_vec: List[float], time_range: TimeRange, 
                                topk: int) -> NormalRAGResult:
        """NormalRAG检索：句子向量检索，获取前5条"""
        
        sentence_table = self.tables.get("normalrag")
        if not sentence_table:
            log_error(self.logger, "表不存在", "normalrag")
            return NormalRAGResult(sentences=[])
        
        try:
            # 如果有时间过滤，先筛选全库样本
            if time_range.has_time and time_range.matched_docs:
                # 1. 从全库中筛选符合时间范围的句子
                sentences_df = sentence_table.to_pandas()
                time_filtered_sentences = sentences_df[
                    sentences_df['doc_id'].isin(time_range.matched_docs)
                ]
                total_sentences = len(sentences_df)
                filtered_count = len(time_filtered_sentences)
                                
                if filtered_count == 0:
                    log_error(self.logger, "  未找到符合时间范围的句子", "normalrag")
                    return NormalRAGResult(sentences=[])
                
                # 2. 在筛选后的样本上进行向量检索
                # 由于LanceDB不支持预过滤，需要获取所有结果然后手动筛选
                all_results = sentence_table.search(query_vec, vector_column_name="sentence_vec").limit(total_sentences).to_list()
                
                # 只保留符合时间范围的
                results = [s for s in all_results if s.get('doc_id', '') in time_range.matched_docs]
                
                # 按距离排序
                results = sorted(results, key=lambda x: x.get('_distance', 1.0))
                
            else:
                # 无时间过滤，正常检索
                results = sentence_table.search(query_vec, vector_column_name="sentence_vec").limit(topk * 2).to_list()
                results = sorted(results, key=lambda x: x.get('_distance', 1.0))
            
            # 获取前topk条
            results = results[:topk]
            
            sentences = []
            for i, s in enumerate(results, 1):
                distance = s.get('_distance', 0.0)
                sentences.append({
                    "sentence_id": s.get('sentence_id', ''),
                    "text": s['sentence_text'],
                    "doc_id": s['doc_id'],
                    "doc_name": s.get('doc_name', ''),
                    "score": round(distance, 4)
                })
            
            # 打印召回统计
            log_success(self.logger, f"[NormalRAG]召回: 句子数-{len(sentences)}", "RouterRetrieve")
            
            return NormalRAGResult(sentences=sentences)
            
        except Exception as e:
            log_error(self.logger, f"失败: {str(e)}", "normalrag")
            return NormalRAGResult(sentences=[])
    
    async def _tagrag_search(self, query_vec: List[float], time_range: TimeRange, 
                            topk: int) -> TagRAGResult:
        """TagRAG检索：文本标签向量检索，获取前5条"""
        
        texts_table = self.tables.get("graphrag_texts")
        if not texts_table:
            log_error(self.logger, "表不存在", "tagrag")
            return TagRAGResult(text_blocks=[])
        
        try:
            # 如果有时间过滤，先筛选全库样本
            if time_range.has_time and time_range.matched_docs:
                # 1. 从全库中筛选符合时间范围的文本块
                texts_df = texts_table.to_pandas()
                time_filtered_texts = texts_df[
                    texts_df['doc_id'].isin(time_range.matched_docs)
                ]
                total_texts = len(texts_df)
                filtered_count = len(time_filtered_texts)
                                
                if filtered_count == 0:
                    log_error(self.logger, "  未找到符合时间范围的文本块", "tagrag")
                    return TagRAGResult(text_blocks=[])
                
                # 2. 在筛选后的样本上进行向量检索
                # 由于LanceDB不支持预过滤，需要获取所有结果然后手动筛选
                all_results = texts_table.search(query_vec, vector_column_name="text_tag_vec").limit(total_texts).to_list()
                
                # 只保留符合时间范围的
                results = [t for t in all_results if t.get('doc_id', '') in time_range.matched_docs]
                
                # 按距离排序
                results = sorted(results, key=lambda x: x.get('_distance', 1.0))
                
            else:
                # 无时间过滤，正常检索
                results = texts_table.search(query_vec, vector_column_name="text_tag_vec").limit(topk * 2).to_list()
                results = sorted(results, key=lambda x: x.get('_distance', 1.0))
            
            # 获取前topk个
            results = results[:topk]
            
            text_blocks = []
            for i, t in enumerate(results, 1):
                distance = t.get('_distance', 0.0)
                text_blocks.append({
                    "text_id": t.get('text_id', ''),
                    "text": t['text'],
                    "text_tag": t.get('text_tag', ''),
                    "doc_id": t['doc_id'],
                    "doc_name": t.get('doc_name', ''),
                    "score": round(distance, 4)
                })
            
            # 打印召回统计
            log_success(self.logger, f"[TagRAG]召回: 文本块数-{len(text_blocks)}", "RouterRetrieve")
            
            return TagRAGResult(text_blocks=text_blocks)
            
        except Exception as e:
            log_error(self.logger, f"失败: {str(e)}", "tagrag")
            return TagRAGResult(text_blocks=[])
    
    async def search(self, params: SearchParams) -> Dict[str, Any]:
        """主检索函数"""
        original_query = params.query_text
        retrieval_plan: Dict[str, Any] = {}
        plan_trace: Dict[str, Any] = {}
        expert_guidance = ""
        expert_results: List[Dict[str, Any]] = []
        opinion_graph_hits: List[Dict[str, Any]] = []
        retrieval_hints = {"keywords": [], "exclude": [], "time_terms": []}
        expert_overlay = {"enabled": params.enable_expert_overlay, "status": "disabled", "error": ""}

        # 步骤0: Expert Overlay（非阻断）
        if params.enable_expert_overlay:
            try:
                from src.rag.retrievers.expert_retriever import ExpertRetriever

                expert_retriever = ExpertRetriever()
                # ExpertRetriever internally uses sync planner logic; run it in a worker
                # thread to avoid nested event-loop errors inside async search().
                expert_payload = await asyncio.to_thread(
                    expert_retriever.retrieve_guidance_payload,
                    original_query,
                )
                retrieval_plan = expert_payload.get("retrieval_plan") or {}
                plan_trace = expert_payload.get("plan_trace") or {}
                expert_guidance = str(expert_payload.get("expert_guidance") or "")
                expert_results = expert_payload.get("expert_results") or []
                retrieval_hints = retrieval_plan.get("retrieval_hints") or {"keywords": [], "exclude": [], "time_terms": []}
                retrieval_hints = {
                    "keywords": self._dedup_terms(retrieval_hints.get("keywords", []), max_items=20, max_len=24),
                    "exclude": self._dedup_terms(retrieval_hints.get("exclude", []), max_items=20, max_len=24),
                    "time_terms": self._dedup_terms(retrieval_hints.get("time_terms", []), max_items=20, max_len=24),
                }
                expert_overlay["status"] = "ok"
            except Exception as e:
                expert_overlay["status"] = "degraded"
                expert_overlay["error"] = str(e)
                log_error(self.logger, f"Expert overlay降级: {e}", "RouterRetrieve")

        # 步骤0.3: opinion业务图谱检索（独立于expert图谱，非阻断）
        opinion_graph_hits: List[Dict[str, Any]] = []
        try:
            opinion_graph_hits = await asyncio.to_thread(
                self._search_opinion_graph, original_query, params.topk_graphrag
            )
        except Exception as e:
            log_error(self.logger, f"Opinion图谱检索降级: {e}", "RouterRetrieve")

        # 步骤0.1: Expert Query Rewrite（追加，不替换）
        rewrite_terms: List[str] = []
        rewritten_query = original_query
        if params.enable_expert_overlay and params.enable_expert_rewrite:
            rewrite_terms = self._build_rewrite_terms(retrieval_plan, retrieval_hints, max_items=8)
            if rewrite_terms:
                rewritten_query = f"{original_query} {' '.join(rewrite_terms)}"
                log_success(self.logger, f"Expert Rewrite追加词: {', '.join(rewrite_terms)}", "RouterRetrieve")

        # 步骤0.2: 原有查询扩展（可选）
        if params.enable_query_expansion:
            expanded_query = await self.llm_helper.expand_query(rewritten_query)
            effective_query = expanded_query if expanded_query != rewritten_query else rewritten_query
            if effective_query != rewritten_query:
                log_success(self.logger, f"查询已扩展: {rewritten_query[:50]}... -> {effective_query[:50]}...", "RouterRetrieve")
        else:
            effective_query = rewritten_query
            log_success(self.logger, "查询扩展已禁用", "RouterRetrieve")
        
        # 步骤1: 时间过滤（使用原始查询，因为时间信息提取更准确）
        time_range = await self._process_time_filter(original_query)
        
        # 步骤2: 生成查询向量（使用扩展后的查询）
        query_vec = await self.embedding_gen.generate_embedding(effective_query)
        if not query_vec:
            log_error(self.logger, "查询向量生成失败", "search")
            return {"error": "查询向量生成失败"}
                
        # 步骤3: 根据模式执行检索
        results = {
            "query_topic": params.query_topic,
            "query_text": original_query,  # 保留原始查询用于展示
            "expanded_query": effective_query if effective_query != original_query else None,  # 扩展后的查询
            "search_mode": params.search_mode,
            "expert_overlay": expert_overlay,
            "query_rewrite": {
                "original": original_query,
                "effective": effective_query,
                "added_terms": rewrite_terms,
            },
            "retrieval_hints_used": retrieval_hints,
            "retrieval_plan": retrieval_plan,
            "plan_trace": plan_trace,
            "expert_guidance": expert_guidance,
            "neo4jrag": {
                "expert_nodes": expert_results,
            },
            "opinion_graph": {
                "hits": opinion_graph_hits,
            },
            "answer_structure": {
                "template": "Task -> Method -> Evidence -> Conclusion/Gap",
                "applied": bool(
                    params.enable_expert_overlay
                    and params.enable_expert_answer_structure
                    and retrieval_plan
                ),
            },
            "time_filter": {
                "has_time": time_range.has_time,
                "time_text": time_range.time_text,
                "matched_docs": time_range.matched_docs
            }
        }
        
        if params.search_mode == "mixed":
            # 统一口径：GraphRAG仅使用 Neo4j 图检索结果。
            results["graphrag"] = self._build_neo4j_graphrag(opinion_graph_hits, params.topk_graphrag)
            if self._has_tagrag_table():
                normalrag_result, tagrag_result = await asyncio.gather(
                    self._normalrag_search(query_vec, time_range, params.topk_normalrag),
                    self._tagrag_search(query_vec, time_range, params.topk_tagrag)
                )
                tag_blocks = tagrag_result.text_blocks
            else:
                normalrag_result = await self._normalrag_search(query_vec, time_range, params.topk_normalrag)
                tag_blocks = []
            results["normalrag"] = {
                "sentences": normalrag_result.sentences
            }
            results["tagrag"] = {
                "text_blocks": tag_blocks
            }
        
        elif params.search_mode == "graphrag":
            # 统一口径：GraphRAG仅使用 Neo4j 图检索结果。
            results["graphrag"] = self._build_neo4j_graphrag(opinion_graph_hits, params.topk_graphrag)
        
        elif params.search_mode == "normalrag":
            normalrag_result = await self._normalrag_search(query_vec, time_range, params.topk_normalrag)
            results["normalrag"] = {
                "sentences": normalrag_result.sentences
            }
        
        elif params.search_mode == "tagrag":
            if self._has_tagrag_table():
                tagrag_result = await self._tagrag_search(query_vec, time_range, params.topk_tagrag)
                tag_blocks = tagrag_result.text_blocks
            else:
                log_success(self.logger, "TagRAG未启用（缺少graphrag_texts表）", "RouterRetrieve")
                tag_blocks = []
            results["tagrag"] = {
                "text_blocks": tag_blocks
            }

        # 步骤3.1: Retrieval hints 轻量重排（仅内存排序，不改底层索引）
        if params.enable_expert_overlay and params.enable_expert_hints:
            positive_terms = self._dedup_terms(
                (retrieval_plan.get("tasks", []) or [])
                + (retrieval_plan.get("methods", []) or [])
                + (retrieval_hints.get("keywords", []) or []),
                max_items=32,
                max_len=24,
            )
            negative_terms = self._dedup_terms(
                retrieval_hints.get("exclude", []) or [],
                max_items=16,
                max_len=24,
            )
            if positive_terms or negative_terms:
                if "normalrag" in results and isinstance(results["normalrag"], dict):
                    sent = results["normalrag"].get("sentences", []) or []
                    results["normalrag"]["sentences"] = self._rerank_items_by_hints(
                        sent,
                        positive_terms,
                        negative_terms,
                        text_keys=["text", "doc_name"],
                    )
                if "tagrag" in results and isinstance(results["tagrag"], dict):
                    blocks = results["tagrag"].get("text_blocks", []) or []
                    results["tagrag"]["text_blocks"] = self._rerank_items_by_hints(
                        blocks,
                        positive_terms,
                        negative_terms,
                        text_keys=["text", "text_tag", "doc_name"],
                    )
                if "graphrag" in results and isinstance(results["graphrag"], dict):
                    findings = results["graphrag"].get("findings", []) or []
                    results["graphrag"]["findings"] = self._rerank_items_by_hints(
                        findings,
                        positive_terms,
                        negative_terms,
                        text_keys=[
                            "finding_title",
                            "finding_statement",
                            "topics",
                            "platforms",
                            "events",
                            "claims",
                            "post_titles",
                            "recommendations",
                        ],
                    )
                
        # 步骤4: 使用LLM整理检索结果（可选）
        if params.enable_llm_summary:
            # 使用原始查询进行结果整理，因为用户更关心原始查询的答案
            summary = await self.llm_helper.summarize_results(original_query, results, params.llm_summary_mode)
            
            if summary:
                results["llm_summary"] = summary
        
        # 根据return_format参数返回不同格式的结果
        if params.return_format == "llm_only":
            # 仅返回LLM整理结果
            if "llm_summary" in results:
                return {
                    "query_topic": params.query_topic,
                    "query_text": original_query,
                    "expanded_query": results.get("expanded_query"),
                    "llm_summary": results["llm_summary"]
                }
            else:
                log_error(self.logger, "return_format=llm_only但未启用LLM整理，返回空结果", "return")
                return {
                    "query_topic": params.query_topic,
                    "query_text": original_query,
                    "expanded_query": results.get("expanded_query"),
                    "llm_summary": "未启用LLM整理，无法返回LLM结果"
                }
        
        elif params.return_format == "index_only":
            # 仅返回索引检索结果（移除llm_summary）
            filtered_results = {k: v for k, v in results.items() if k != "llm_summary"}
            filtered_results["return_format"] = "index_only"
            return filtered_results
        
        else:  # both (默认)
            # 返回完整结果（索引结果 + LLM整理）
            results["return_format"] = "both"
        return results
    

def router_retrieve(
    topic: str,
    query: str,
    mode: str = "mixed",
    topk_graphrag: int = 3,
    topk_normalrag: int = 5,
    topk_tagrag: int = 5,
    enable_query_expansion: bool = True,
    enable_llm_summary: bool = True,
    llm_summary_mode: str = "strict",
    return_format: str = "both",
    enable_expert_overlay: bool = True,
    enable_expert_rewrite: bool = True,
    enable_expert_hints: bool = True,
    enable_expert_answer_structure: bool = True,
    question_type: Optional[str] = None,
    experiment_tag: str = "default",
    trace_id: Optional[str] = None,
    use_question_preset: bool = True,
    db_base_path: Optional[Path] = None
) -> Dict[str, Any]:
    """
    RAG检索包装函数，返回JSON格式的检索结果
    
    Args:
        topic: 主题名称
        query: 查询文本
        mode: 检索模式 (mixed/graphrag/normalrag/tagrag)
        topk_graphrag: GraphRAG返回的核心实体数量
        topk_normalrag: NormalRAG返回的句子数量
        topk_tagrag: TagRAG返回的文本块数量
        enable_query_expansion: 是否启用查询扩展/重写（默认True）
        enable_llm_summary: 是否启用LLM整理结果
        llm_summary_mode: LLM整理模式 (strict/supplement)
        return_format: 返回格式 (both/llm_only/index_only)
    """
    try:
        # 引入logger（使用主题和当前日期）
        current_date = datetime.now().strftime("%Y-%m-%d")
        logger = setup_logger(f"RagRouter_{topic}", current_date)

        log_module_start(logger, "RouterRetrieve", f"正在进行Router检索 - 主题: {topic}")

        # 加载LLM配置
        llm_config = settings.get_llm_config()
        
        # 获取router_retrieve配置
        router_config = llm_config.get('router_retrieve_llm', {})
        embedding_config = llm_config.get('embedding_llm', {})
        
        llm_model = router_config.get('model', 'qwen-plus')
        embedding_model = embedding_config.get('model', 'text-embedding-v4')
        
        # 创建QwenClient
        qwen_client = QwenClient()

        resolved_question_type = (question_type or "").strip().lower() or detect_question_type(query)
        if resolved_question_type not in QUESTION_TYPE_PRESETS:
            resolved_question_type = "explore"
        preset = QUESTION_TYPE_PRESETS.get(resolved_question_type, {})
        applied_preset: Dict[str, Any] = {}

        if use_question_preset and preset:
            mode = str(preset.get("mode", mode))
            topk_graphrag = int(preset.get("topk_graphrag", topk_graphrag))
            topk_normalrag = int(preset.get("topk_normalrag", topk_normalrag))
            topk_tagrag = int(preset.get("topk_tagrag", topk_tagrag))
            llm_summary_mode = str(preset.get("llm_summary_mode", llm_summary_mode))
            enable_expert_overlay = bool(preset.get("enable_expert_overlay", enable_expert_overlay))
            enable_expert_rewrite = bool(preset.get("enable_expert_rewrite", enable_expert_rewrite))
            enable_expert_hints = bool(preset.get("enable_expert_hints", enable_expert_hints))
            enable_expert_answer_structure = bool(
                preset.get("enable_expert_answer_structure", enable_expert_answer_structure)
            )
            applied_preset = dict(preset)
        
        # 提示词文件由topic自动确定
        prompts_file = f"{topic}.yaml"
        
        # 创建检索器
        searcher = AdvancedRAGSearcher(
            topic=topic,
            logger=logger,
            qwen_client=qwen_client,
            llm_model=llm_model,
            embedding_model=embedding_model,
            prompts_file=prompts_file,
            db_base_path=db_base_path
        )
        
        # 设置检索参数
        params = SearchParams(
            query_topic=topic,
            query_text=query,
            search_mode=mode,
            topk_graphrag=topk_graphrag,
            topk_normalrag=topk_normalrag,
            topk_tagrag=topk_tagrag,
            enable_query_expansion=enable_query_expansion,
            enable_llm_summary=enable_llm_summary,
            llm_summary_mode=llm_summary_mode,
            return_format=return_format,
            enable_expert_overlay=enable_expert_overlay,
            enable_expert_rewrite=enable_expert_rewrite,
            enable_expert_hints=enable_expert_hints,
            enable_expert_answer_structure=enable_expert_answer_structure,
        )
        
        
        # 执行检索（需要使用asyncio运行）
        results = asyncio.run(searcher.search(params))
        if isinstance(results, dict):
            results["question_type"] = resolved_question_type
            results["experiment_tag"] = str(experiment_tag or "default")
            results["trace_id"] = trace_id or uuid.uuid4().hex
            results["preset_applied"] = bool(use_question_preset and applied_preset)
            if applied_preset:
                results["preset_config"] = applied_preset
        
        return results
        
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def retrieve_documents(
    query: str,
    topic: str,
    top_k: int = 10,
    threshold: float = 0.0,
    mode: str = "normalrag",
    enable_expert_overlay: bool = True,
    enable_expert_rewrite: bool = True,
    enable_expert_hints: bool = True,
    enable_expert_answer_structure: bool = True,
    question_type: Optional[str] = None,
    experiment_tag: str = "default",
    trace_id: Optional[str] = None,
    use_question_preset: bool = True,
    db_base_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Adapter for API usage. Normalizes RouterRAG results into a dictionary with
    `results` (flat list) and optional `summary`.
    """
    # 获取全局RAG配置中的功能开关
    from ...setting.settings import settings
    rag_config = settings.get("rag", {}) or {}
    retrieval_config = rag_config.get("retrieval", {})
    
    enable_qe = retrieval_config.get("enable_query_expansion", True)
    enable_sum = retrieval_config.get("enable_llm_summary", True)
    sum_mode = retrieval_config.get("llm_summary_mode", "strict")

    payload = router_retrieve(
        topic=topic,
        query=query,
        mode=mode,
        topk_normalrag=top_k,
        topk_tagrag=top_k,
        enable_query_expansion=enable_qe,
        enable_llm_summary=enable_sum,
        llm_summary_mode=sum_mode,
        return_format="both",
        enable_expert_overlay=enable_expert_overlay,
        enable_expert_rewrite=enable_expert_rewrite,
        enable_expert_hints=enable_expert_hints,
        enable_expert_answer_structure=enable_expert_answer_structure,
        question_type=question_type,
        experiment_tag=experiment_tag,
        trace_id=trace_id,
        use_question_preset=use_question_preset,
        db_base_path=db_base_path,
    )

    if not isinstance(payload, dict):
        return {"results": [], "total": 0}

    results: List[Dict[str, Any]] = []
    summary = payload.get("llm_summary", "")
    debug_fields = {
        "trace_id": payload.get("trace_id", ""),
        "experiment_tag": payload.get("experiment_tag", "default"),
        "question_type": payload.get("question_type", question_type or ""),
        "preset_applied": payload.get("preset_applied", False),
        "preset_config": payload.get("preset_config", {}),
        "expert_overlay": payload.get("expert_overlay", {}),
        "query_rewrite": payload.get("query_rewrite", {}),
        "retrieval_hints_used": payload.get("retrieval_hints_used", {}),
        "retrieval_plan": payload.get("retrieval_plan", {}),
        "plan_trace": payload.get("plan_trace", {}),
        "answer_structure": payload.get("answer_structure", {}),
        "expert_guidance": payload.get("expert_guidance", ""),
    }

    if mode == "tagrag":
        items = payload.get("tagrag", {}).get("text_blocks", [])
        raw_total = len(items)
        for item in items:
            distance = float(item.get("score", 1.0))
            similarity = max(0.0, 1.0 - distance)
            if similarity < threshold:
                continue
            results.append({
                "id": item.get("text_id") or item.get("doc_id"),
                "text": item.get("text", ""),
                "score": round(similarity, 4),
                "metadata": {
                    "doc_id": item.get("doc_id"),
                    "doc_name": item.get("doc_name"),
                    "text_tag": item.get("text_tag"),
                },
            })
        return {"results": results, "total": len(results), "raw_total": raw_total, "summary": summary, **debug_fields}

    elif mode == "graphrag" or mode == "mixed":
        graphrag_data = payload.get("graphrag", {})

        findings = graphrag_data.get("findings", []) or []
        capability = graphrag_data.get("capability", {}) or {}
        evidence = graphrag_data.get("evidence", {}) or {}

        for item in findings:
            text_parts = [
                f"【Finding】{item.get('finding_title') or item.get('finding_id') or ''}",
                str(item.get("finding_statement") or "").strip(),
            ]
            if item.get("topics"):
                text_parts.append("Topics: " + ", ".join([str(x) for x in item.get("topics", []) if x]))
            if item.get("platforms"):
                text_parts.append("Platforms: " + ", ".join([str(x) for x in item.get("platforms", []) if x]))
            if item.get("events"):
                text_parts.append("Events: " + ", ".join([str(x) for x in item.get("events", []) if x]))
            if item.get("claims"):
                text_parts.append("Claims: " + "; ".join([str(x) for x in item.get("claims", []) if x]))
            if item.get("post_titles"):
                text_parts.append("Posts: " + "; ".join([str(x) for x in item.get("post_titles", []) if x]))
            if item.get("recommendations"):
                text_parts.append("Recommendations: " + "; ".join([str(x) for x in item.get("recommendations", []) if x]))
            related = item.get("related_findings") or []
            if related:
                text_parts.append(
                    "Related: " + "; ".join(
                        [str(x.get("finding_title") or x.get("finding_id") or "") for x in related if isinstance(x, dict)]
                    )
                )

            finding_score = float(item.get("score", 0.0) or 0.0)
            results.append({
                "id": item.get("finding_id") or item.get("finding_title"),
                "text": "\n".join([part for part in text_parts if part]),
                "score": round(finding_score, 4),
                "metadata": {
                    "type": "finding",
                    "topics": item.get("topics", []) or [],
                    "platforms": item.get("platforms", []) or [],
                    "events": item.get("events", []) or [],
                    "claim_ids": item.get("claim_ids", []) or [],
                    "chunk_ids": item.get("chunk_ids", []) or [],
                    "post_ids": item.get("post_ids", []) or [],
                    "recommendations": item.get("recommendations", []) or [],
                    "seed": item.get("seed", {}) or {},
                    "graph_score": item.get("graph_score"),
                    "evidence_score": item.get("evidence_score"),
                },
            })

        if capability:
            results.append({
                "id": "graphrag_capability",
                "text": f"【GraphRAG状态】mode={capability.get('mode', '')}; degraded={capability.get('is_degraded', False)}; summary={capability.get('summary', '')}",
                "score": 1.0,
                "metadata": {
                    "type": "graphrag_capability",
                    **capability,
                },
            })

        if evidence:
            results.append({
                "id": "graphrag_evidence",
                "text": "【GraphRAG证据统计】" + json.dumps(evidence, ensure_ascii=False),
                "score": 0.99,
                "metadata": {
                    "type": "graphrag_evidence",
                    **evidence,
                },
            })

        if mode == "graphrag":
            return {"results": results, "total": len(results), "raw_total": len(findings), "summary": summary, **debug_fields}

    # Default: normalrag (or mixed part 2)
    items = payload.get("normalrag", {}).get("sentences", [])
    raw_total = len(items)
    for item in items:
        distance = float(item.get("score", 1.0))
        similarity = max(0.0, 1.0 - distance)
        if similarity < threshold:
            continue
        results.append({
            "id": item.get("sentence_id") or item.get("doc_id"),
            "text": item.get("text", ""),
            "score": round(similarity, 4),
            "metadata": {
                "doc_id": item.get("doc_id"),
                "doc_name": item.get("doc_name"),
            },
        })

    return {"results": results, "total": len(results), "raw_total": raw_total, "summary": summary, **debug_fields}
