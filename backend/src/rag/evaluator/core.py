"""
RAG 评估核心：EvaluationData 数据模型、数据加载、主评估流程。
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .utils import (
    call_judge_sync,
    call_multi_judge_sync,
    compute_evidence_coverage,
    compute_finding_stats,
    compute_precision_recall,
    compute_retriever_attribution,
    compute_topk_metrics,
    extract_retrieved_doc_ids,
    extract_retrieved_evidence_items,
    find_relevant_docs_by_keywords,
    get_relevant_docs_by_embedding,
    load_corpus_doc_texts,
    percentile,
)


@dataclass
class EvaluationDataItem:
    """单条评估样本：问题、标准答案、可选的相关文档 ID 与关键证据线索。"""

    question: str
    answer_gold: str
    question_type: Optional[str] = None
    relevant_doc_ids: Optional[List[str]] = None
    required_evidence_ids: Optional[List[str]] = None
    must_hit_terms: Optional[List[str]] = None
    topic_tags: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "question": self.question,
            "answer_gold": self.answer_gold,
        }
        if self.question_type is not None:
            d["question_type"] = self.question_type
        if self.relevant_doc_ids is not None:
            d["relevant_doc_ids"] = self.relevant_doc_ids
        if self.required_evidence_ids is not None:
            d["required_evidence_ids"] = self.required_evidence_ids
        if self.must_hit_terms is not None:
            d["must_hit_terms"] = self.must_hit_terms
        if self.topic_tags is not None:
            d["topic_tags"] = self.topic_tags
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvaluationDataItem":
        return cls(
            question=str(d.get("question", "")).strip(),
            answer_gold=str(d.get("answer_gold", "")).strip(),
            question_type=str(d.get("question_type", "")).strip() or None,
            relevant_doc_ids=d.get("relevant_doc_ids"),
            required_evidence_ids=d.get("required_evidence_ids"),
            must_hit_terms=d.get("must_hit_terms"),
            topic_tags=d.get("topic_tags"),
        )


@dataclass
class EvaluationData:
    """评估数据集：多条样本，可选元信息。"""

    items: List[EvaluationDataItem] = field(default_factory=list)
    name: Optional[str] = None
    version: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "items": [x.to_dict() for x in self.items],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvaluationData":
        items = []
        for x in d.get("items", []):
            if isinstance(x, dict):
                items.append(EvaluationDataItem.from_dict(x))
        return cls(
            items=items,
            name=d.get("name"),
            version=d.get("version"),
        )


def load_evaluation_data(path: Path) -> EvaluationData:
    """
    从 JSON 文件加载评估数据。
    支持旧格式与增强格式。
    """
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, list):
        data = {"items": data}
    return EvaluationData.from_dict(data)


def _get_a_pred(
    topic: str,
    question: str,
    mode: str = "mixed",
    *,
    question_type: Optional[str] = None,
    experiment_tag: str = "default",
) -> str:
    """调用 RouterRAG 生成模型答案 A_pred（LLM 整理结果）。"""
    from src.utils.rag.ragrouter.router_retrieve_data import router_retrieve

    result = router_retrieve(
        topic=topic,
        query=question,
        mode=mode,
        enable_llm_summary=True,
        return_format="llm_only",
        question_type=question_type,
        experiment_tag=experiment_tag,
    )
    if result.get("status") == "error":
        return ""
    return (result.get("llm_summary") or "").strip()


def _get_router_index_result(
    topic: str,
    question: str,
    mode: str = "mixed",
    *,
    question_type: Optional[str] = None,
    experiment_tag: str = "default",
) -> Dict[str, Any]:
    """调用 RouterRAG 并返回 index_only 结果。"""
    from src.utils.rag.ragrouter.router_retrieve_data import router_retrieve

    result = router_retrieve(
        topic=topic,
        query=question,
        mode=mode,
        enable_llm_summary=False,
        return_format="index_only",
        question_type=question_type,
        experiment_tag=experiment_tag,
    )
    return result if isinstance(result, dict) else {}


def _normalize_question_type(name: Optional[str]) -> str:
    val = str(name or "").strip().lower()
    return val or "unknown"


def _group_average(rows: List[Dict[str, Any]], key: str) -> float:
    nums = [float(r.get(key) or 0.0) for r in rows]
    return round(sum(nums) / len(nums), 4) if nums else 0.0


def _aggregate_breakdown(samples_out: List[Dict[str, Any]], group_key: str) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for sample in samples_out:
        key = str(sample.get(group_key) or "unknown")
        groups.setdefault(key, []).append(sample)
    breakdown: Dict[str, Any] = {}
    for key, rows in groups.items():
        breakdown[key] = {
            "count": len(rows),
            "precision_avg": _group_average(rows, "precision"),
            "recall_avg": _group_average(rows, "recall"),
            "precision_at_k_avg": _group_average(rows, "precision_at_k"),
            "recall_at_k_avg": _group_average(rows, "recall_at_k"),
            "hit_at_k_avg": _group_average(rows, "hit_at_k"),
            "mrr_avg": _group_average(rows, "mrr"),
            "ndcg_avg": _group_average(rows, "ndcg"),
            "evidence_coverage_avg": _group_average(rows, "evidence_coverage"),
            "accuracy_score_avg": _group_average(rows, "accuracy_score"),
            "faithfulness_score_avg": _group_average(rows, "faithfulness_score"),
            "completeness_score_avg": _group_average(rows, "completeness_score"),
            "citation_score_avg": _group_average(rows, "citation_score"),
            "manual_ux_score_avg": _group_average(rows, "manual_ux_score"),
            "latency_ms_avg": _group_average(rows, "latency_ms"),
        }
    return breakdown


def _load_manual_ux_scores(
    topic: str,
    experiment_tag: str = "default",
    manual_feedback_path: Optional[Path] = None,
) -> Dict[str, float]:
    """
    读取人工 UX 评分。支持 JSON / JSONL：
    - {"records":[{"question":"...","score":4}]}
    - 每行一个 JSON
    """
    rows: List[Dict[str, Any]] = []
    if manual_feedback_path and manual_feedback_path.is_file():
        text = manual_feedback_path.read_text(encoding="utf-8").strip()
        if text:
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    rows = obj.get("records", []) or []
                elif isinstance(obj, list):
                    rows = obj
            except Exception:
                rows = []
                for line in text.splitlines():
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        rows.append(json.loads(raw))
                    except Exception:
                        continue
    else:
        try:
            from src.rag.feedback.store import list_feedback

            rows = list_feedback(topic=topic, limit=5000, experiment_tag=experiment_tag)
        except Exception:
            rows = []

    question_to_scores: Dict[str, List[float]] = {}
    for row in rows:
        question = str(row.get("question") or "").strip()
        if not question:
            continue
        values: List[float] = []
        for field_name in ("manual_ux_score", "user_score_relevance", "user_score_usefulness", "user_score_trust"):
            raw = row.get(field_name)
            try:
                num = float(raw)
            except Exception:
                continue
            if num > 1.0:
                num = (max(1.0, min(5.0, num)) - 1.0) / 4.0
            values.append(max(0.0, min(1.0, num)))
        scores_payload = row.get("scores")
        if isinstance(scores_payload, dict):
            for field_name in ("relevance", "usefulness", "trust", "ux"):
                raw = scores_payload.get(field_name)
                try:
                    num = float(raw)
                except Exception:
                    continue
                if num > 1.0:
                    num = (max(1.0, min(5.0, num)) - 1.0) / 4.0
                values.append(max(0.0, min(1.0, num)))
        if values:
            question_to_scores.setdefault(question, []).extend(values)
    return {
        question: round(sum(values) / len(values), 4)
        for question, values in question_to_scores.items()
        if values
    }


def _build_evidence_context(router_index_result: Dict[str, Any], limit: int = 6) -> str:
    items = extract_retrieved_evidence_items(router_index_result)
    parts: List[str] = []
    for item in items[: max(1, limit)]:
        snippet = item.text[:180].replace("\n", " ")
        parts.append(f"[{item.source}] doc={item.doc_id or '-'} evidence={item.evidence_id}: {snippet}")
    return "\n".join(parts)


def _select_failure_reasons(sample: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    if float(sample.get("recall_at_k") or 0.0) < 0.3:
        reasons.append("漏召回")
    if float(sample.get("precision_at_k") or 0.0) < 0.3:
        reasons.append("排序不准")
    if float(sample.get("faithfulness_score") or 0.0) < 0.5:
        reasons.append("幻觉")
    if float(sample.get("citation_score") or 0.0) < 0.5:
        reasons.append("引用不足")
    if float(sample.get("latency_ms") or 0.0) > 15000:
        reasons.append("延迟高")
    if bool(sample.get("empty_result")):
        reasons.append("空结果")
    return reasons


def run_evaluation(
    topic: str,
    eval_data_path: Path,
    *,
    mode: str = "mixed",
    use_judge: bool = True,
    judge_mode: str = "with_reference",
    fill_relevant_docs_with_keywords: bool = True,
    relevant_method: str = "embedding",
    experiment_tag: str = "default",
    eval_scope: str = "all",
    top_k: int = 10,
    include_breakdown: bool = True,
    manual_feedback_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    主评估函数：对每条样本跑 RouterRAG 检索 + 生成，并产出检索/生成/UX 代理三层指标。
    """
    data = load_evaluation_data(eval_data_path)
    samples_out: List[Dict[str, Any]] = []
    manual_ux_scores = _load_manual_ux_scores(topic=topic, experiment_tag=experiment_tag, manual_feedback_path=manual_feedback_path)

    for item in data.items:
        question = item.question
        answer_gold = item.answer_gold
        question_type = item.question_type
        relevant = set(item.relevant_doc_ids or [])
        required_evidence_ids = list(item.required_evidence_ids or [])
        must_hit_terms = list(item.must_hit_terms or [])

        if fill_relevant_docs_with_keywords and not relevant:
            if relevant_method == "embedding":
                query_for_relevant = f"{question} {answer_gold}".strip()
                ids = get_relevant_docs_by_embedding(topic, query_for_relevant, top_k=25)
                relevant = set(ids)
            else:
                ids_q = find_relevant_docs_by_keywords(topic, question, ngram_size=3)
                ids_a = find_relevant_docs_by_keywords(topic, answer_gold, ngram_size=3)
                relevant = set(ids_q) & set(ids_a)
                if not relevant:
                    relevant = set(ids_q) | set(ids_a)

        start = time.perf_counter()
        router_index_result = _get_router_index_result(
            topic,
            question,
            mode=mode,
            question_type=question_type,
            experiment_tag=experiment_tag,
        )
        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        retrieved = extract_retrieved_doc_ids(router_index_result)
        if not relevant and retrieved:
            relevant = set(retrieved)
        precision, recall = compute_precision_recall(retrieved, relevant)

        evidence_items = extract_retrieved_evidence_items(router_index_result)
        topk_metrics = compute_topk_metrics(evidence_items, relevant, top_k=top_k)
        evidence_coverage = compute_evidence_coverage(
            evidence_items,
            required_evidence_ids=required_evidence_ids,
            must_hit_terms=must_hit_terms,
        )
        attribution = compute_retriever_attribution(evidence_items, relevant)
        finding_stats = compute_finding_stats(router_index_result)

        a_pred = ""
        llm_summary_failure = False
        if eval_scope in ("all", "generation"):
            a_pred = _get_a_pred(
                topic,
                question,
                mode=mode,
                question_type=question_type,
                experiment_tag=experiment_tag,
            )
            llm_summary_failure = not bool(a_pred)

        if use_judge and eval_scope in ("all", "generation"):
            evidence_context = _build_evidence_context(router_index_result)
            multi_scores = call_multi_judge_sync(question, answer_gold, a_pred, evidence_context=evidence_context)
            judge_score = call_judge_sync(question, answer_gold, a_pred, judge_mode=judge_mode)
        else:
            multi_scores = {
                "accuracy_score": 0.0,
                "faithfulness_score": 0.0,
                "completeness_score": 0.0,
                "citation_score": 0.0,
                "notes": "",
            }
            judge_score = None

        hallucination_rate = round(1.0 - float(multi_scores.get("faithfulness_score") or 0.0), 4)
        empty_result = len(retrieved) == 0
        status_is_error = router_index_result.get("status") == "error"
        fallback_rate = 1.0 if (
            status_is_error
            or str(((router_index_result.get("expert_overlay") or {}).get("status") or "")).lower() == "degraded"
            or not retrieved
        ) else 0.0
        manual_ux_score = float(manual_ux_scores.get(question, 0.0))

        sample = {
            "question": question,
            "question_type": _normalize_question_type(question_type),
            "topic_tags": item.topic_tags or [],
            "precision": precision,
            "recall": recall,
            "precision_at_k": topk_metrics["precision_at_k"],
            "recall_at_k": topk_metrics["recall_at_k"],
            "hit_at_k": topk_metrics["hit_at_k"],
            "mrr": topk_metrics["mrr"],
            "ndcg": topk_metrics["ndcg"],
            "evidence_coverage": evidence_coverage["coverage"],
            "retriever_attribution": attribution,
            "finding_stats": finding_stats,
            "judge_score": round(judge_score, 4) if judge_score is not None else None,
            "accuracy_score": float(multi_scores.get("accuracy_score") or 0.0),
            "faithfulness_score": float(multi_scores.get("faithfulness_score") or 0.0),
            "completeness_score": float(multi_scores.get("completeness_score") or 0.0),
            "citation_score": float(multi_scores.get("citation_score") or 0.0),
            "hallucination_rate": hallucination_rate,
            "a_pred": a_pred,
            "latency_ms": latency_ms,
            "timeout": latency_ms > 30000,
            "error": status_is_error,
            "empty_result": empty_result,
            "llm_summary_failure": llm_summary_failure,
            "fallback_rate": fallback_rate,
            "manual_ux_score": round(manual_ux_score, 4),
            "required_evidence_ids": required_evidence_ids,
            "must_hit_terms": must_hit_terms,
            "matched_evidence_ids": evidence_coverage["matched_evidence_ids"],
            "matched_terms": evidence_coverage["matched_terms"],
            "failure_reasons": [],
        }
        sample["failure_reasons"] = _select_failure_reasons(sample)
        samples_out.append(sample)

    n = len(samples_out)
    retrieval_metrics = {
        "precision_avg": _group_average(samples_out, "precision"),
        "recall_avg": _group_average(samples_out, "recall"),
        "precision_at_k_avg": _group_average(samples_out, "precision_at_k"),
        "recall_at_k_avg": _group_average(samples_out, "recall_at_k"),
        "hit_at_k_avg": _group_average(samples_out, "hit_at_k"),
        "mrr_avg": _group_average(samples_out, "mrr"),
        "ndcg_avg": _group_average(samples_out, "ndcg"),
        "evidence_coverage_avg": _group_average(samples_out, "evidence_coverage"),
        "finding_count_avg": _group_average(
            [{"finding_count": (x.get("finding_stats") or {}).get("finding_count", 0)} for x in samples_out],
            "finding_count",
        ),
    }
    generation_metrics = {
        "judge_correct_ratio": _group_average(
            [x for x in samples_out if x.get("judge_score") is not None],
            "judge_score",
        ),
        "answer_accuracy_avg": _group_average(samples_out, "accuracy_score"),
        "faithfulness_avg": _group_average(samples_out, "faithfulness_score"),
        "completeness_avg": _group_average(samples_out, "completeness_score"),
        "citation_coverage_avg": _group_average(samples_out, "citation_score"),
        "hallucination_rate_avg": _group_average(samples_out, "hallucination_rate"),
        "empty_weak_answer_rate": round(
            sum(1 for x in samples_out if not str(x.get("a_pred") or "").strip()) / n, 4
        ) if n else 0.0,
    }
    ux_metrics = {
        "avg_latency_ms": _group_average(samples_out, "latency_ms"),
        "p95_latency_ms": percentile([float(x.get("latency_ms") or 0.0) for x in samples_out], 95),
        "timeout_rate": round(sum(1 for x in samples_out if x.get("timeout")) / n, 4) if n else 0.0,
        "error_rate": round(sum(1 for x in samples_out if x.get("error")) / n, 4) if n else 0.0,
        "empty_result_rate": round(sum(1 for x in samples_out if x.get("empty_result")) / n, 4) if n else 0.0,
        "llm_summary_failure_rate": round(sum(1 for x in samples_out if x.get("llm_summary_failure")) / n, 4) if n else 0.0,
        "fallback_rate": _group_average(samples_out, "fallback_rate"),
        "manual_ux_score": _group_average([x for x in samples_out if x.get("manual_ux_score")], "manual_ux_score"),
    }

    failure_cases = [
        {
            "question": x["question"],
            "question_type": x["question_type"],
            "failure_reasons": x["failure_reasons"],
            "latency_ms": x["latency_ms"],
            "precision_at_k": x["precision_at_k"],
            "recall_at_k": x["recall_at_k"],
            "accuracy_score": x["accuracy_score"],
            "faithfulness_score": x["faithfulness_score"],
            "citation_score": x["citation_score"],
        }
        for x in samples_out
        if x["failure_reasons"]
    ]

    breakdown = {}
    if include_breakdown:
        breakdown = {
            "by_question_type": _aggregate_breakdown(samples_out, "question_type"),
        }

    return {
        "topic": topic,
        "mode": mode,
        "experiment_tag": experiment_tag,
        "eval_scope": eval_scope,
        "top_k": int(top_k),
        "num_samples": n,
        "dataset": {
            "name": data.name,
            "version": data.version,
        },
        "retrieval_metrics": retrieval_metrics,
        "generation_metrics": generation_metrics,
        "ux_metrics": ux_metrics,
        # 兼容旧结构
        "precision_avg": retrieval_metrics["precision_avg"],
        "recall_avg": retrieval_metrics["recall_avg"],
        "judge_correct_ratio": generation_metrics["judge_correct_ratio"],
        "breakdown_by_question_type": breakdown.get("by_question_type", {}),
        "failure_cases": failure_cases,
        "samples": samples_out,
    }


