"""LLM-driven planning graph engine for expert retrieval."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.graph.neo4j_client import get_session
from src.utils.ai.qwen import QwenClient
from src.utils.logging.logging import log_error, setup_logger

from .schema import DEFAULT_NEXT_CONFIDENCE_THRESHOLD, VOCAB_CACHE_VERSION

LOGGER = setup_logger("PlanningGraph", "default")


class PlanningGraphEngine:
    def __init__(
        self,
        *,
        next_threshold: float = DEFAULT_NEXT_CONFIDENCE_THRESHOLD,
        cache_path: Optional[Path] = None,
        model: str = "qwen-plus",
    ) -> None:
        self.next_threshold = float(next_threshold)
        self.cache_path = cache_path or (Path(__file__).resolve().parents[3] / "data" / "expert" / "planning_vocab_cache.json")
        self.next_whitelist_path = Path(__file__).resolve().parents[3] / "data" / "expert" / "planning_next_whitelist.json"
        self.model = model
        self.qwen_client = QwenClient()

    def _neo4j_session(self):
        try:
            return get_session(database="opinion-expert")
        except Exception as exc:
            if "Database does not exist" in str(exc) or "database management is not supported" in str(exc):
                return get_session()
            raise

    def _load_vocab_cache(self) -> Optional[Dict[str, Any]]:
        if not self.cache_path.exists():
            return None
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if int(data.get("version", 0)) != VOCAB_CACHE_VERSION:
                return None
            return data
        except Exception:
            return None

    def _save_vocab_cache(self, payload: Dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def build_vocab(self, force_refresh: bool = False) -> Dict[str, Any]:
        if not force_refresh:
            cached = self._load_vocab_cache()
            if cached:
                return cached

        vocab = {
            "version": VOCAB_CACHE_VERSION,
            "updated_at": datetime.now().isoformat(),
            "scenario": [],
            "goal": [],
            "dimension": [],
            "task": [],
            "method": [],
        }

        cypher = """
        MATCH (n:ExpertNode)
        WHERE n.name IS NOT NULL AND size(trim(n.name)) > 0
        RETURN labels(n) AS labels, n.name AS name, coalesce(n.description, '') AS description
        LIMIT 2000
        """
        records: List[Dict[str, Any]] = []
        with self._neo4j_session() as session:
            records = session.run(cypher).data()

        def _append(bucket: str, canonical: str, aliases: List[str], source: str) -> None:
            canonical = canonical.strip()
            if not canonical:
                return
            exists = next((x for x in vocab[bucket] if x["canonical"] == canonical), None)
            if exists:
                exists["aliases"] = sorted(set(exists["aliases"] + aliases))
                return
            vocab[bucket].append({
                "canonical": canonical,
                "aliases": sorted(set([canonical] + aliases)),
                "confidence": 0.6,
                "source_nodes": [source],
            })

        for row in records:
            labels = set(row.get("labels") or [])
            name = str(row.get("name") or "").strip()
            desc = str(row.get("description") or "")
            source = ",".join(sorted(labels)) or "ExpertNode"
            aliases = [name.lower()]

            if "Method" in labels or "Methodology" in labels or "Theory" in labels:
                _append("method", name, aliases, source)
            if "Indicator" in labels or "Frame" in labels or "Risk" in labels:
                _append("dimension", name, aliases, source)
            if "CaseStudy" in labels or "Event" in labels:
                _append("scenario", name, aliases, source)
            if "Guideline" in labels:
                _append("goal", name, aliases, source)

            # Auto-extract candidate task names from descriptions.
            for m in re.findall(r"(?:任务|步骤|工作)[：:]\s*([^\n，。,;；]{2,30})", desc):
                _append("task", m.strip(), [m.strip().lower()], source)

        self._save_vocab_cache(vocab)
        return vocab

    @staticmethod
    def _normalize_terms(items: List[str], vocab_items: List[Dict[str, Any]]) -> Tuple[List[str], List[Dict[str, str]]]:
        alias_map: Dict[str, str] = {}
        for entry in vocab_items:
            canonical = str(entry.get("canonical", "")).strip()
            if not canonical:
                continue
            alias_map[canonical.lower()] = canonical
            for a in entry.get("aliases", []):
                s = str(a).strip().lower()
                if s:
                    alias_map[s] = canonical

        normalized: List[str] = []
        hits: List[Dict[str, str]] = []
        for raw in items:
            token = str(raw or "").strip()
            if not token:
                continue
            canonical = alias_map.get(token.lower(), token)
            normalized.append(canonical)
            if canonical != token:
                hits.append({"raw": token, "canonical": canonical})
        return sorted(set(normalized)), hits

    async def _call_llm_plan(self, query: str, vocab: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""
你是舆情分析规划器。请根据用户问题生成严格JSON，不要输出任何解释。

用户问题:
{query}

受控词表（摘要）:
Scenario: {[x['canonical'] for x in vocab.get('scenario', [])[:80]]}
Goal: {[x['canonical'] for x in vocab.get('goal', [])[:80]]}
Dimension: {[x['canonical'] for x in vocab.get('dimension', [])[:80]]}
Task: {[x['canonical'] for x in vocab.get('task', [])[:80]]}
Method: {[x['canonical'] for x in vocab.get('method', [])[:80]]}

输出JSON结构:
{{
  "scenario": ["..."],
  "goals": ["..."],
  "dimensions": ["..."],
  "tasks": ["..."],
  "methods": ["..."],
  "retrieval_hints": {{
    "keywords": ["..."],
    "exclude": ["..."],
    "time_terms": ["..."]
  }},
  "next_edges": [
    {{"from_task":"...","to_task":"...","confidence":0.0,"evidence":"..."}}
  ]
}}
"""
        resp = await self.qwen_client.call(prompt=prompt, model=self.model, max_tokens=1800)
        if not resp or not resp.get("text"):
            return {
                "scenario": [],
                "goals": [],
                "dimensions": [],
                "tasks": [],
                "methods": [],
                "retrieval_hints": {"keywords": [], "exclude": [], "time_terms": []},
                "next_edges": [],
            }
        text = str(resp["text"])
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {
                "scenario": [],
                "goals": [],
                "dimensions": [],
                "tasks": [],
                "methods": [],
                "retrieval_hints": {"keywords": [], "exclude": [], "time_terms": []},
                "next_edges": [],
            }
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                data.setdefault("retrieval_hints", {})
                if not isinstance(data["retrieval_hints"], dict):
                    data["retrieval_hints"] = {}
                data["retrieval_hints"].setdefault("keywords", [])
                data["retrieval_hints"].setdefault("exclude", [])
                data["retrieval_hints"].setdefault("time_terms", [])
                return data
        except Exception:
            pass
        return {
            "scenario": [],
            "goals": [],
            "dimensions": [],
            "tasks": [],
            "methods": [],
            "retrieval_hints": {"keywords": [], "exclude": [], "time_terms": []},
            "next_edges": [],
        }

    def _materialize_planning_graph(self, plan: Dict[str, Any]) -> None:
        scenarios = plan.get("scenario", [])
        goals = plan.get("goals", [])
        dimensions = plan.get("dimensions", [])
        tasks = plan.get("tasks", [])
        methods = plan.get("methods", [])

        with self._neo4j_session() as session:
            for name in scenarios:
                session.run("MERGE (n:Scenario:ExpertNode {name:$name}) SET n.id = coalesce(n.id, 'scenario_' + $name)", {"name": name})
            for name in goals:
                session.run("MERGE (n:Goal:ExpertNode {name:$name}) SET n.id = coalesce(n.id, 'goal_' + $name)", {"name": name})
            for name in dimensions:
                session.run("MERGE (n:Dimension:ExpertNode {name:$name}) SET n.id = coalesce(n.id, 'dimension_' + $name)", {"name": name})
            for name in tasks:
                session.run("MERGE (n:Task:ExpertNode {name:$name}) SET n.id = coalesce(n.id, 'task_' + $name)", {"name": name})
            for name in methods:
                session.run("MERGE (n:Method:ExpertNode {name:$name}) SET n.id = coalesce(n.id, 'method_' + $name)", {"name": name})

            for s in scenarios:
                for g in goals:
                    session.run(
                        "MATCH (s:Scenario {name:$s}) "
                        "MATCH (g:Goal {name:$g}) "
                        "MERGE (s)-[:HAS_GOAL]->(g)",
                        {"s": s, "g": g},
                    )
            for g in goals:
                for d in dimensions:
                    session.run(
                        "MATCH (g:Goal {name:$g}) "
                        "MATCH (d:Dimension {name:$d}) "
                        "MERGE (g)-[:FOCUS_ON]->(d)",
                        {"g": g, "d": d},
                    )
                for t in tasks:
                    session.run(
                        "MATCH (g:Goal {name:$g}) "
                        "MATCH (t:Task {name:$t}) "
                        "MERGE (g)-[:REQUIRES_TASK]->(t)",
                        {"g": g, "t": t},
                    )
            for t in tasks:
                for m in methods:
                    session.run(
                        "MATCH (t:Task {name:$t}) "
                        "MATCH (m:Method {name:$m}) "
                        "MERGE (t)-[:SOLVED_BY]->(m)",
                        {"t": t, "m": m},
                    )

    def _load_next_whitelist(self) -> List[Dict[str, Any]]:
        if not self.next_whitelist_path.exists():
            return []
        try:
            data = json.loads(self.next_whitelist_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            return []
        return []

    def _apply_next_whitelist(self, tasks: List[str]) -> Dict[str, Any]:
        writeback = {
            "mode": "whitelist_only",
            "threshold": self.next_threshold,
            "written_count": 0,
            "filtered_count": 0,
            "failed_count": 0,
            "errors": [],
        }
        whitelist = self._load_next_whitelist()
        task_set = set(tasks)
        with self._neo4j_session() as session:
            for edge in whitelist:
                src = str(edge.get("from_task") or "").strip()
                tgt = str(edge.get("to_task") or "").strip()
                conf = float(edge.get("confidence") or 1.0)
                if not src or not tgt:
                    continue
                if src not in task_set or tgt not in task_set:
                    continue
                if conf < self.next_threshold:
                    writeback["filtered_count"] += 1
                    continue
                try:
                    session.run(
                        """
                        MERGE (a:Task:ExpertNode {name:$src})
                        MERGE (b:Task:ExpertNode {name:$tgt})
                        MERGE (a)-[r:NEXT]->(b)
                        SET r.source = 'whitelist',
                            r.confidence = $conf,
                            r.updated_at = $ts
                        """,
                        {"src": src, "tgt": tgt, "conf": conf, "ts": datetime.now().isoformat()},
                    )
                    writeback["written_count"] += 1
                except Exception as exc:
                    writeback["failed_count"] += 1
                    writeback["errors"].append(str(exc))
        return writeback

    def generate_plan(self, query: str) -> Dict[str, Any]:
        vocab = self.build_vocab(force_refresh=False)
        llm_plan = asyncio.run(self._call_llm_plan(query, vocab))

        scenario, alias_s = self._normalize_terms(llm_plan.get("scenario", []), vocab.get("scenario", []))
        goals, alias_g = self._normalize_terms(llm_plan.get("goals", []), vocab.get("goal", []))
        dimensions, alias_d = self._normalize_terms(llm_plan.get("dimensions", []), vocab.get("dimension", []))
        tasks, alias_t = self._normalize_terms(llm_plan.get("tasks", []), vocab.get("task", []))
        methods, alias_m = self._normalize_terms(llm_plan.get("methods", []), vocab.get("method", []))

        plan = {
            "scenario": scenario,
            "goals": goals,
            "dimensions": dimensions,
            "tasks": tasks,
            "methods": methods,
            "retrieval_hints": {
                "keywords": sorted(set([str(x).strip() for x in (llm_plan.get("retrieval_hints", {}) or {}).get("keywords", []) if str(x).strip()])),
                "exclude": sorted(set([str(x).strip() for x in (llm_plan.get("retrieval_hints", {}) or {}).get("exclude", []) if str(x).strip()])),
                "time_terms": sorted(set([str(x).strip() for x in (llm_plan.get("retrieval_hints", {}) or {}).get("time_terms", []) if str(x).strip()])),
            },
            "route": {
                "steps": [
                    {"stage": "scenario", "items": scenario},
                    {"stage": "goal", "items": goals},
                    {"stage": "dimension", "items": dimensions},
                    {"stage": "task", "items": tasks},
                    {"stage": "method", "items": methods},
                ]
            },
            "next_edges": llm_plan.get("next_edges", []),
        }

        next_writeback = {"mode": "whitelist_only", "threshold": self.next_threshold, "written_count": 0, "filtered_count": 0, "failed_count": 0, "errors": []}
        try:
            self._materialize_planning_graph(plan)
            next_writeback = self._apply_next_whitelist(tasks)
        except Exception as exc:
            log_error(LOGGER, f"Planning graph writeback failed: {exc}", "PlanningGraph")
            next_writeback["errors"] = [str(exc)]
            next_writeback["failed_count"] = 1

        return {
            "retrieval_plan": {
                "scenario": scenario,
                "goals": goals,
                "dimensions": dimensions,
                "tasks": tasks,
                "methods": methods,
                "retrieval_hints": plan["retrieval_hints"],
                "route": plan["route"],
            },
            "plan_trace": {
                "alias_hits": alias_s + alias_g + alias_d + alias_t + alias_m,
                "normalized_terms": {
                    "scenario": scenario,
                    "goals": goals,
                    "dimensions": dimensions,
                    "tasks": tasks,
                    "methods": methods,
                },
                "retrieval_hints_merged": plan["retrieval_hints"],
                "llm_plan_raw": llm_plan,
            },
            "next_writeback": next_writeback,
        }
