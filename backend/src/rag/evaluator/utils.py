"""
RAG 评估工具：关键词相关文档、检索指标、LLM Judge。
"""
import asyncio
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import lancedb
import yaml


def _get_router_db_path(topic: str) -> Path:
    """获取 RouterRAG 主题对应的 vector_db 路径。"""
    base = Path(__file__).resolve().parent
    # evaluator -> rag -> src (backend/src)
    for _ in range(2):
        base = base.parent
    ragrouter = base / "utils" / "rag" / "ragrouter"
    return ragrouter / f"{topic}数据库" / "vector_db"


def _normalize_doc_id(x: Any) -> str:
    """
    将 doc_id 规范化为字符串，保证 Router 返回的 int/float 与 LanceDB 读出的类型一致。
    例如 1、1.0、"1" 均变为 "1"。
    """
    if x is None:
        return ""
    s = str(x).strip()
    if not s:
        return ""
    try:
        n = float(s)
        if n == int(n):
            return str(int(n))
        return s
    except (ValueError, TypeError):
        return s


def load_corpus_doc_texts(topic: str) -> Dict[str, str]:
    """
    加载主题下所有文档的 doc_id -> 拼接文本。
    使用 graphrag_texts 表（含 doc_id, text），同一 doc_id 多行拼接。
    """
    db_path = _get_router_db_path(topic)
    if not db_path.exists():
        return {}
    doc_texts: Dict[str, List[str]] = {}
    try:
        db = lancedb.connect(str(db_path))
        for tname in ("graphrag_texts", "normalrag"):
            try:
                tbl = db.open_table(tname)
            except Exception:
                continue
            df = tbl.to_pandas()
            text_col = "text" if "text" in df.columns else "sentence_text"
            id_col = "doc_id"
            if id_col not in df.columns:
                continue
            for _, row in df.iterrows():
                doc_id = _normalize_doc_id(row.get(id_col))
                if not doc_id:
                    continue
                text = row.get(text_col, "")
                if isinstance(text, str) and text:
                    doc_texts.setdefault(doc_id, []).append(text)
    except Exception:
        return {}
    return {doc_id: " ".join(parts) for doc_id, parts in doc_texts.items()}


def _text_to_match_phrases(text: str, ngram_size: int = 2, min_len: int = 2) -> List[str]:
    """
    将中文/混合文本切成可匹配的短语：先按空白分词，长度>=min_len 的保留；
    再对每个片段按 ngram_size 字切 n-gram，用于在语料中匹配。
    避免整句过长导致子串匹配不到、中文无空格导致按空格分词失效。
    """
    text = (text or "").strip()
    if not text:
        return []
    # 先按空白拆成片段（英文/数字会分开，中文整段保留）
    parts = [p for p in re.split(r"\s+", text) if len(p) >= min_len]
    phrases: List[str] = []
    for p in parts:
        if len(p) <= ngram_size:
            phrases.append(p)
        else:
            for i in range(len(p) - ngram_size + 1):
                phrases.append(p[i : i + ngram_size])
    return list(dict.fromkeys(phrases))


def find_relevant_docs_by_keywords(
    topic: str,
    text: str,
    *,
    keyword_source: str = "query",
    min_keyword_len: int = 1,
    use_substring: bool = True,
    ngram_size: int = 2,
) -> List[str]:
    """
    根据文本中的关键词在主题语料中匹配相关文档 ID。

    Args:
        topic: RouterRAG 主题名。
        text: 用于抽取/匹配的文本（如问题 Q 或标准答案 A_gold）。
        keyword_source: 保留参数，兼容 "query" / "answer"。
        min_keyword_len: 关键词最小长度（字符）。
        use_substring: True 时先用整段做子串匹配，若无结果则用 n-gram 短语匹配（适合中文）。
        ngram_size: 短语长度（字），用于中文 n-gram 匹配。

    Returns:
        相关文档 doc_id 列表（去重）。
    """
    corpus = load_corpus_doc_texts(topic)
    if not corpus or not (text and text.strip()):
        return []
    text = text.strip()
    relevant: List[str] = []

    if use_substring:
        for doc_id, content in corpus.items():
            if text in content or content in text:
                relevant.append(doc_id)
        if not relevant:
            phrases = _text_to_match_phrases(text, ngram_size=ngram_size, min_len=min_keyword_len)
            phrases = [p for p in phrases if len(p) >= min_keyword_len]
            if phrases:
                for doc_id, content in corpus.items():
                    if any(p in content for p in phrases):
                        relevant.append(doc_id)
    else:
        words = [w for w in re.split(r"\s+", text) if len(w) >= min_keyword_len]
        words = list(dict.fromkeys(words))
        for doc_id, content in corpus.items():
            if any(w in content for w in words):
                relevant.append(doc_id)
    return list(dict.fromkeys(relevant))