def run_evaluation_compare(
    topic: str,
    eval_data_path: Path,
    *,
    mode: str = "mixed",
    baseline_tag: str = "baseline",
    candidate_tag: str = "candidate",
    use_judge: bool = True,
    judge_mode: str = "with_reference",
    fill_relevant_docs_with_keywords: bool = True,
    relevant_method: str = "embedding",
    eval_scope: str = "all",
    top_k: int = 10,
    include_breakdown: bool = True,
    manual_feedback_path: Optional[Path] = None,
) -> Dict[str, Any]:
    baseline = run_evaluation(
        topic=topic,
        eval_data_path=eval_data_path,
        mode=mode,
        use_judge=use_judge,
        judge_mode=judge_mode,
        fill_relevant_docs_with_keywords=fill_relevant_docs_with_keywords,
        relevant_method=relevant_method,
        experiment_tag=baseline_tag,
        eval_scope=eval_scope,
        top_k=top_k,
        include_breakdown=include_breakdown,
        manual_feedback_path=manual_feedback_path,
    )
    candidate = run_evaluation(
        topic=topic,
        eval_data_path=eval_data_path,
        mode=mode,
        use_judge=use_judge,
        judge_mode=judge_mode,
        fill_relevant_docs_with_keywords=fill_relevant_docs_with_keywords,
        relevant_method=relevant_method,
        experiment_tag=candidate_tag,
        eval_scope=eval_scope,
        top_k=top_k,
        include_breakdown=include_breakdown,
        manual_feedback_path=manual_feedback_path,
    )

    metric_paths = {
        "precision_avg": ("retrieval_metrics", "precision_avg"),
        "recall_avg": ("retrieval_metrics", "recall_avg"),
        "precision_at_k_avg": ("retrieval_metrics", "precision_at_k_avg"),
        "recall_at_k_avg": ("retrieval_metrics", "recall_at_k_avg"),
        "hit_at_k_avg": ("retrieval_metrics", "hit_at_k_avg"),
        "mrr_avg": ("retrieval_metrics", "mrr_avg"),
        "ndcg_avg": ("retrieval_metrics", "ndcg_avg"),
        "evidence_coverage_avg": ("retrieval_metrics", "evidence_coverage_avg"),
        "answer_accuracy_avg": ("generation_metrics", "answer_accuracy_avg"),
        "faithfulness_avg": ("generation_metrics", "faithfulness_avg"),
        "completeness_avg": ("generation_metrics", "completeness_avg"),
        "citation_coverage_avg": ("generation_metrics", "citation_coverage_avg"),
        "hallucination_rate_avg": ("generation_metrics", "hallucination_rate_avg"),
        "avg_latency_ms": ("ux_metrics", "avg_latency_ms"),
        "p95_latency_ms": ("ux_metrics", "p95_latency_ms"),
        "error_rate": ("ux_metrics", "error_rate"),
        "empty_result_rate": ("ux_metrics", "empty_result_rate"),
        "fallback_rate": ("ux_metrics", "fallback_rate"),
        "manual_ux_score": ("ux_metrics", "manual_ux_score"),
    }
    delta: Dict[str, float] = {}
    for name, (section, key) in metric_paths.items():
        delta[name] = round(
            float((candidate.get(section) or {}).get(key, 0.0)) - float((baseline.get(section) or {}).get(key, 0.0)),
            4,
        )

    regression_cases: List[Dict[str, Any]] = []
    base_samples = {str(x.get("question") or ""): x for x in baseline.get("samples", []) or []}
    for cand in candidate.get("samples", []) or []:
        question = str(cand.get("question") or "")
        base = base_samples.get(question) or {}
        regressions = []
        if float(cand.get("precision_at_k") or 0.0) < float(base.get("precision_at_k") or 0.0):
            regressions.append("precision_at_k")
        if float(cand.get("faithfulness_score") or 0.0) < float(base.get("faithfulness_score") or 0.0):
            regressions.append("faithfulness")
        if float(cand.get("citation_score") or 0.0) < float(base.get("citation_score") or 0.0):
            regressions.append("citation")
        if float(cand.get("latency_ms") or 0.0) > float(base.get("latency_ms") or 0.0):
            regressions.append("latency")
        if regressions:
            regression_cases.append(
                {
                    "question": question,
                    "question_type": cand.get("question_type"),
                    "baseline": {
                        "precision_at_k": base.get("precision_at_k"),
                        "faithfulness_score": base.get("faithfulness_score"),
                        "citation_score": base.get("citation_score"),
                        "latency_ms": base.get("latency_ms"),
                    },
                    "candidate": {
                        "precision_at_k": cand.get("precision_at_k"),
                        "faithfulness_score": cand.get("faithfulness_score"),
                        "citation_score": cand.get("citation_score"),
                        "latency_ms": cand.get("latency_ms"),
                    },
                    "regressions": regressions,
                }
            )

    return {
        "topic": topic,
        "mode": mode,
        "eval_scope": eval_scope,
        "baseline": baseline,
        "candidate": candidate,
        "delta": delta,
        "regression_cases": regression_cases,
    }
