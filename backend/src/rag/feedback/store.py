"""Simple JSONL feedback store for RouterRAG."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _feedback_root() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "rag_feedback"


def _feedback_file(topic: str) -> Path:
    safe_topic = str(topic or "").strip().replace("/", "_").replace("\\", "_")
    return _feedback_root() / f"{safe_topic}.jsonl"


def append_feedback(topic: str, record: Dict[str, Any]) -> Dict[str, Any]:
    if not str(topic or "").strip():
        raise ValueError("topic is required")
    payload = dict(record or {})
    payload.setdefault("created_at", datetime.utcnow().isoformat())

    path = _feedback_file(topic)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def list_feedback(topic: str, *, limit: int = 100, experiment_tag: Optional[str] = None) -> List[Dict[str, Any]]:
    path = _feedback_file(topic)
    if not path.exists():
        return []

    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if experiment_tag and str(item.get("experiment_tag") or "").strip() != experiment_tag:
                continue
            records.append(item)

    records.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return records[: max(1, int(limit))]


def summarize_feedback(topic: str, *, limit: int = 1000, experiment_tag: Optional[str] = None) -> Dict[str, Any]:
    """汇总反馈与人工 UX 评分。"""
    records = list_feedback(topic=topic, limit=limit, experiment_tag=experiment_tag)
    if not records:
        return {
            "topic": topic,
            "experiment_tag": experiment_tag or "all",
            "total_feedback": 0,
            "avg_manual_ux_score": 0.0,
            "avg_relevance_score": 0.0,
            "avg_usefulness_score": 0.0,
            "avg_trust_score": 0.0,
            "bad_reason_counts": {},
        }

    def _collect_numeric(item: Dict[str, Any], *keys: str) -> List[float]:
        nums: List[float] = []
        scores = item.get("scores")
        for key in keys:
            raw = item.get(key)
            if raw is None and isinstance(scores, dict):
                raw = scores.get(key)
            try:
                num = float(raw)
            except Exception:
                continue
            if num > 1.0:
                num = (max(1.0, min(5.0, num)) - 1.0) / 4.0
            nums.append(max(0.0, min(1.0, num)))
        return nums

    ux_scores: List[float] = []
    rel_scores: List[float] = []
    useful_scores: List[float] = []
    trust_scores: List[float] = []
    bad_reason_counts: Dict[str, int] = {}

    for record in records:
        ux_scores.extend(_collect_numeric(record, "manual_ux_score", "ux"))
        rel_scores.extend(_collect_numeric(record, "user_score_relevance", "relevance"))
        useful_scores.extend(_collect_numeric(record, "user_score_usefulness", "usefulness"))
        trust_scores.extend(_collect_numeric(record, "user_score_trust", "trust"))
        bad_reason = str(record.get("bad_reason") or "").strip()
        if bad_reason:
            bad_reason_counts[bad_reason] = bad_reason_counts.get(bad_reason, 0) + 1

    def _avg(nums: List[float]) -> float:
        return round(sum(nums) / len(nums), 4) if nums else 0.0

    return {
        "topic": topic,
        "experiment_tag": experiment_tag or "all",
        "total_feedback": len(records),
        "avg_manual_ux_score": _avg(ux_scores),
        "avg_relevance_score": _avg(rel_scores),
        "avg_usefulness_score": _avg(useful_scores),
        "avg_trust_score": _avg(trust_scores),
        "bad_reason_counts": bad_reason_counts,
    }
