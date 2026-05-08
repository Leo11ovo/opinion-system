"""
实体抽取：粗提 NER（可接 HanLP/BERT）+ Topic 从 MySQL classification 或 BERTopic 映射。
首期：Topic 从 classification 建节点与 (Post)-[:ABOUT_TOPIC]->(Topic)；Entity 粗提可插 NER，默认占位。
"""
from __future__ import annotations

import logging
import json
from typing import Any, Dict, List, Optional, Tuple

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from ..utils.setting.env_loader import get_api_key
from .neo4j_client import get_driver, get_session

LOG = logging.getLogger(__name__)


def _post_global_id(topic: str, channel: str, row_id: str) -> str:
    """Duplicate of sync_to_neo4j._post_global_id to avoid circular import."""
    return f"{topic}_{channel}_{row_id}"


def extract_with_llm(text: str) -> Dict[str, Any]:
    """
    使用 LLM 提取实体和观点。
    返回: {"entities": [(name, type), ...], "claims": [claim_text, ...]}
    """
    if not text or not str(text).strip():
        return {"entities": [], "claims": []}

    api_key = get_api_key()
    if not api_key or OpenAI is None:
        LOG.warning("LLM API Key not found or OpenAI package missing, skipping LLM extraction.")
        return {"entities": [], "claims": []}

    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

        prompt = f"""
请分析以下文本，提取其中的关键实体和核心观点。

文本内容：
{text[:3000]}

请严格按照以下 JSON 格式输出：
{{
    "entities": [["实体名称", "实体类型(如: 人物, 地点, 组织, 事件, 产品, 其他)"], ...],
    "claims": ["观点1", "观点2", ...]
}}
注意：
1. 实体类型请尽量规范。
2. 观点应简洁明了，概括文本中的主要论断或意见。
3. 仅输出 JSON，不要包含其他解释。
"""

        completion = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {'role': 'system', 'content': '你是一个专业的信息抽取助手，擅长从文本中提取实体和观点。'},
                {'role': 'user', 'content': prompt}
            ],
            response_format={"type": "json_object"}
        )
        content = completion.choices[0].message.content
        data = json.loads(content)
        
        raw_entities = data.get("entities", [])
        entities = []
        for e in raw_entities:
            if isinstance(e, list) and len(e) >= 2:
                entities.append((str(e[0]), str(e[1])))
        
        claims = [str(c) for c in data.get("claims", []) if c]
        
        return {"entities": entities, "claims": claims}

    except Exception as e:
        LOG.error(f"LLM extraction failed: {e}")
        return {"entities": [], "claims": []}


def extract_entities_naive(text: str) -> List[Tuple[str, str]]:
    """
    轻量级实体抽取占位：首期不依赖 HanLP/BERT，返回空列表。
    后续可接入 HanLP 或 BERT NER，返回 [(name, type), ...]，如 ("张三", "PERSON"), ("北京", "LOC")。
    """
    if not text or not str(text).strip():
        return []
    # 占位：不做 NER，避免新增依赖；后续可替换为 HanLP/BERT 调用
    return []


def _write_entities_for_chunk(
    topic: str,
    channel: str,
    post_id_raw: str,
    chunk_index: int,
    entities: List[Tuple[str, str]],
) -> int:
    """
    Internal helper to write entities to Neo4j for a specific Chunk.
    Writes: (Chunk)-[:MENTIONS]->(Entity) AND (Post)-[:MENTIONS]->(Entity) (Aggregated)
    """
    if not entities:
        return 0
    
    post_global_id = _post_global_id(topic, channel, str(post_id_raw).strip())
    chunk_id = f"{post_global_id}_chunk_{chunk_index}"
    seen: set = set()
    
    with get_session() as session:
        with session.begin_transaction() as tx:
            for name, etype in entities:
                if not name or not str(name).strip():
                    continue
                name = str(name).strip()
                etype = str(etype or "OTHER").strip() or "OTHER"
                key = (name, etype)
                if key in seen:
                    continue
                seen.add(key)
                entity_id = f"{topic}_{name}_{etype}"
                
                # MERGE Entity
                tx.run(
                    """
                    MERGE (e:Entity {id: $id})
                    SET e.name = $name, e.type = $type, e.topic = $topic
                    """,
                    {"id": entity_id, "name": name, "type": etype, "topic": topic},
                )
                
                # 1. Chunk -> Entity
                tx.run(
                    """
                    MATCH (c:Chunk {id: $cid}), (e:Entity {id: $eid})
                    MERGE (c)-[:MENTIONS]->(e)
                    """,
                    {"cid": chunk_id, "eid": entity_id},
                )
                
                # 2. Post -> Entity (Aggregation for compatibility)
                tx.run(
                    """
                    MATCH (p:Post {id: $pid}), (e:Entity {id: $eid})
                    MERGE (p)-[:MENTIONS]->(e)
                    """,
                    {"pid": post_global_id, "eid": entity_id},
                )
    return len(seen)

