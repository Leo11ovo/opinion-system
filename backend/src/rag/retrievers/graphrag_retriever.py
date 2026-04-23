"""GraphRAG retriever backed by Neo4j finding-centric search."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from src.graph.config import get_graph_config
from src.graph.neo4j_client import get_session


class GraphRAGRetriever:
    """Retrieve finding-centric evidence from the graph."""

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        try:
            from src.utils.rag.embedding import get_sync_client

            client, model, _ = get_sync_client()
            query_vec = client.embeddings.create(
                model=model, input=[(query or "").replace("\n", " ")]
            ).data[0].embedding
        except Exception:
            return []

        seed_k = max(int(top_k) + 1, 6)
        terms = [
            t.strip()
            for t in re.split(r"[\s,，。；;、:：？?！!（）()【】\[\]\"'“”]+", query or "")
            if len(t.strip()) >= 2
        ]
        years = re.findall(r"20\d{2}", query or "")
        dedup_terms: List[str] = []
        seen_terms = set()
        for token in years + terms:
            key = token.lower()
            if key in seen_terms:
                continue
            seen_terms.add(key)
            dedup_terms.append(token)
            if len(dedup_terms) >= 12:
                break
        terms = dedup_terms or [str(query or "").strip()]

        def _run_query_on_db(cypher: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
            cfg_db = str(get_graph_config().get("database") or "").strip()
            db_candidates: List[Optional[str]] = []
            for name in (cfg_db, "opinion-report", "opinion", None):
                if name in db_candidates:
                    continue
                db_candidates.append(name)
            for db_name in db_candidates:
                try:
                    if db_name:
                        with get_session(database=db_name) as session:
                            rows = session.run(cypher, **params).data()
                    else:
                        with get_session() as session:
                            rows = session.run(cypher, **params).data()
                    if rows:
                        return rows
                except Exception:
                    continue
            return []

        idx_rows = _run_query_on_db(
            "SHOW VECTOR INDEXES YIELD name, labelsOrTypes, properties, state "
            "WHERE state='ONLINE' RETURN name, labelsOrTypes, properties",
            {},
        )
        vector_index_by_label: Dict[str, str] = {}
        for row in idx_rows:
            name = str(row.get("name") or "")
            labels = row.get("labelsOrTypes") or []
            props = [str(x) for x in (row.get("properties") or [])]
            if "embedding" not in props:
                continue
            for lb in labels:
                label = str(lb or "")
                if label in {"Finding", "Claim", "Entity", "Chunk", "Topic", "Event"} and label not in vector_index_by_label:
                    vector_index_by_label[label] = name

        def _vector_seed_query(label: str) -> str:
            return f"""
            CALL db.index.vector.queryNodes($index_name, $k, $qv)
            YIELD node, score
            WHERE node:{label}
            RETURN elementId(node) AS eid,
                   coalesce(node.id, node.name, elementId(node)) AS node_id,
                   coalesce(node.title, node.statement, node.content, node.name, node.text, '') AS text,
                   score
            LIMIT $k
            """

        def _lexical_seed_query(label: str) -> str:
            return f"""
            MATCH (n:{label})
            WHERE any(term IN $terms WHERE toLower(coalesce(n.title, n.statement, n.content, n.name, n.text, '')) CONTAINS toLower(term))
            RETURN elementId(n) AS eid,
                   coalesce(n.id, n.name, elementId(n)) AS node_id,
                   coalesce(n.title, n.statement, n.content, n.name, n.text, '') AS text,
                   0.0 AS score
            LIMIT $k
            """

        def _expand_seed_to_finding_eids(label: str, seed_eid: str) -> List[str]:
            q_map = {
                "Finding": "MATCH (f:Finding) WHERE elementId(f)=$eid RETURN elementId(f) AS feid",
                "Claim": "MATCH (c:Claim) WHERE elementId(c)=$eid MATCH (f:Finding)-[:DERIVED_FROM]->(c) RETURN elementId(f) AS feid",
                "Chunk": "MATCH (ch:Chunk) WHERE elementId(ch)=$eid MATCH (f:Finding)-[:SUPPORTED_BY_CHUNK]->(ch) RETURN elementId(f) AS feid",
                "Entity": "MATCH (e:Entity) WHERE elementId(e)=$eid MATCH (c:Claim)-[:MENTIONS]->(e) MATCH (f:Finding)-[:DERIVED_FROM]->(c) RETURN elementId(f) AS feid",
                "Topic": "MATCH (t:Topic) WHERE elementId(t)=$eid MATCH (f:Finding)-[:ABOUT_TOPIC]->(t) RETURN elementId(f) AS feid",
                "Event": "MATCH (ev:Event) WHERE elementId(ev)=$eid MATCH (f:Finding)-[:SUPPORTED_BY_EVENT]->(ev) RETURN elementId(f) AS feid",
            }
            cypher = q_map.get(label)
            if not cypher:
                return []
            rows = _run_query_on_db(cypher, {"eid": seed_eid})
            return [str(r.get("feid") or "") for r in rows if str(r.get("feid") or "")]

        def _expand_from_finding(finding_eid: str) -> Dict[str, Any]:
            rows = _run_query_on_db(
                """
                MATCH (f:Finding) WHERE elementId(f)=$eid
                OPTIONAL MATCH (f)-[:ABOUT_TOPIC]->(t:Topic)
                OPTIONAL MATCH (f)-[:ABOUT_PLATFORM]->(pl:Platform)
                OPTIONAL MATCH (f)-[:SUPPORTED_BY_EVENT]->(ev:Event)
                OPTIONAL MATCH (f)-[:DERIVED_FROM]->(c:Claim)
                OPTIONAL MATCH (f)-[:SUPPORTED_BY_CHUNK]->(ch:Chunk)
                OPTIONAL MATCH (f)-[:SUPPORTED_BY_POST]->(p:Post)
                OPTIONAL MATCH (r:Recommendation)-[:RESPONDS_TO]->(f)
                RETURN
                  f.id AS finding_id,
                  f.title AS finding_title,
                  f.statement AS finding_statement,
                  collect(DISTINCT t.name)[0..3] AS topics,
                  collect(DISTINCT pl.name)[0..3] AS platforms,
                  collect(DISTINCT ev.name)[0..3] AS events,
                  collect(DISTINCT c.id)[0..3] AS claim_ids,
                  collect(DISTINCT c.content)[0..3] AS claims,
                  collect(DISTINCT ch.id)[0..3] AS chunk_ids,
                  collect(DISTINCT p.id)[0..3] AS post_ids,
                  collect(DISTINCT p.title)[0..3] AS post_titles,
                  collect(DISTINCT r.action)[0..3] AS recommendations
                """,
                {"eid": finding_eid},
            )
            return dict(rows[0]) if rows else {}

        def _score(item: Dict[str, Any], seed_score: float) -> Tuple[float, float, float]:
            text = " ".join(
                [
                    str(item.get("finding_title") or ""),
                    str(item.get("finding_statement") or ""),
                    " ".join(item.get("topics") or []),
                    " ".join(item.get("platforms") or []),
                ]
            ).lower()
            graph_score = min(
                1.0,
                0.25 * (1 if item.get("topics") else 0)
                + 0.25 * (1 if item.get("platforms") else 0)
                + 0.25 * (1 if item.get("events") else 0)
                + 0.25 * (1 if item.get("recommendations") else 0),
            )
            evidence_score = min(
                1.0,
                0.4 * (1 if item.get("claim_ids") else 0)
                + 0.3 * (1 if item.get("chunk_ids") else 0)
                + 0.3 * (1 if item.get("post_ids") else 0),
            )
            lexical = 0.0
            for token in terms:
                if token.lower() in text:
                    lexical += 0.08
            lexical = min(0.4, lexical)
            semantic_score = max(0.0, min(1.0, seed_score)) + lexical
            final = 0.55 * semantic_score + 0.30 * graph_score + 0.15 * evidence_score
            return round(final, 4), round(graph_score, 4), round(evidence_score, 4)

        labels = ["Finding", "Claim", "Entity", "Chunk", "Topic", "Event"]
        seeds: List[Dict[str, Any]] = []
        for label in labels:
            if label in vector_index_by_label:
                rows = _run_query_on_db(
                    _vector_seed_query(label),
                    {"index_name": vector_index_by_label[label], "k": int(seed_k), "qv": query_vec},
                )
                for row in rows:
                    seeds.append(
                        {
                            "label": label,
                            "eid": row.get("eid"),
                            "node_id": row.get("node_id"),
                            "score": float(row.get("score") or 0.0),
                            "mode": "vector",
                        }
                    )
            else:
                rows = _run_query_on_db(_lexical_seed_query(label), {"terms": terms, "k": int(seed_k)})
                for row in rows:
                    seeds.append(
                        {
                            "label": label,
                            "eid": row.get("eid"),
                            "node_id": row.get("node_id"),
                            "score": 0.0,
                            "mode": "lexical",
                        }
                    )

        best_seed_by_finding: Dict[str, Dict[str, Any]] = {}
        for seed in seeds:
            for feid in _expand_seed_to_finding_eids(str(seed.get("label") or ""), str(seed.get("eid") or "")):
                current = best_seed_by_finding.get(feid)
                if not current or float(seed.get("score") or 0.0) > float(current.get("score") or 0.0):
                    best_seed_by_finding[feid] = seed

        results: List[Dict[str, Any]] = []
        for feid, seed in best_seed_by_finding.items():
            expanded = _expand_from_finding(feid)
            if not expanded:
                continue
            final, g_score, e_score = _score(expanded, float(seed.get("score") or 0.0))
            expanded["score"] = final
            expanded["graph_score"] = g_score
            expanded["evidence_score"] = e_score
            expanded["seed"] = {
                "label": seed.get("label"),
                "node_id": seed.get("node_id"),
                "seed_score": round(float(seed.get("score") or 0.0), 4),
                "mode": seed.get("mode"),
            }
            results.append(expanded)

        results.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

        dedup_map: Dict[str, Dict[str, Any]] = {}
        for item in results:
            claim_key = (item.get("claim_ids") or [""])[0] if isinstance(item.get("claim_ids"), list) else ""
            post_key = (item.get("post_ids") or [""])[0] if isinstance(item.get("post_ids"), list) else ""
            dedup_key = f"{post_key}||{claim_key}"
            current = dedup_map.get(dedup_key)
            if not current:
                clone = dict(item)
                clone["related_findings"] = []
                dedup_map[dedup_key] = clone
                continue
            if float(item.get("score") or 0.0) > float(current.get("score") or 0.0):
                folded = {
                    "finding_id": current.get("finding_id"),
                    "finding_title": current.get("finding_title"),
                    "finding_statement": current.get("finding_statement"),
                    "score": current.get("score"),
                }
                clone = dict(item)
                clone["related_findings"] = [folded] + (current.get("related_findings") or [])
                dedup_map[dedup_key] = clone
            else:
                current.setdefault("related_findings", []).append(
                    {
                        "finding_id": item.get("finding_id"),
                        "finding_title": item.get("finding_title"),
                        "finding_statement": item.get("finding_statement"),
                        "score": item.get("score"),
                    }
                )

        deduped_results = list(dedup_map.values())
        deduped_results.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
        return deduped_results[: max(1, int(top_k))]