def extract_retrieved_doc_ids(router_result: Dict[str, Any]) -> Set[str]:
    """
    从 RouterRAG 检索结果（index_only 或 both）中提取所有 doc_id。
    包含 normalrag.sentences、tagrag.text_blocks、graphrag 中实体的 doc_ids。
    使用 _normalize_doc_id 保证与相关文档集合的 doc_id 格式一致（避免 int/str 导致交为空）。
    """
    doc_ids: Set[str] = set()
    if not router_result or router_result.get("status") == "error":
        return doc_ids

    def add(did: Any) -> None:
        n = _normalize_doc_id(did)
        if n:
            doc_ids.add(n)

    # normalrag
    nr = router_result.get("normalrag") or {}
    for s in nr.get("sentences", []):
        add(s.get("doc_id"))

    # tagrag
    tr = router_result.get("tagrag") or {}
    for t in tr.get("text_blocks", []):
        add(t.get("doc_id"))

    # graphrag findings
    gr = router_result.get("graphrag") or {}
    for finding in gr.get("findings", []) or []:
        for raw in (finding.get("doc_ids") or []):
            add(raw)
        for raw in (finding.get("post_ids") or []):
            add(raw)

    # graphrag entities (legacy structure)
    entities = gr.get("entities") or {}
    for key in ("core", "extended"):
        for e in (entities.get(key) if isinstance(entities, dict) else []) or []:
            raw = e.get("doc_ids")
            if isinstance(raw, list):
                for did in raw:
                    add(did)
            elif isinstance(raw, str):
                try:
                    for did in json.loads(raw):
                        add(did)
                except Exception:
                    add(raw)

    return doc_ids


def compute_precision_recall(
    retrieved: Set[str], relevant: Set[str]
) -> Tuple[float, float]:
    """
    计算检索精确度与召回率。
    Precision = |retrieved ∩ relevant| / |retrieved|（无检索结果时为 0）
    Recall = |retrieved ∩ relevant| / |relevant|（无相关文档时为 0）
    使用 _normalize_doc_id 保证两边 doc_id 格式一致。
    """
    retrieved = set(_normalize_doc_id(x) for x in retrieved if x is not None) - {""}
    relevant = set(_normalize_doc_id(x) for x in relevant if x is not None) - {""}
    intersection = retrieved & relevant
    precision = len(intersection) / len(retrieved) if retrieved else 0.0
    recall = len(intersection) / len(relevant) if relevant else 0.0
    return round(precision, 4), round(recall, 4)


@dataclass
class RetrievedEvidenceItem:
    """统一证据表示，便于跨 retriever 评估。"""

    source: str
    doc_id: str
    rank: int
    text: str
    evidence_id: str
    meta: Dict[str, Any]


def _stringify_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return " ".join(str(x).strip() for x in value if str(x).strip())
    return str(value).strip()