def _write_claims_for_chunk(
    topic: str,
    channel: str,
    post_id_raw: str,
    chunk_index: int,
    claims: List[str],
) -> int:
    """
    Internal helper to write claims to Neo4j for a specific Chunk.
    Writes: (Chunk)-[:HAS_CLAIM]->(Claim) AND (Post)-[:HAS_CLAIM]->(Claim) (Aggregated)
    """
    if not claims:
        return 0

    post_global_id = _post_global_id(topic, channel, str(post_id_raw).strip())
    chunk_id = f"{post_global_id}_chunk_{chunk_index}"
    count = 0
    
    with get_session() as session:
        with session.begin_transaction() as tx:
            for claim_text in claims:
                if not claim_text or not str(claim_text).strip():
                    continue
                
                import hashlib
                claim_hash = hashlib.md5(claim_text.encode("utf-8")).hexdigest()
                claim_id = f"{topic}_claim_{claim_hash}"
                
                try:
                    # MERGE Claim
                    tx.run(
                        """
                        MERGE (c:Claim {id: $id})
                        SET c.content = $content, c.topic = $topic
                        """,
                        {"id": claim_id, "content": claim_text, "topic": topic}
                    )
                    
                    # 1. Chunk -> Claim
                    tx.run(
                        """
                        MATCH (c:Chunk {id: $cid}), (cl:Claim {id: $clid})
                        MERGE (c)-[:HAS_CLAIM]->(cl)
                        """,
                        {"cid": chunk_id, "clid": claim_id}
                    )
                    
                    # 2. Post -> Claim (Aggregation)
                    tx.run(
                        """
                        MATCH (p:Post {id: $pid}), (cl:Claim {id: $clid})
                        MERGE (p)-[:HAS_CLAIM]->(cl)
                        """,
                        {"pid": post_global_id, "clid": claim_id}
                    )
                    count += 1
                except Exception as e:
                    LOG.warning(f"Failed to write claim: {e}")
                
    return count


def _load_chunks_for_post(topic: str, channel: str, post_id_raw: str) -> List[Tuple[str, int]]:
    """
    优先读取已落库的 Chunk，确保抽取阶段与图谱中的 chunk_id 完全一致。
    返回: [(chunk_text, chunk_index), ...]
    """
    post_global_id = _post_global_id(topic, channel, str(post_id_raw).strip())
    rows: List[Tuple[str, int]] = []
    try:
        with get_session() as session:
            result = session.run(
                """
                MATCH (p:Post {id: $pid})-[:HAS_CHUNK]->(c:Chunk)
                RETURN c.chunk_index AS chunk_index, c.text AS text
                ORDER BY c.chunk_index ASC
                """,
                {"pid": post_global_id},
            )
            for r in result:
                text = str(r.get("text") or "").strip()
                idx_raw = r.get("chunk_index")
                if not text:
                    continue
                try:
                    idx = int(idx_raw)
                except Exception:
                    continue
                rows.append((text, idx))
    except Exception as e:
        LOG.warning("Load chunks for post failed: %s", e)
    return rows


def run_entity_extraction_for_sync(
    topic: str,
    channel: str,
    rows: List[Dict[str, Any]],
    *,
    extract_fn: Optional[Any] = None,
    enable_llm: bool = False,
    pre_fetched_llm_result: Optional[Dict[str, Any]] = None,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> Tuple[int, int]:
    """
    对一批 Post 行执行：Chunk 切分 + LLM 抽取 (Entity/Claim) + 写入 (Chunk粒度)。
    Pre-requisite: Chunks must be created via run_chunk_embedding_for_sync BEFORE calling this.
    """
    mentions = 0
    topics = 0
    
    # Import chunker here to avoid circular imports if placed at top
    from ..rag.core.chunker import ChunkConfig, TextChunker
    chunker = TextChunker(config=ChunkConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap))

    for row in rows:
        post_id = row.get("id")
        contents = row.get("contents") or ""
        if post_id is None or not str(post_id).strip():
            continue
            
        # 1) 优先读取 Neo4j 中已存在的 Chunk，保证 chunk_id 一致。
        # 2) 若缺失，再用同参数重切作为兜底（并提示日志）。
        chunks = _load_chunks_for_post(topic, channel, str(post_id))
        if not chunks:
            chunks = chunker.chunk_by_size(str(contents).strip())
            if chunks:
                LOG.warning(
                    "No persisted chunks for post %s; using fallback rechunk with size=%s overlap=%s",
                    post_id,
                    chunk_size,
                    chunk_overlap,
                )
        
        if enable_llm:
            for chunk_text, chunk_index in chunks:
                try:
                    # LLM 抽取实体和观点 (Per Chunk)
                    # Note: pre_fetched_llm_result is not supported for chunk-level yet
                    res = extract_with_llm(chunk_text)
                    
                    ents = res.get("entities", [])
                    claims = res.get("claims", [])
                    
                    # 写入实体 (Chunk Level)
                    mentions += _write_entities_for_chunk(topic, channel, str(post_id), chunk_index, ents)
                    
                    # 写入观点 (Chunk Level)
                    _write_claims_for_chunk(topic, channel, str(post_id), chunk_index, claims)
                    
                except Exception as e:
                    LOG.warning(f"LLM extraction failed for post {post_id} chunk {chunk_index}: {e}")
        else:
            local_extract_fn = extract_fn or extract_entities_naive
            for chunk_text, chunk_index in chunks:
                try:
                    ents = local_extract_fn(chunk_text) or []
                    mentions += _write_entities_for_chunk(topic, channel, str(post_id), chunk_index, ents)
                except Exception as e:
                    LOG.warning(f"Naive extraction failed for post {post_id} chunk {chunk_index}: {e}")
            
    return mentions, topics
