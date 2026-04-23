"""
Backfill embeddings for ExpertNode in opinion-expert database.

Usage:
  python -m src.expert_kg.backfill_expert_embeddings --batch-size 64 --embed-batch-size 10
"""
from __future__ import annotations

import argparse
from typing import List

from src.graph.neo4j_client import get_session
from src.utils.rag.embedding import get_sync_client


def _batched(seq: List[str], n: int) -> List[List[str]]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def _fetch_nodes(limit: int) -> List[dict]:
    cypher = """
    MATCH (n:ExpertNode)
    WHERE n.embedding IS NULL
    RETURN n.name AS name, n.description AS description
    ORDER BY n.name
    """ + (f"\nLIMIT {int(limit)}" if limit and limit > 0 else "")
    with get_session(database="opinion-expert") as session:
        return session.run(cypher).data()


def _write_embeddings(rows: List[dict]) -> None:
    if not rows:
        return
    cypher = """
    UNWIND $rows AS row
    MATCH (n:ExpertNode {name: row.name})
    SET n.embedding = row.embedding
    """
    with get_session(database="opinion-expert") as session:
        session.run(cypher, rows=rows).consume()


def _ensure_index(dim: int, recreate: bool) -> None:
    drop = "DROP INDEX expert_embedding_index IF EXISTS"
    create = f"""
    CREATE VECTOR INDEX expert_embedding_index IF NOT EXISTS
    FOR (n:ExpertNode) ON (n.embedding)
    OPTIONS {{
      indexConfig: {{
        `vector.dimensions`: {int(dim)},
        `vector.similarity_function`: 'cosine'
      }}
    }}
    """
    with get_session(database="opinion-expert") as session:
        if recreate:
            session.run(drop).consume()
        session.run(create).consume()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill ExpertNode embeddings in opinion-expert")
    parser.add_argument("--batch-size", type=int, default=64, help="Fetch/write batch size")
    parser.add_argument("--embed-batch-size", type=int, default=10, help="Embedding API batch size (<=10)")
    parser.add_argument("--limit", type=int, default=0, help="Max nodes to process, 0 means all")
    parser.add_argument("--recreate-index", action="store_true", help="Drop and recreate expert_embedding_index")
    args = parser.parse_args()

    client, model, dim = get_sync_client()
    items = _fetch_nodes(args.limit)
    total = len(items)
    print(f"ExpertNode without embedding: {total}")
    if total == 0:
        _ensure_index(dim, args.recreate_index)
        print("No backfill needed. Index ensured.")
        return 0

    done = 0
    for batch in _batched(items, max(1, int(args.batch_size))):
        texts = []
        names = []
        for row in batch:
            name = str(row.get("name") or "").strip()
            desc = str(row.get("description") or "").strip()
            names.append(name)
            texts.append((name + " " + desc).strip())

        vectors: List[List[float]] = []
        for sub in _batched(texts, max(1, min(int(args.embed_batch_size), 10))):
            resp = client.embeddings.create(model=model, input=sub)
            vectors.extend([x.embedding for x in resp.data])

        payload = []
        for name, emb in zip(names, vectors):
            if name and emb:
                payload.append({"name": name, "embedding": emb})
        _write_embeddings(payload)
        done += len(batch)
        print(f"Backfilled {done}/{total}")

    _ensure_index(dim, args.recreate_index)
    print("Backfill completed and index ensured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

