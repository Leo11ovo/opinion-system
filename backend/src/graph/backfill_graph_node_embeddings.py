"""
Backfill Neo4j embeddings for graph nodes (Entity/Claim/Event/Topic/Finding)
and (re)create vector indexes per label.

Usage:
  python -m src.graph.backfill_graph_node_embeddings --database opinion --labels Entity,Claim,Event,Topic,Finding --batch-size 64 --embed-batch-size 10 --recreate-index
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from src.graph.neo4j_client import get_session
from src.utils.rag.embedding import get_sync_client


LABEL_CONFIG: Dict[str, Dict[str, object]] = {
    "Entity": {
        "index_name": "entity_embedding_vec",
        "text_fields": ["name", "description", "type"],
    },
    "Claim": {
        "index_name": "claim_embedding_vec",
        "text_fields": ["content", "summary"],
    },
    "Event": {
        "index_name": "event_embedding_vec",
        "text_fields": ["name", "summary", "description"],
    },
    "Topic": {
        "index_name": "topic_embedding_vec",
        "text_fields": ["name", "description", "keywords"],
    },
    "Finding": {
        "index_name": "finding_embedding_vec",
        "text_fields": ["title", "statement"],
    },
}


def _batched(seq: List[str], n: int) -> List[List[str]]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def _embed_batches(
    client,
    model: str,
    text_batches: List[List[str]],
    max_concurrency: int,
) -> List[List[float]]:
    if not text_batches:
        return []
    workers = max(1, int(max_concurrency))
    ordered: List[List[List[float]]] = [None] * len(text_batches)  # type: ignore[assignment]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(client.embeddings.create, model=model, input=batch): idx
            for idx, batch in enumerate(text_batches)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            resp = future.result()
            ordered[idx] = [x.embedding for x in resp.data]
    vectors: List[List[float]] = []
    for part in ordered:
        vectors.extend(part or [])
    return vectors


def _session(database: str | None):
    return get_session(database=database) if database else get_session()


def _build_text_expr(fields: List[str]) -> str:
    # Join non-empty fields with newline in Cypher.
    # Some properties (e.g., Topic.keywords) can be arrays; convert all parts to string first.
    parts = ", ".join([f"toString(coalesce(n.{f}, ''))" for f in fields])
    return (
        "trim(reduce(acc = '', part IN ["
        + parts
        + "] | acc + CASE "
          "WHEN trim(part) = '' THEN '' "
          "WHEN acc = '' THEN trim(part) "
          "ELSE '\\n' + trim(part) END))"
    )


def _fetch_seed_rows(database: str | None, label: str, limit: int) -> List[Dict[str, str]]:
    cfg = LABEL_CONFIG[label]
    fields = cfg["text_fields"]  # type: ignore[index]
    text_expr = _build_text_expr(fields)  # type: ignore[arg-type]
    cypher = f"""
    MATCH (n:{label})
    WHERE n.embedding IS NULL
    WITH n, {text_expr} AS text
    WHERE text IS NOT NULL AND trim(text) <> ''
    RETURN elementId(n) AS eid, text
    """ + (f"\nLIMIT {int(limit)}" if limit and limit > 0 else "")

    with _session(database) as session:
        rows = session.run(cypher).data()
    out: List[Dict[str, str]] = []
    for row in rows:
        eid = str(row.get("eid") or "").strip()
        text = str(row.get("text") or "").strip()
        if eid and text:
            out.append({"eid": eid, "text": text})
    return out


def _write_embeddings(database: str | None, label: str, eids: List[str], embeddings: List[List[float]]) -> None:
    payload = [{"eid": eid, "embedding": emb} for eid, emb in zip(eids, embeddings) if eid and emb]
    if not payload:
        return
    cypher = f"""
    UNWIND $rows AS row
    MATCH (n:{label})
    WHERE elementId(n) = row.eid
    SET n.embedding = row.embedding
    """
    with _session(database) as session:
        session.run(cypher, rows=payload).consume()


def _ensure_vector_index(database: str | None, label: str, index_name: str, dim: int, recreate: bool) -> None:
    drop = f"DROP INDEX {index_name} IF EXISTS"
    create = f"""
    CREATE VECTOR INDEX {index_name} IF NOT EXISTS
    FOR (n:{label}) ON (n.embedding)
    OPTIONS {{
      indexConfig: {{
        `vector.dimensions`: {int(dim)},
        `vector.similarity_function`: 'cosine'
      }}
    }}
    """
    with _session(database) as session:
        if recreate:
            session.run(drop).consume()
        session.run(create).consume()


def _parse_labels(raw: str) -> List[str]:
    values = [x.strip() for x in (raw or "").split(",") if x.strip()]
    labels = [x for x in values if x in LABEL_CONFIG]
    if not labels:
        return ["Entity", "Claim", "Event", "Topic", "Finding"]
    return labels


def backfill_graph_node_embeddings(
    database: Optional[str],
    *,
    labels: Optional[List[str]] = None,
    batch_size: int = 64,
    embed_batch_size: int = 10,
    max_concurrency: int = 5,
    limit_per_label: int = 0,
    recreate_index: bool = False,
) -> Dict[str, Any]:
    selected_labels = [x for x in (labels or []) if x in LABEL_CONFIG] or ["Entity", "Claim", "Event", "Topic", "Finding"]
    client, model, dimension = get_sync_client()
    per_label: List[Dict[str, Any]] = []
    indexes: List[str] = []
    labels_without_processable_nodes: List[str] = []
    total_candidates = 0
    total_backfilled = 0

    for label in selected_labels:
        cfg = LABEL_CONFIG[label]
        index_name = str(cfg["index_name"])
        rows = _fetch_seed_rows(database, label, limit_per_label)
        candidate_count = len(rows)
        total_candidates += candidate_count
        done = 0

        for batch in _batched(rows, max(1, int(batch_size))):
            texts = [x["text"].replace("\n", " ").strip() for x in batch]
            eids = [x["eid"] for x in batch]
            text_batches = _batched(texts, max(1, min(int(embed_batch_size), 10)))
            vecs = _embed_batches(client, model, text_batches, int(max_concurrency))
            _write_embeddings(database, label, eids, vecs)
            written = min(len(batch), len(vecs))
            done += written

        _ensure_vector_index(database, label, index_name, dimension, recreate_index)
        indexes.append(index_name)
        if candidate_count == 0:
            labels_without_processable_nodes.append(label)
        total_backfilled += done
        per_label.append(
            {
                "label": label,
                "index_name": index_name,
                "processable_nodes": candidate_count,
                "backfilled_nodes": done,
                "index_ensured": True,
            }
        )

    return {
        "status": "ok",
        "embedding_model": model,
        "embedding_dimension": dimension,
        "database": database or "",
        "labels": selected_labels,
        "total_processable_nodes": total_candidates,
        "total_backfilled_nodes": total_backfilled,
        "indexes": indexes,
        "labels_without_processable_nodes": labels_without_processable_nodes,
        "per_label": per_label,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill Neo4j embeddings and vector indexes for Entity/Claim/Event/Topic/Finding"
    )
    parser.add_argument("--database", default="opinion", help="Neo4j database name, default: opinion")
    parser.add_argument(
        "--labels",
        default="Entity,Claim,Event,Topic,Finding",
        help="Comma separated labels. Supported: Entity,Claim,Event,Topic,Finding",
    )
    parser.add_argument("--batch-size", type=int, default=64, help="Backfill write batch size")
    parser.add_argument(
        "--embed-batch-size",
        type=int,
        default=10,
        help="Single embeddings API call batch size (provider limit <=10)",
    )
    parser.add_argument("--max-concurrency", type=int, default=5, help="Max concurrent embedding API calls")
    parser.add_argument("--limit-per-label", type=int, default=0, help="Max nodes per label, 0 means all")
    parser.add_argument("--recreate-index", action="store_true", help="Drop and recreate vector indexes")
    args = parser.parse_args()

    labels = _parse_labels(args.labels)
    result = backfill_graph_node_embeddings(
        args.database,
        labels=labels,
        batch_size=args.batch_size,
        embed_batch_size=args.embed_batch_size,
        max_concurrency=args.max_concurrency,
        limit_per_label=args.limit_per_label,
        recreate_index=args.recreate_index,
    )
    print(f"Embedding model: {result['embedding_model']} (dim={result['embedding_dimension']})")
    print(f"Target labels: {', '.join(result['labels'])}")
    for item in result["per_label"]:
        print(f"[{item['label']}] nodes without embedding (processable): {item['processable_nodes']}")
        print(f"[{item['label']}] backfilled {item['backfilled_nodes']}/{item['processable_nodes']}")
        print(f"[{item['label']}] index ensured: {item['index_name']}")
    print("Graph-node backfill completed and indexes ensured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
