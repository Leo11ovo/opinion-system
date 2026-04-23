"""Lightweight RLHF-style feedback tuner for RouterRAG retrieval params."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .store import _feedback_root, list_feedback


def _to_float01(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except Exception:
        return None
    if v < 0:
        return 0.0
    if v <= 1:
        return v
    if v <= 5:
        return v / 5.0
    if v <= 10:
        return v / 10.0
    return 1.0


def _record_reward(record: Dict[str, Any]) -> float:
    scores = record.get("scores")
    vals: List[float] = []
    if isinstance(scores, dict):
        for raw in scores.values():
            v = _to_float01(raw)
            if v is not None:
                vals.append(v)

    if vals:
        base = sum(vals) / max(1, len(vals))
    else:
        bad_reason = str(record.get("bad_reason") or "").strip()
        note = str(record.get("note") or "").strip()
        base = 0.35 if (bad_reason or note) else 0.5

    bad_reason = str(record.get("bad_reason") or "").strip()
    if bad_reason:
        base -= 0.12
    return max(0.0, min(1.0, base))


def _metric_means(records: List[Dict[str, Any]]) -> Dict[str, float]:
    bucket: Dict[str, List[float]] = {}
    for rec in records:
        scores = rec.get("scores")
        if not isinstance(scores, dict):
            continue
        for k, raw in scores.items():
            key = str(k or "").strip()
            if not key:
                continue
            val = _to_float01(raw)
            if val is None:
                continue
            bucket.setdefault(key, []).append(val)
    return {k: (sum(vs) / max(1, len(vs))) for k, vs in bucket.items()}


def _detect_issues(metric_means: Dict[str, float], rewards: List[float]) -> Dict[str, float]:
    issue = {
        "relevance_risk": 0.5,
        "completeness_risk": 0.5,
        "factual_risk": 0.5,
    }
    if rewards:
        overall = sum(rewards) / len(rewards)
        issue["overall_reward"] = overall

    for k, v in metric_means.items():
        lk = k.lower()
        if any(t in lk for t in ("相关", "relevance", "match", "匹配")):
            issue["relevance_risk"] = 1.0 - v
        if any(t in lk for t in ("完整", "complet", "coverage", "覆盖")):
            issue["completeness_risk"] = 1.0 - v
        if any(t in lk for t in ("事实", "fact", "halluc", "准确", "accuracy")):
            issue["factual_risk"] = 1.0 - v
    return issue


def build_feedback_stats(
    topic: str,
    *,
    limit: int = 1000,
    experiment_tag: Optional[str] = None,
) -> Dict[str, Any]:
    records = list_feedback(topic=topic, limit=limit, experiment_tag=experiment_tag)
    rewards = [_record_reward(r) for r in records]
    metric_means = _metric_means(records)
    by_exp: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        tag = str(rec.get("experiment_tag") or "default").strip() or "default"
        slot = by_exp.setdefault(tag, {"count": 0, "rewards": []})
        slot["count"] += 1
        slot["rewards"].append(_record_reward(rec))

    by_experiment = []
    for tag, slot in by_exp.items():
        rs = slot["rewards"]
        by_experiment.append(
            {
                "experiment_tag": tag,
                "count": slot["count"],
                "avg_reward": round(sum(rs) / max(1, len(rs)), 4),
            }
        )
    by_experiment.sort(key=lambda x: (x["avg_reward"], x["count"]), reverse=True)

    issues = _detect_issues(metric_means, rewards)
    avg_reward = round(sum(rewards) / max(1, len(rewards)), 4) if rewards else 0.0

    return {
        "topic": topic,
        "total_feedback": len(records),
        "avg_reward": avg_reward,
        "metric_means": {k: round(v, 4) for k, v in metric_means.items()},
        "issues": {k: round(v, 4) for k, v in issues.items()},
        "by_experiment": by_experiment,
    }


def suggest_retrieval_update(
    *,
    current_retrieval: Optional[Dict[str, Any]],
    stats: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    curr = dict(current_retrieval or {})
    proposal = {
        "top_k": int(curr.get("top_k", 10)),
        "threshold": float(curr.get("threshold", 0.0)),
        "enable_query_expansion": bool(curr.get("enable_query_expansion", True)),
        "enable_llm_summary": bool(curr.get("enable_llm_summary", True)),
        "llm_summary_mode": str(curr.get("llm_summary_mode", "strict") or "strict"),
    }
    reasons: List[str] = []

    total = int(stats.get("total_feedback") or 0)
    avg_reward = float(stats.get("avg_reward") or 0.0)
    issues = stats.get("issues") if isinstance(stats.get("issues"), dict) else {}
    relevance_risk = float(issues.get("relevance_risk", 0.5))
    completeness_risk = float(issues.get("completeness_risk", 0.5))
    factual_risk = float(issues.get("factual_risk", 0.5))

    if total < 8:
        reasons.append("feedback sample too small (<8), only conservative adjustments")
        proposal["enable_query_expansion"] = True
        proposal["enable_llm_summary"] = True
        return proposal, reasons

    if completeness_risk >= 0.55:
        proposal["top_k"] = min(20, max(proposal["top_k"], 12))
        proposal["enable_query_expansion"] = True
        proposal["llm_summary_mode"] = "supplement"
        reasons.append("completeness risk is high, increase recall breadth and supplement summary")

    if relevance_risk >= 0.55:
        proposal["threshold"] = min(0.35, max(proposal["threshold"], 0.08))
        proposal["llm_summary_mode"] = "strict"
        reasons.append("relevance risk is high, tighten similarity threshold and strict summary")

    if factual_risk >= 0.55:
        proposal["enable_llm_summary"] = True
        proposal["llm_summary_mode"] = "strict"
        reasons.append("factual risk is high, force strict LLM summary")

    if avg_reward < 0.45:
        proposal["top_k"] = min(20, max(proposal["top_k"], 14))
        proposal["enable_query_expansion"] = True
        proposal["enable_llm_summary"] = True
        reasons.append("overall reward is low, expand exploration to improve hit chance")
    elif avg_reward > 0.75 and relevance_risk < 0.4:
        proposal["threshold"] = max(proposal["threshold"], 0.05)
        reasons.append("reward is healthy, keep settings stable with mild precision control")

    if not reasons:
        reasons.append("no major issue found, keep current retrieval settings")
    return proposal, reasons


def _tuning_dir() -> Path:
    return _feedback_root() / "tuning"


def save_tuning_snapshot(topic: str, payload: Dict[str, Any]) -> Path:
    safe_topic = str(topic or "").strip().replace("/", "_").replace("\\", "_")
    path = _tuning_dir() / f"{safe_topic}.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    history: List[Dict[str, Any]] = []
    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []

    item = dict(payload or {})
    item.setdefault("created_at", datetime.utcnow().isoformat())
    history.append(item)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