def extract_retrieved_evidence_items(router_result: Dict[str, Any]) -> List[RetrievedEvidenceItem]:
    """
    从 RouterRAG 返回中提取统一证据项，用于 Top-k/MRR/nDCG/coverage/attribution 评估。
    """
    items: List[RetrievedEvidenceItem] = []
    if not router_result or router_result.get("status") == "error":
        return items

    rank = 1
    for source_name, payload_key in (("normalrag", "normalrag"), ("tagrag", "tagrag"), ("graphrag", "graphrag")):
        payload = router_result.get(payload_key) or {}
        if source_name == "normalrag":
            for row in payload.get("sentences", []) or []:
                doc_id = _normalize_doc_id(row.get("doc_id"))
                items.append(
                    RetrievedEvidenceItem(
                        source=source_name,
                        doc_id=doc_id,
                        rank=rank,
                        text=_stringify_text(row.get("text") or row.get("sentence_text")),
                        evidence_id=str(row.get("text_id") or row.get("id") or f"{source_name}_{rank}"),
                        meta=dict(row),
                    )
                )
                rank += 1
        elif source_name == "tagrag":
            for row in payload.get("text_blocks", []) or []:
                doc_id = _normalize_doc_id(row.get("doc_id"))
                items.append(
                    RetrievedEvidenceItem(
                        source=source_name,
                        doc_id=doc_id,
                        rank=rank,
                        text=_stringify_text(row.get("text")),
                        evidence_id=str(row.get("text_id") or row.get("id") or f"{source_name}_{rank}"),
                        meta=dict(row),
                    )
                )
                rank += 1
        else:
            findings = payload.get("findings", []) or []
            for row in findings:
                doc_ids: List[str] = []
                for raw in row.get("doc_ids", []) or []:
                    norm = _normalize_doc_id(raw)
                    if norm:
                        doc_ids.append(norm)
                for raw in row.get("post_ids", []) or []:
                    norm = _normalize_doc_id(raw)
                    if norm and norm not in doc_ids:
                        doc_ids.append(norm)
                doc_id = doc_ids[0] if doc_ids else ""
                items.append(
                    RetrievedEvidenceItem(
                        source=source_name,
                        doc_id=doc_id,
                        rank=rank,
                        text=_stringify_text(row.get("finding_statement") or row.get("statement") or row.get("finding_title")),
                        evidence_id=str(row.get("finding_id") or row.get("id") or f"{source_name}_{rank}"),
                        meta=dict(row),
                    )
                )
                rank += 1
    return items


def compute_topk_metrics(
    items: List[RetrievedEvidenceItem],
    relevant_doc_ids: Set[str],
    *,
    top_k: int = 10,
) -> Dict[str, float]:
    """计算 Top-k precision/recall/hit/MRR/nDCG。"""
    top_items = items[: max(1, int(top_k))]
    relevant = set(_normalize_doc_id(x) for x in relevant_doc_ids if x is not None) - {""}
    hits = [1 if item.doc_id and item.doc_id in relevant else 0 for item in top_items]

    precision_at_k = sum(hits) / len(top_items) if top_items else 0.0
    recall_at_k = sum(hits) / len(relevant) if relevant else 0.0
    hit_at_k = 1.0 if any(hits) else 0.0

    reciprocal_rank = 0.0
    for idx, item in enumerate(top_items, start=1):
        if item.doc_id and item.doc_id in relevant:
            reciprocal_rank = 1.0 / idx
            break

    dcg = 0.0
    for idx, hit in enumerate(hits, start=1):
        if hit:
            dcg += 1.0 / math.log2(idx + 1)
    ideal_hits = [1] * min(len(relevant), len(top_items))
    idcg = 0.0
    for idx, hit in enumerate(ideal_hits, start=1):
        if hit:
            idcg += 1.0 / math.log2(idx + 1)
    ndcg = dcg / idcg if idcg > 0 else 0.0

    return {
        "precision_at_k": round(precision_at_k, 4),
        "recall_at_k": round(recall_at_k, 4),
        "hit_at_k": round(hit_at_k, 4),
        "mrr": round(reciprocal_rank, 4),
        "ndcg": round(ndcg, 4),
    }


