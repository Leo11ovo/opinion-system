"""Expert retriever with planning-graph pre-routing."""
from __future__ import annotations

from typing import Any, Dict, List
import re

from src.graph.neo4j_client import get_session
from src.rag.planner import PlanningGraphEngine
from src.utils.logging.logging import log_error, setup_logger
from src.utils.rag.embedding import get_sync_client

logger = setup_logger("ExpertRetriever", "default")


class ExpertRetriever:
    def __init__(self) -> None:
        self.client, self.model, self.dimension = get_sync_client()
        self.planner = PlanningGraphEngine()

    def _get_embedding(self, text: str) -> List[float]:
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=[text.replace("\n", " ")],
            )
            return response.data[0].embedding
        except Exception as e:
            log_error(logger, f"Embedding generation failed: {e}", "ExpertRetriever")
            return []

    def _query_expert_nodes(self, query_vec: List[float], top_k: int) -> List[Dict[str, Any]]:
        cypher_query = """
        CALL db.index.vector.queryNodes($index_name, $top_k, $query_vec)
        YIELD node, score
        WHERE score > 0.3
        OPTIONAL MATCH (node) WHERE NOT node:ExpertChunk
        WITH node, score, labels(node) AS labels,
             CASE WHEN NOT node:ExpertChunk THEN node.name ELSE NULL END AS entity_name,
             CASE WHEN NOT node:ExpertChunk THEN node.description ELSE node.content END AS text_content
        OPTIONAL MATCH (node)-[r]->(related)
        WITH node, score, labels, entity_name, text_content,
             collect(DISTINCT {label: labels(related)[0], name: related.name})[..5] AS connections
        OPTIONAL MATCH (doc)-[:HAS_CHUNK]->(node)
        RETURN labels, entity_name, text_content, score, connections, doc.name AS source_doc
        ORDER BY score DESC
        """
        index_candidates = [
            "expert_entity_embedding_index",
            "expert_embedding_index",
            "expert_chunk_embedding_index",
        ]
        records: List[Dict[str, Any]] = []

        def _run_with_session(session_obj) -> List[Dict[str, Any]]:
            # Query available vector indexes first to avoid calling non-existent index names.
            available = set()
            try:
                rows = session_obj.run("SHOW VECTOR INDEXES YIELD name RETURN name").data()
                for row in rows:
                    n = str(row.get("name") or "").strip()
                    if n:
                        available.add(n)
            except Exception:
                # If listing indexes fails, fallback to candidate probing.
                available = set(index_candidates)

            candidates = [name for name in index_candidates if name in available]
            if not candidates:
                return []

            last_exc: Exception | None = None
            for index_name in candidates:
                try:
                    data = session_obj.run(
                        cypher_query,
                        {"index_name": index_name, "top_k": top_k, "query_vec": query_vec},
                    ).data()
                    if data:
                        return data
                except Exception as exc:  # keep trying other index names
                    last_exc = exc
                    continue
            if last_exc:
                raise last_exc
            return []

        # Expert graph should only use the dedicated expert DB.
        db_candidates = ["opinion-expert"]
        last_exc: Exception | None = None
        for db_name in db_candidates:
            try:
                if db_name:
                    with get_session(database=db_name) as session:
                        records = _run_with_session(session)
                else:
                    with get_session() as session:
                        records = _run_with_session(session)
                if records:
                    return records
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc and not records:
            log_error(logger, f"Expert query fallback exhausted: {last_exc}", "ExpertRetriever")
        return records

    @staticmethod
    def _label_of(row: Dict[str, Any]) -> str:
        labels = [str(x) for x in (row.get("labels") or [])]
        for key in ("Scenario", "Goal", "Task", "Method", "Dimension"):
            if key in labels:
                return key
        return labels[0] if labels else "ExpertNode"

    def _expand_structured_nodes(self, seeds: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        seed_names = [str(x.get("entity_name") or "").strip() for x in seeds if str(x.get("entity_name") or "").strip()]
        if not seed_names:
            return seeds
        cypher = """
        UNWIND $seed_names AS seed_name
        MATCH (seed:ExpertNode {name: seed_name})
        MATCH p=(seed)-[*0..3]-(n:ExpertNode)
        WHERE ANY(l IN labels(n) WHERE l IN ['Scenario','Goal','Task','Method','Dimension'])
        OPTIONAL MATCH (n)-[r]->(related)
        WITH n, labels(n) AS labels,
             collect(DISTINCT {label: labels(related)[0], name: related.name})[..8] AS connections
        RETURN DISTINCT labels,
               n.name AS entity_name,
               coalesce(n.description, n.content, '') AS text_content,
               0.2 AS score,
               connections,
               NULL AS source_doc
        LIMIT $limit
        """
        try:
            with get_session(database="opinion-expert") as session:
                expanded = session.run(cypher, seed_names=seed_names, limit=max(8, int(top_k) * 4)).data()
        except Exception as e:
            log_error(logger, f"Expert structured expansion failed: {e}", "ExpertRetriever")
            return seeds

        # Full-chain expansion by relation semantics.
        chain_query = """
        UNWIND $seed_names AS seed_name
        MATCH (seed:ExpertNode {name: seed_name})
        OPTIONAL MATCH (s:ExpertNode:Scenario)-[:HAS_GOAL]->(g:ExpertNode:Goal)
        OPTIONAL MATCH (g)-[:REQUIRES_TASK]->(t:ExpertNode:Task)
        OPTIONAL MATCH (t)-[:SOLVED_BY]->(m:ExpertNode:Method)
        OPTIONAL MATCH (g)-[:FOCUS_ON]->(d:ExpertNode:Dimension)
        WITH seed, s, g, t, m, d
        WHERE s IS NOT NULL AND (
          seed = s OR seed = g OR seed = t OR seed = m OR seed = d
          OR (seed)-[*1..2]-(g)
          OR (seed)-[*1..2]-(t)
          OR (seed)-[*1..2]-(m)
          OR (seed)-[*1..2]-(d)
        )
        UNWIND [s,g,t,m,d] AS n
        WITH DISTINCT n
        WHERE n IS NOT NULL
        OPTIONAL MATCH (n)-[r]->(related)
        RETURN labels(n) AS labels,
               n.name AS entity_name,
               coalesce(n.description, n.content, '') AS text_content,
               0.25 AS score,
               collect(DISTINCT {label: labels(related)[0], name: related.name})[..8] AS connections,
               NULL AS source_doc
        LIMIT $limit
        """
        chain_rows: List[Dict[str, Any]] = []
        try:
            with get_session(database="opinion-expert") as session:
                chain_rows = session.run(chain_query, seed_names=seed_names, limit=max(16, int(top_k) * 8)).data()
        except Exception as e:
            log_error(logger, f"Expert full-chain expansion failed: {e}", "ExpertRetriever")

        merged = list(seeds) + (expanded or []) + (chain_rows or [])
        dedup: Dict[str, Dict[str, Any]] = {}
        for row in merged:
            name = str(row.get("entity_name") or "").strip()
            labels = ",".join([str(x) for x in (row.get("labels") or [])])
            key = f"{name}::{labels}"
            if not name:
                continue
            if key not in dedup:
                dedup[key] = row
                continue
            # keep richer text / higher score
            old = dedup[key]
            old_text = str(old.get("text_content") or "")
            new_text = str(row.get("text_content") or "")
            if len(new_text) > len(old_text) or float(row.get("score") or 0.0) > float(old.get("score") or 0.0):
                dedup[key] = row
        rows = list(dedup.values())
        # Balanced ordering for full-chain readability.
        order = {"Scenario": 0, "Goal": 1, "Task": 2, "Method": 3, "Dimension": 4}
        rows.sort(key=lambda r: (order.get(self._label_of(r), 9), -(float(r.get("score") or 0.0))))
        return rows

    def _select_balanced_results(self, rows: List[Dict[str, Any]], limit: int = 12) -> List[Dict[str, Any]]:
        if not rows:
            return []
        buckets: Dict[str, List[Dict[str, Any]]] = {"Scenario": [], "Goal": [], "Task": [], "Method": [], "Dimension": [], "Other": []}
        for row in rows:
            lbl = self._label_of(row)
            if lbl not in buckets:
                lbl = "Other"
            buckets[lbl].append(row)

        picked: List[Dict[str, Any]] = []
        # Keep chain coverage first.
        for key in ("Scenario", "Goal", "Task", "Method", "Dimension"):
            if buckets[key]:
                picked.append(buckets[key].pop(0))
                if len(picked) >= limit:
                    return picked[:limit]

        # Fill remaining with priority order.
        for key in ("Task", "Method", "Dimension", "Goal", "Scenario", "Other"):
            for row in buckets[key]:
                picked.append(row)
                if len(picked) >= limit:
                    return picked[:limit]
        return picked[:limit]

    def _query_expert_nodes_lexical(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        terms = [t.strip() for t in re.split(r"[\s,，。；;、:：？?！!]+", str(query or "")) if len(t.strip()) >= 2]
        if not terms:
            terms = [str(query or "").strip()]
        cypher = """
        MATCH (node:ExpertNode)
        WHERE ANY(term IN $terms WHERE
            toLower(coalesce(node.name, '')) CONTAINS toLower(term)
            OR toLower(coalesce(node.description, '')) CONTAINS toLower(term)
        )
        OPTIONAL MATCH (node)-[r]->(related)
        RETURN labels(node) AS labels,
               node.name AS entity_name,
               node.description AS text_content,
               0.1 AS score,
               collect(DISTINCT {label: labels(related)[0], name: related.name})[..5] AS connections,
               NULL AS source_doc
        LIMIT $top_k
        """
        try:
            with get_session(database="opinion-expert") as session:
                return session.run(cypher, terms=terms, top_k=max(1, int(top_k))).data()
        except Exception:
            return []

    @staticmethod
    def _filter_by_plan(results: List[Dict[str, Any]], plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        scenarios = {str(x).strip() for x in plan.get("scenario", []) if str(x).strip()}
        goals = {str(x).strip() for x in plan.get("goals", []) if str(x).strip()}
        methods = {str(x).strip() for x in plan.get("methods", []) if str(x).strip()}
        dimensions = {str(x).strip() for x in plan.get("dimensions", []) if str(x).strip()}
        tasks = {str(x).strip() for x in plan.get("tasks", []) if str(x).strip()}
        all_terms = scenarios | goals | methods | dimensions | tasks
        if not all_terms:
            return results

        filtered: List[Dict[str, Any]] = []
        for row in results:
            name = str(row.get("entity_name") or "").strip()
            content = str(row.get("text_content") or "")
            conn_names = {str(c.get("name") or "").strip() for c in (row.get("connections") or []) if c}
            hit = False
            if name and name in all_terms:
                hit = True
            if not hit and (conn_names & all_terms):
                hit = True
            if not hit:
                # lightweight semantic fallback
                for token in list(all_terms):
                    if token and (token in content):
                        hit = True
                        break
            if hit:
                filtered.append(row)
        if not filtered:
            return results

        # Keep chain coverage: preserve at least one node for each core label if present.
        def _main_label(row: Dict[str, Any]) -> str:
            labels = [str(x) for x in (row.get("labels") or [])]
            for key in ("Scenario", "Goal", "Task", "Method", "Dimension"):
                if key in labels:
                    return key
            return ""

        covered = {_main_label(r) for r in filtered}
        for row in results:
            lbl = _main_label(row)
            if not lbl:
                continue
            if lbl not in covered:
                filtered.append(row)
                covered.add(lbl)
        return filtered

    @staticmethod
    def _format_guidance(results: List[Dict[str, Any]], plan_payload: Dict[str, Any]) -> str:
        if not results:
            return ""

        guidance_text = "### 专家库指导 (Expert Guidance)\n"
        retrieval_plan = plan_payload.get("retrieval_plan", {})
        route = retrieval_plan.get("route", {}).get("steps", [])
        if route:
            guidance_text += "#### 检索路线 (Planning Graph)\n"
            for step in route:
                stage = step.get("stage", "")
                items = ", ".join(step.get("items", []))
                guidance_text += f"- {stage}: {items}\n"

        entities = [r for r in results if "ExpertChunk" not in (r.get("labels") or [])]
        chunks = [r for r in results if "ExpertChunk" in (r.get("labels") or [])]

        if entities:
            guidance_text += "#### 核心方法与理论：\n"
            for ent in entities:
                labels = ent.get("labels") or []
                label_zh = labels[0] if labels else "ExpertNode"
                guidance_text += f"- **{ent.get('entity_name') or '未知'}** ({label_zh}): {ent.get('text_content') or ''}\n"
                connections = ent.get("connections") or []
                if connections:
                    conn_str = ", ".join([str(c.get("name") or "") for c in connections if c.get("name")])
                    if conn_str:
                        guidance_text += f"  - 相关延伸: {conn_str}\n"

        if chunks:
            guidance_text += "\n#### 相关文献片段：\n"
            for i, chunk in enumerate(chunks[:6], 1):
                source = chunk.get("source_doc") or "专家文献"
                text = str(chunk.get("text_content") or "")
                guidance_text += f"{i}. [{source}] {text[:300]}...\n"

        return guidance_text

    def retrieve_guidance_payload(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        query_vec = self._get_embedding(query)
        if not query_vec:
            return {
                "expert_guidance": "",
                "expert_results": [],
                "retrieval_plan": {},
                "plan_trace": {"error": "embedding_failed"},
                "next_writeback": {"written_count": 0, "filtered_count": 0, "failed_count": 1, "errors": ["embedding_failed"]},
            }

        try:
            plan_payload = self.planner.generate_plan(query)
        except Exception as e:
            log_error(logger, f"Planning graph generation failed: {e}", "ExpertRetriever")
            plan_payload = {
                "retrieval_plan": {},
                "plan_trace": {"error": str(e)},
                "next_writeback": {"written_count": 0, "filtered_count": 0, "failed_count": 1, "errors": [str(e)]},
            }

        try:
            raw_results = self._query_expert_nodes(query_vec=query_vec, top_k=top_k)
            if not raw_results:
                raw_results = self._query_expert_nodes_lexical(query=query, top_k=top_k)
            raw_results = self._expand_structured_nodes(raw_results, top_k=top_k)
        except Exception as e:
            log_error(logger, f"Expert search failed: {e}", "ExpertRetriever")
            return {
                "expert_guidance": "",
                "expert_results": [],
                "retrieval_plan": plan_payload.get("retrieval_plan", {}),
                "plan_trace": plan_payload.get("plan_trace", {}),
                "next_writeback": plan_payload.get("next_writeback", {}),
            }

        filtered_results = self._filter_by_plan(raw_results, plan_payload.get("retrieval_plan", {}))
        guidance = self._format_guidance(filtered_results, plan_payload)
        compact_results: List[Dict[str, Any]] = []
        selected_rows = self._select_balanced_results(filtered_results, limit=12)
        for row in selected_rows:
            compact_results.append(
                {
                    "labels": row.get("labels") or [],
                    "entity_name": row.get("entity_name"),
                    "text_content": row.get("text_content"),
                    "score": row.get("score"),
                    "connections": row.get("connections") or [],
                    "source_doc": row.get("source_doc"),
                }
            )
        return {
            "expert_guidance": guidance,
            "expert_results": compact_results,
            "retrieval_plan": plan_payload.get("retrieval_plan", {}),
            "plan_trace": plan_payload.get("plan_trace", {}),
            "next_writeback": plan_payload.get("next_writeback", {}),
        }

    def retrieve_guidance(self, query: str, top_k: int = 3) -> str:
        payload = self.retrieve_guidance_payload(query=query, top_k=top_k)
        return str(payload.get("expert_guidance") or "")


if __name__ == "__main__":
    retriever = ExpertRetriever()
    data = retriever.retrieve_guidance_payload("如何分析品牌危机中的负面情绪？")
    print(data.get("expert_guidance", ""))
    print(data.get("retrieval_plan", {}))
