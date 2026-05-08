"""GraphRAG retriever backed by Neo4j finding-centric search."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from src.graph.config import get_graph_config
from src.graph.neo4j_client import get_session

LOG = logging.getLogger(__name__)
CN_STOP_PHRASES = {
    "关于",
    "有关",
    "内容",
    "情况",
    "信息",
    "问题",
    "方面",
    "什么",
    "哪些",
    "介绍",
    "说明",
    "分析",
}
CN_QUERY_HINTS = {
    "内容": 0.1,
    "情况": 0.1,
    "信息": 0.1,
    "问题": 0.2,
    "风险": 0.35,
    "原因": 0.35,
    "趋势": 0.3,
    "建议": 0.35,
    "对策": 0.35,
}


class GraphRAGRetriever:
    """Retrieve finding-centric evidence from the graph."""

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        topic: str = "",
        *,
        return_diagnostics: bool = False,
    ) -> List[Dict[str, Any]] | Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        diagnostics: Dict[str, Any] = {
            "query": str(query or ""),
            "topic": str(topic or ""),
            "top_k": int(top_k),
            "embedding": {
                "attempted": True,
                "success": False,
                "model": "",
                "error": "",
            },
            "db_candidates": [],
            "vector_indexes": {},
            "seed_terms": [],
            "keyword_terms": [],
            "seed_counts": {},
            "seed_examples": {},
            "seed_total": 0,
            "expanded_finding_count": 0,
            "result_count": 0,
        }
        query_vec: Optional[List[float]] = None
        try:
            from src.utils.rag.embedding import get_sync_client

            client, model, _ = get_sync_client()
            diagnostics["embedding"]["model"] = str(model or "")
            query_vec = client.embeddings.create(
                model=model, input=[(query or "").replace("\n", " ")]
            ).data[0].embedding
            diagnostics["embedding"]["success"] = True
            LOG.info(
                "GraphRAG embedding ready query=%r topic=%r model=%s",
                query,
                topic,
                model,
            )
        except Exception as exc:
            query_vec = None
            diagnostics["embedding"]["error"] = str(exc)
            LOG.warning(
                "GraphRAG embedding failed; fallback to lexical query=%r topic=%r error=%s",
                query,
                topic,
                exc,
            )

        seed_k = max(int(top_k) + 1, 6)
        years = re.findall(r"20\d{2}", query or "")
        topic = str(topic or "").strip()
        terms, keyword_terms = self._build_seed_terms(query, years=years)
        diagnostics["seed_terms"] = terms
        diagnostics["keyword_terms"] = keyword_terms

        def _run_query_on_db(cypher: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
            cfg_db = str(get_graph_config().get("database") or "").strip()
            db_candidates: List[Optional[str]] = []
            for name in (cfg_db, "neo4j", "opinion-report", "opinion", None):
                if name in db_candidates:
                    continue
                db_candidates.append(name)
            diagnostics["db_candidates"] = [str(name or "<default>") for name in db_candidates]
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
        diagnostics["vector_indexes"] = dict(vector_index_by_label)

        def _text_expr(label: str, alias: str) -> str:
            if label == "Finding":
                return f"coalesce({alias}.title, '') + ' ' + coalesce({alias}.statement, '')"
            if label == "Claim":
                return f"coalesce({alias}.content, '')"
            if label == "Entity":
                return f"coalesce({alias}.name, '') + ' ' + coalesce({alias}.text, '') + ' ' + coalesce({alias}.content, '')"
            if label == "Chunk":
                return f"coalesce({alias}.content, '') + ' ' + coalesce({alias}.text, '')"
            if label == "Topic":
                return f"coalesce({alias}.name, '') + ' ' + coalesce({alias}.project, '')"
            if label == "Event":
                return f"coalesce({alias}.name, '') + ' ' + coalesce({alias}.summary, '')"
            if label == "Report":
                return f"coalesce({alias}.title, '') + ' ' + coalesce({alias}.summary, '') + ' ' + coalesce({alias}.topic, '')"
            if label == "Section":
                return f"coalesce({alias}.name, '') + ' ' + coalesce({alias}.summary, '')"
            if label == "Recommendation":
                return f"coalesce({alias}.title, '') + ' ' + coalesce({alias}.action, '')"
            if label == "Metric":
                return f"coalesce({alias}.name, '') + ' ' + coalesce({alias}.value, '') + ' ' + coalesce({alias}.unit, '')"
            return f"coalesce({alias}.name, '') + ' ' + coalesce({alias}.text, '')"

        def _vector_seed_query(label: str) -> str:
            if label == "Finding":
                where_clause = (
                    "AND ($topic = '' OR "
                    "coalesce(node.report_id, '') STARTS WITH ($topic + '_') OR "
                    "coalesce(node.id, '') STARTS WITH ($topic + '_'))"
                )
            elif label in {"Claim", "Chunk", "Entity"}:
                where_clause = "AND ($topic = '' OR coalesce(node.topic, '') = $topic)"
            elif label == "Topic":
                where_clause = "AND ($topic = '' OR coalesce(node.project, '') = $topic OR coalesce(node.id, '') STARTS WITH ($topic + '_'))"
            elif label == "Event":
                where_clause = "AND ($topic = '' OR coalesce(node.project, '') = $topic OR coalesce(node.topic_id, '') STARTS WITH ($topic + '_'))"
            else:
                where_clause = ""
            return f"""
            CALL db.index.vector.queryNodes($index_name, $k, $qv)
            YIELD node, score
            WHERE node:{label}
              {where_clause}
            RETURN elementId(node) AS eid,
                   coalesce(node.id, node.name, elementId(node)) AS node_id,
                   coalesce(node.title, node.statement, node.content, node.name, node.text, '') AS text,
                   score
            LIMIT $k
            """

        def _lexical_seed_query(label: str) -> str:
            if label == "Finding":
                topic_filter = (
                    "AND ($topic = '' OR "
                    "coalesce(n.report_id, '') STARTS WITH ($topic + '_') OR "
                    "coalesce(n.id, '') STARTS WITH ($topic + '_'))"
                )
            elif label in {"Claim", "Chunk", "Entity"}:
                topic_filter = "AND ($topic = '' OR coalesce(n.topic, '') = $topic)"
            elif label == "Topic":
                topic_filter = "AND ($topic = '' OR coalesce(n.project, '') = $topic OR coalesce(n.id, '') STARTS WITH ($topic + '_'))"
            elif label == "Event":
                topic_filter = "AND ($topic = '' OR coalesce(n.project, '') = $topic OR coalesce(n.topic_id, '') STARTS WITH ($topic + '_'))"
            elif label == "Report":
                topic_filter = "AND ($topic = '' OR coalesce(n.topic, '') = $topic)"
            elif label == "Section":
                topic_filter = (
                    "AND ($topic = '' OR EXISTS { "
                    "MATCH (r:Report)-[:HAS_SECTION]->(n) "
                    "WHERE coalesce(r.topic, '') = $topic "
                    "})"
                )
            elif label == "Recommendation":
                topic_filter = (
                    "AND ($topic = '' OR EXISTS { "
                    "MATCH (r:Report)-[:HAS_RECOMMENDATION]->(n) "
                    "WHERE coalesce(r.topic, '') = $topic "
                    "})"
                )
            elif label == "Metric":
                topic_filter = (
                    "AND ($topic = '' OR EXISTS { "
                    "MATCH (f:Finding)-[:SUPPORTED_BY]->(n) "
                    "WHERE coalesce(f.report_id, '') STARTS WITH ($topic + '_') "
                    "})"
                )
            else:
                topic_filter = ""
            return f"""
            MATCH (n:{label})
            WITH n, toLower({_text_expr(label, 'n')}) AS text_value
            WITH n, text_value,
                 reduce(score = 0.0, term IN $terms |
                    score +
                    CASE
                      WHEN text_value CONTAINS toLower(term) THEN
                        CASE
                          WHEN size(term) >= 6 THEN 1.4
                          WHEN size(term) >= 4 THEN 1.0
                          WHEN size(term) = 3 THEN 0.65
                          ELSE 0.35
                        END
                      ELSE 0.0
                    END
                 ) AS lexical_score
            WHERE lexical_score > 0
              {topic_filter}
            RETURN elementId(n) AS eid,
                   coalesce(n.id, n.name, elementId(n)) AS node_id,
                   {_text_expr(label, 'n')} AS text,
                   lexical_score AS score
            ORDER BY score DESC
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
                "Report": "MATCH (r:Report) WHERE elementId(r)=$eid MATCH (r)-[:HAS_SECTION]->(:Section)-[:HAS_FINDING]->(f:Finding) RETURN DISTINCT elementId(f) AS feid",
                "Section": "MATCH (s:Section) WHERE elementId(s)=$eid MATCH (s)-[:HAS_FINDING]->(f:Finding) RETURN DISTINCT elementId(f) AS feid",
                "Recommendation": "MATCH (r:Recommendation) WHERE elementId(r)=$eid MATCH (r)-[:RESPONDS_TO]->(f:Finding) RETURN DISTINCT elementId(f) AS feid",
                "Metric": "MATCH (m:Metric) WHERE elementId(m)=$eid MATCH (f:Finding)-[:SUPPORTED_BY]->(m) RETURN DISTINCT elementId(f) AS feid",
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
            # Year-based boosting: if query contains a year (e.g. "2024"),
            # give +0.1 boost to results that mention that year.
            year_boost = 0.0
            if years:
                for yr in years:
                    if yr in text:
                        year_boost = 0.1
                        break
            semantic_score = max(0.0, min(1.0, seed_score)) + lexical + year_boost
            final = 0.55 * semantic_score + 0.30 * graph_score + 0.15 * evidence_score
            return round(final, 4), round(graph_score, 4), round(evidence_score, 4)

        labels = ["Finding", "Claim", "Entity", "Chunk", "Topic", "Event", "Report", "Section", "Recommendation", "Metric"]
        seeds: List[Dict[str, Any]] = []
        for label in labels:
            if label in vector_index_by_label and query_vec is not None:
                rows = _run_query_on_db(
                    _vector_seed_query(label),
                    {"index_name": vector_index_by_label[label], "k": int(seed_k), "qv": query_vec, "topic": topic},
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
                rows = _run_query_on_db(_lexical_seed_query(label), {"terms": terms, "k": int(seed_k), "topic": topic})
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
            diagnostics["seed_counts"][label] = len(rows)
            diagnostics["seed_examples"][label] = [
                {
                    "node_id": str(row.get("node_id") or ""),
                    "score": float(row.get("score") or 0.0),
                    "text": str(row.get("text") or "")[:160],
                }
                for row in rows[:3]
            ]

        diagnostics["seed_total"] = len(seeds)
        LOG.info(
            "GraphRAG seeds query=%r topic=%r total=%s counts=%s",
            query,
            topic,
            diagnostics["seed_total"],
            diagnostics["seed_counts"],
        )

        best_seed_by_finding: Dict[str, Dict[str, Any]] = {}
        for seed in seeds:
            for feid in _expand_seed_to_finding_eids(str(seed.get("label") or ""), str(seed.get("eid") or "")):
                current = best_seed_by_finding.get(feid)
                if not current or float(seed.get("score") or 0.0) > float(current.get("score") or 0.0):
                    best_seed_by_finding[feid] = seed
        diagnostics["expanded_finding_count"] = len(best_seed_by_finding)
        LOG.info(
            "GraphRAG expanded findings query=%r topic=%r count=%s",
            query,
            topic,
            diagnostics["expanded_finding_count"],
        )

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
        final_results = deduped_results[: max(1, int(top_k))]
        diagnostics["result_count"] = len(final_results)
        diagnostics["result_examples"] = [
            {
                "finding_id": str(item.get("finding_id") or ""),
                "finding_title": str(item.get("finding_title") or ""),
                "score": float(item.get("score") or 0.0),
                "seed": item.get("seed") or {},
            }
            for item in final_results[:5]
        ]
        LOG.info(
            "GraphRAG finished query=%r topic=%r results=%s",
            query,
            topic,
            diagnostics["result_count"],
        )
        if return_diagnostics:
            return final_results, diagnostics
        return final_results

    @staticmethod
    def _is_junk_ngram(gram: str) -> bool:
        if len(gram) <= 2:
            return True
        # Preserve 4-digit years (20XX) — these are valid lexical search terms
        if re.fullmatch(r"20\d{2}", gram):
            return False
        # Pure digits: "123", "024"
        if re.fullmatch(r"[\d]+", gram):
            return True
        # Mixed digit-only fragments: e.g. "XR12" (digit-heavy alnum), "12XR"
        if re.fullmatch(r"[\dA-Za-z]+", gram):
            digit_count = sum(c.isdigit() for c in gram)
            if digit_count >= len(gram) - 1:
                return True
        return False

    def _build_seed_terms(self, query: str, years: Optional[List[str]] = None) -> Tuple[List[str], List[str]]:
        raw_query = str(query or "").strip()
        tokens = [
            t.strip()
            for t in re.split(r"[\s,，。；;、:：？?！!（）()【】\[\]\"'“”]+", raw_query)
            if len(t.strip()) >= 2
        ]
        candidates: List[str] = []
        keyword_terms: List[str] = []
        if raw_query:
            candidates.append(raw_query)
        candidates.extend(years or [])
        candidates.extend(tokens)

        # Chinese queries often arrive as one full sentence without spaces.
        # Extract shorter keyword-like spans so lexical fallback can hit report titles,
        # section names and finding statements.
        compact_cn = re.sub(r"[^\u4e00-\u9fff0-9a-zA-Z]+", "", raw_query)
        if compact_cn:
            reduced = compact_cn
            for phrase in sorted(CN_STOP_PHRASES, key=len, reverse=True):
                reduced = reduced.replace(phrase, " ")
            for token in re.split(r"\s+", reduced):
                token = token.strip()
                if len(token) >= 2:
                    candidates.append(token)
                    keyword_terms.append(token)
                    if len(token) > 4:
                        for size in (2, 3, 4):
                            for idx in range(0, len(token) - size + 1):
                                gram = token[idx : idx + size]
                                if self._is_junk_ngram(gram):
                                    continue
                                candidates.append(gram)
                                if size >= 3:
                                    keyword_terms.append(gram)

        # Add lightweight semantic hints from common Chinese question intents.
        for hint, _weight in CN_QUERY_HINTS.items():
            if hint in raw_query:
                continue
            for token in list(keyword_terms):
                if hint in token:
                    candidates.append(hint)
                    keyword_terms.append(hint)
                    break

        dedup_terms: List[str] = []
        seen_terms = set()
        for token in candidates:
            key = token.lower()
            if key in seen_terms:
                continue
            seen_terms.add(key)
            dedup_terms.append(token)
            if len(dedup_terms) >= 20:
                break
        dedup_keywords: List[str] = []
        seen_keywords = set()
        for token in keyword_terms:
            key = token.lower()
            if key in seen_keywords:
                continue
            seen_keywords.add(key)
            dedup_keywords.append(token)
            if len(dedup_keywords) >= 12:
                break
        base_terms = dedup_terms or ([raw_query] if raw_query else [])
        return base_terms, dedup_keywords