def compute_evidence_coverage(
    items: List[RetrievedEvidenceItem],
    *,
    required_evidence_ids: Optional[Iterable[Any]] = None,
    must_hit_terms: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """
    计算关键证据覆盖率。优先 evidence_id，其次 must_hit_terms 文本命中。
    """
    required_ids = {
        str(x).strip() for x in (required_evidence_ids or []) if str(x).strip()
    }
    must_terms = [str(x).strip().lower() for x in (must_hit_terms or []) if str(x).strip()]
    matched_ids = set()
    matched_terms = set()

    for item in items:
        if item.evidence_id in required_ids:
            matched_ids.add(item.evidence_id)
        haystack = f"{item.text} {_stringify_text(item.meta)}".lower()
        for term in must_terms:
            if term and term in haystack:
                matched_terms.add(term)

    id_den = len(required_ids)
    term_den = len(must_terms)
    id_cov = len(matched_ids) / id_den if id_den else None
    term_cov = len(matched_terms) / term_den if term_den else None

    if id_cov is not None and term_cov is not None:
        coverage = (id_cov + term_cov) / 2.0
    elif id_cov is not None:
        coverage = id_cov
    elif term_cov is not None:
        coverage = term_cov
    else:
        coverage = 0.0

    return {
        "coverage": round(coverage, 4),
        "matched_evidence_ids": sorted(matched_ids),
        "matched_terms": sorted(matched_terms),
    }


def compute_retriever_attribution(items: List[RetrievedEvidenceItem], relevant_doc_ids: Set[str]) -> Dict[str, Any]:
    """统计命中证据按 retriever 来源分布。"""
    relevant = set(_normalize_doc_id(x) for x in relevant_doc_ids if x is not None) - {""}
    counts = {"graphrag": 0, "normalrag": 0, "tagrag": 0}
    total_hits = 0
    for item in items:
        if item.doc_id and item.doc_id in relevant:
            counts.setdefault(item.source, 0)
            counts[item.source] += 1
            total_hits += 1
    shares = {
        f"{key}_share": round((value / total_hits), 4) if total_hits else 0.0
        for key, value in counts.items()
    }
    return {"hit_counts": counts, "total_hits": total_hits, **shares}


def compute_finding_stats(router_result: Dict[str, Any]) -> Dict[str, Any]:
    """统计 GraphRAG finding-centric 指标。"""
    graphrag = (router_result or {}).get("graphrag") or {}
    findings = graphrag.get("findings", []) or []
    topics: Set[str] = set()
    platforms: Set[str] = set()
    events: Set[str] = set()
    evidence_counts: List[int] = []
    for row in findings:
        topics.update(str(x).strip() for x in (row.get("topics") or []) if str(x).strip())
        platforms.update(str(x).strip() for x in (row.get("platforms") or []) if str(x).strip())
        events.update(str(x).strip() for x in (row.get("events") or []) if str(x).strip())
        evidence_counts.append(
            len(row.get("claim_ids") or [])
            + len(row.get("chunk_ids") or [])
            + len(row.get("post_ids") or [])
        )
    avg_evidence = (sum(evidence_counts) / len(evidence_counts)) if evidence_counts else 0.0
    return {
        "finding_count": len(findings),
        "avg_evidence_per_finding": round(avg_evidence, 4),
        "topic_count": len(topics),
        "platform_count": len(platforms),
        "event_count": len(events),
        "topics": sorted(topics)[:20],
        "platforms": sorted(platforms)[:20],
        "events": sorted(events)[:20],
    }


# ---- 嵌入相似度：无标注下的「相关文档」----

def _cosine_sim(a: List[float], b: List[float]) -> float:
    """余弦相似度；向量维数需一致。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def load_doc_vectors_by_doc_id(topic: str) -> Dict[str, List[float]]:
    """
    按 doc_id 聚合文档向量：从 normalrag（sentence_vec）、graphrag_texts（text_tag_vec）
    按 doc_id 取向量均值，作为该文档的表示。用于与查询向量算相似度、无标注判定相关文档。
    """
    db_path = _get_router_db_path(topic)
    if not db_path.exists():
        return {}
    doc_vectors: Dict[str, List[List[float]]] = {}
    try:
        db = lancedb.connect(str(db_path))
        for tname, vec_col in (("normalrag", "sentence_vec"), ("graphrag_texts", "text_tag_vec")):
            try:
                tbl = db.open_table(tname)
            except Exception:
                continue
            df = tbl.to_pandas()
            if vec_col not in df.columns or "doc_id" not in df.columns:
                continue
            for _, row in df.iterrows():
                doc_id = _normalize_doc_id(row.get("doc_id"))
                if not doc_id:
                    continue
                vec = row.get(vec_col)
                if isinstance(vec, (list, tuple)) and len(vec) > 0:
                    doc_vectors.setdefault(doc_id, []).append(list(vec))
    except Exception:
        return {}
    # 按 doc_id 做向量均值（同维）
    out: Dict[str, List[float]] = {}
    for doc_id, vecs in doc_vectors.items():
        if not vecs:
            continue
        dim = len(vecs[0])
        if not all(len(v) == dim for v in vecs):
            continue
        mean_vec = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
        out[doc_id] = mean_vec
    return out


def _embed_query_sync(text: str, model: str = "text-embedding-v4") -> Optional[List[float]]:
    """同步调用 DashScope 文本嵌入 API，与 RouterRAG 使用同一模型。"""
    try:
        from src.utils.setting.env_loader import get_api_key
    except Exception:
        from ...utils.setting.env_loader import get_api_key  # type: ignore
    api_key = get_api_key()
    if not api_key:
        return None
    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
        data=json.dumps({"model": model, "input": {"texts": [text or ""]}}).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            emb = body.get("output", {}).get("embeddings", [])
            if emb:
                return emb[0].get("embedding")
    except Exception:
        pass
    return None


def get_relevant_docs_by_embedding(
    topic: str,
    query_text: str,
    *,
    top_k: int = 25,
    threshold: Optional[float] = None,
    embedding_model: Optional[str] = None,
) -> List[str]:
    """
    用查询与文档向量的相似度判定相关文档（无需人工标注）。
    查询文本做嵌入，与各 doc 的聚合向量算余弦相似度，取 top_k 或高于 threshold 的 doc_id。
    """
    query_text = (query_text or "").strip()
    if not query_text:
        return []
    model = embedding_model
    if not model:
        try:
            from src.utils.setting.paths import get_configs_root
            config_path = get_configs_root() / "llm.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                model = cfg.get("embedding_llm", {}).get("model", "text-embedding-v4")
            else:
                model = "text-embedding-v4"
        except Exception:
            model = "text-embedding-v4"
    query_vec = _embed_query_sync(query_text, model=model)
    if not query_vec:
        return []
    doc_vecs = load_doc_vectors_by_doc_id(topic)
    if not doc_vecs:
        return []
    sims: List[Tuple[str, float]] = []
    for doc_id, doc_vec in doc_vecs.items():
        if len(doc_vec) != len(query_vec):
            continue
        s = _cosine_sim(query_vec, doc_vec)
        sims.append((doc_id, s))
    sims.sort(key=lambda x: -x[1])
    if threshold is not None:
        return [doc_id for doc_id, s in sims if s >= threshold]
    return [doc_id for doc_id, _ in sims[:top_k]]


# ---- LLM Judge ----

_JUDGE_SYSTEM = """你是一个客观的评判员。根据「问题」「标准答案」和「模型答案」，判断模型答案是否在语义上正确回答了问题。
只输出一个数字：1 表示正确，0 表示错误。不要输出其他内容。"""

_JUDGE_SYSTEM_NO_REF = """你是一个客观的评判员。仅根据「问题」和「模型答案」判断质量，不依赖任何标准答案或文档。
从以下维度综合打分：是否切题、是否连贯、是否像事实性回答（非胡编或明显矛盾）。只输出一个 1-5 的整数：5=很好，4=较好，3=一般，2=较差，1=很差。不要输出其他内容。"""

_JUDGE_SYSTEM_MULTI = """你是一个严格的 RAG 答案评估器。请根据提供的输入，对模型答案进行多维度打分。
返回 JSON，字段固定为：
{
  "accuracy_score": 1-5,
  "faithfulness_score": 1-5,
  "completeness_score": 1-5,
  "citation_score": 1-5,
  "notes": "简短中文说明"
}
不要输出 JSON 以外的内容。"""


def build_judge_prompt(question: str, answer_gold: str, answer_pred: str) -> str:
    """构建 LLM Judge 的 user prompt（有参考）。"""
    return (
        "【问题】\n" + (question or "") + "\n\n"
        "【标准答案】\n" + (answer_gold or "") + "\n\n"
        "【模型答案】\n" + (answer_pred or "") + "\n\n"
        "模型答案是否在语义上正确回答了问题？只输出 1（正确）或 0（错误）："
    )


def build_judge_prompt_no_reference(question: str, answer_pred: str) -> str:
    """构建无参考 Judge 的 user prompt：仅问题与模型答案，输出 1-5 分。"""
    return (
        "【问题】\n" + (question or "") + "\n\n"
        "【模型答案】\n" + (answer_pred or "") + "\n\n"
        "请从切题、连贯、事实性三个维度综合打分，只输出一个 1-5 的整数（5 最好，1 最差）："
    )


def build_multi_judge_prompt(
    question: str,
    answer_gold: str,
    answer_pred: str,
    evidence_context: str = "",
) -> str:
    """构建多维度 Judge 提示词。"""
    return (
        "【问题】\n" + (question or "") + "\n\n"
        "【标准答案】\n" + (answer_gold or "") + "\n\n"
        "【模型答案】\n" + (answer_pred or "") + "\n\n"
        "【可用证据】\n" + (evidence_context or "无") + "\n\n"
        "请从 accuracy、faithfulness、completeness、citation 四个维度分别给出 1-5 分。"
    )


def parse_judge_result(raw: str) -> int:
    """
    从 Judge LLM 的回复中解析 0/1（有参考模式）。
    默认 0（错误）。
    """
    if not raw:
        return 0
    raw = raw.strip()
    m = re.search(r"[01]", raw)
    if m:
        return int(m.group(0))
    if "正确" in raw or "是" in raw or "对" in raw:
        return 1
    return 0


def parse_judge_result_no_reference(raw: str) -> float:
    """
    从无参考 Judge 的回复中解析 1-5 分，并归一化到 [0, 1]。
    5 -> 1.0, 1 -> 0.0。无法解析时返回 0.0。
    """
    if not raw:
        return 0.0
    raw = raw.strip()
    # 匹配 1-5 的整数（可能带前后文如 "评分：4"）
    m = re.search(r"\b([1-5])\b", raw)
    if m:
        x = int(m.group(1))
        return (x - 1) / 4.0  # 1->0, 2->0.25, 3->0.5, 4->0.75, 5->1
    # 兼容 "0.8" 等小数，当作已归一化
    m_float = re.search(r"0?\.\d+", raw)
    if m_float:
        return min(1.0, max(0.0, float(m_float.group(0))))
    return 0.0


def parse_multi_judge_result(raw: str) -> Dict[str, Any]:
    """解析多维度 judge 输出并归一化到 0-1。"""
    default = {
        "accuracy_score": 0.0,
        "faithfulness_score": 0.0,
        "completeness_score": 0.0,
        "citation_score": 0.0,
        "notes": "",
    }
    if not raw:
        return default
    text = raw.strip()
    try:
        obj = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return default
        try:
            obj = json.loads(match.group(0))
        except Exception:
            return default
    out = dict(default)
    for key in ("accuracy_score", "faithfulness_score", "completeness_score", "citation_score"):
        try:
            val = float(obj.get(key, 0))
        except Exception:
            val = 0.0
        if val > 1.0:
            val = max(1.0, min(5.0, val))
            val = (val - 1.0) / 4.0
        out[key] = round(max(0.0, min(1.0, val)), 4)
    out["notes"] = str(obj.get("notes") or "").strip()
    return out


async def call_judge_async(
    question: str,
    answer_gold: str,
    answer_pred: str,
    *,
    judge_mode: str = "with_reference",
    config_path: Optional[Path] = None,
    model_key: str = "router_retrieve_llm",
) -> float:
    """
    异步调用 Judge LLM。有参考返回 0.0/1.0；无参考返回 [0,1] 连续分（由 1-5 分归一化）。
    judge_mode: "with_reference" 用问题+标准答案+模型答案；"no_reference" 仅用问题+模型答案，输出 1-5 后归一化。
    """
    from src.utils.setting.paths import get_configs_root
    from src.utils.ai.qwen import QwenClient

    config_path = config_path or (get_configs_root() / "llm.yaml")
    if not config_path.exists():
        return 0.0
    with open(config_path, "r", encoding="utf-8") as f:
        llm_config = yaml.safe_load(f) or {}
    cfg = llm_config.get(model_key, {})
    model = cfg.get("model", "qwen-plus")

    client = QwenClient()
    if judge_mode == "no_reference":
        system_content = _JUDGE_SYSTEM_NO_REF
        prompt = build_judge_prompt_no_reference(question, answer_pred)
    else:
        system_content = _JUDGE_SYSTEM
        prompt = build_judge_prompt(question, answer_gold, answer_pred)
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": prompt},
    ]

    import aiohttp
    headers = {
        "Authorization": f"Bearer {client.api_key}",
        "Content-Type": "application/json",
    }
    data = {
        "model": model,
        "input": {"messages": messages},
        "parameters": {"max_tokens": 64},
    }
    try:
        timeout = aiohttp.ClientTimeout(total=60, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                json=data,
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    return 0.0
                body = await resp.json()
                text = (body.get("output") or {}).get("text", "") or ""
                if judge_mode == "no_reference":
                    return parse_judge_result_no_reference(text)
                return float(parse_judge_result(text))
    except Exception:
        return 0.0


async def call_multi_judge_async(
    question: str,
    answer_gold: str,
    answer_pred: str,
    *,
    evidence_context: str = "",
    config_path: Optional[Path] = None,
    model_key: str = "router_retrieve_llm",
) -> Dict[str, Any]:
    """多维度 Judge。"""
    from src.utils.setting.paths import get_configs_root
    from src.utils.ai.qwen import QwenClient

    config_path = config_path or (get_configs_root() / "llm.yaml")
    if not config_path.exists():
        return parse_multi_judge_result("")
    with open(config_path, "r", encoding="utf-8") as f:
        llm_config = yaml.safe_load(f) or {}
    cfg = llm_config.get(model_key, {})
    model = cfg.get("model", "qwen-plus")

    client = QwenClient()
    headers = {
        "Authorization": f"Bearer {client.api_key}",
        "Content-Type": "application/json",
    }
    data = {
        "model": model,
        "input": {
            "messages": [
                {"role": "system", "content": _JUDGE_SYSTEM_MULTI},
                {"role": "user", "content": build_multi_judge_prompt(question, answer_gold, answer_pred, evidence_context)},
            ]
        },
        "parameters": {"max_tokens": 256},
    }
    try:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=60, connect=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                json=data,
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    return parse_multi_judge_result("")
                body = await resp.json()
                text = (body.get("output") or {}).get("text", "") or ""
                return parse_multi_judge_result(text)
    except Exception:
        return parse_multi_judge_result("")


def call_judge_sync(
    question: str,
    answer_gold: str,
    answer_pred: str,
    *,
    judge_mode: str = "with_reference",
    **kwargs: Any,
) -> float:
    """同步封装：调用 Judge LLM。有参考返回 0.0/1.0；无参考返回 [0,1]。judge_mode 同 call_judge_async。"""
    return asyncio.run(
        call_judge_async(question, answer_gold, answer_pred, judge_mode=judge_mode, **kwargs)
    )


def call_multi_judge_sync(
    question: str,
    answer_gold: str,
    answer_pred: str,
    *,
    evidence_context: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """同步封装：调用多维度 Judge。"""
    return asyncio.run(
        call_multi_judge_async(
            question,
            answer_gold,
            answer_pred,
            evidence_context=evidence_context,
            **kwargs,
        )
    )


def percentile(values: List[float], pct: float) -> float:
    """简单分位数计算。"""
    nums = sorted(float(x) for x in values if x is not None)
    if not nums:
        return 0.0
    if pct <= 0:
        return nums[0]
    if pct >= 100:
        return nums[-1]
    idx = (len(nums) - 1) * (pct / 100.0)
    lower = int(idx)
    upper = min(lower + 1, len(nums) - 1)
    weight = idx - lower
    return round(nums[lower] * (1 - weight) + nums[upper] * weight, 4)
