"""Formatting helpers for GraphRAG retrieval output."""
from __future__ import annotations

from typing import Any, Dict, List


class GraphRAGFormatter:
    """Map finding-centric graph hits to RouterRAG graphrag payload."""

    def format(self, hits: List[Dict[str, Any]], topk: int) -> Dict[str, Any]:
        findings = [dict(hit) for hit in (hits or [])[: max(1, int(topk))]]
        if not findings:
            return {
                "findings": [],
                "capability": {
                    "mode": "empty",
                    "summary": "未命中 Finding 结果，GraphRAG 当前无可展示结果。",
                    "is_degraded": True,
                },
                "evidence": {
                    "claim_count": 0,
                    "chunk_count": 0,
                    "post_count": 0,
                    "event_count": 0,
                    "topic_count": 0,
                    "recommendation_count": 0,
                },
                "summary": [],
            }

        claim_ids = set()
        chunk_ids = set()
        post_ids = set()
        events = set()
        topics = set()
        recommendations = set()
        summary: List[Dict[str, Any]] = []

        for item in findings:
            claim_ids.update([str(x) for x in (item.get("claim_ids") or []) if str(x)])
            chunk_ids.update([str(x) for x in (item.get("chunk_ids") or []) if str(x)])
            post_ids.update([str(x) for x in (item.get("post_ids") or []) if str(x)])
            events.update([str(x) for x in (item.get("events") or []) if str(x)])
            topics.update([str(x) for x in (item.get("topics") or []) if str(x)])
            recommendations.update([str(x) for x in (item.get("recommendations") or []) if str(x)])
            summary.append(
                {
                    "finding_id": str(item.get("finding_id") or ""),
                    "finding_title": str(item.get("finding_title") or ""),
                    "score": float(item.get("score") or 0.0),
                    "graph_score": float(item.get("graph_score") or 0.0),
                    "evidence_score": float(item.get("evidence_score") or 0.0),
                    "seed": item.get("seed") or {},
                }
            )

        return {
            "findings": findings,
            "capability": {
                "mode": "finding_centric",
                "summary": "已返回 Finding 主结果及 claim/chunk/post/event/topic 证据链。",
                "is_degraded": False,
            },
            "evidence": {
                "claim_count": len(claim_ids),
                "chunk_count": len(chunk_ids),
                "post_count": len(post_ids),
                "event_count": len(events),
                "topic_count": len(topics),
                "recommendation_count": len(recommendations),
            },
            "summary": summary,
        }
