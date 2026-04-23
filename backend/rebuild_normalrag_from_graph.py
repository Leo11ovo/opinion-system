"""
Script to rebuild NormalRAG vector database using existing Chunks from Neo4j.
This ensures NormalRAG uses the same chunking strategy (512 chars) as GraphRAG.
"""
import os
import lancedb
import pyarrow as pa
import logging
from typing import List, Dict, Any
from src.graph.neo4j_client import get_session
from src.utils.rag.embedding import get_sync_client
from src.utils.setting.paths import get_project_root
from src.utils.logging.logging import setup_logger, log_success, log_error

logger = setup_logger("RebuildNormalRAG", "default")

def fetch_graph_chunks(topic: str) -> List[Dict[str, Any]]:
    """Fetch Chunk nodes linked to Posts from Neo4j."""
    chunks = []
    cypher_query = """
    MATCH (p:Post)-[:HAS_CHUNK]->(c:Chunk)
    WHERE p.topic = $topic OR $topic IS NULL
    RETURN c.id as chunk_id, c.text as chunk_text, 
           p.id as post_id, p.title as post_title, p.published_at as published_at
    """
    
    try:
        with get_session() as session:
            result = session.run(cypher_query, topic=topic)
            for record in result:
                text = record['chunk_text']
                if not text or not text.strip():
                    continue
                
                chunks.append({
                    "sentence_id": record['chunk_id'],
                    "sentence_text": text,
                    "doc_id": record['post_id'],
                    "doc_name": record['post_title'] or "未知",
                    "time": str(record['published_at']) if record['published_at'] else "未知"
                })
        log_success(logger, f"Fetched {len(chunks)} Chunks from Neo4j", "Fetch")
        return chunks
    except Exception as e:
        log_error(logger, f"Failed to fetch chunks from Neo4j: {e}", "Fetch")
        return []

import time

def compute_embeddings(chunks: List[Dict[str, Any]], batch_size: int = 5) -> List[Dict[str, Any]]:
    """Compute embeddings for chunks in batches."""
    client, model, dimension = get_sync_client()
    total = len(chunks)
    processed_chunks = []
    
    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c['sentence_text'] for c in batch]
        
        # Clean texts
        cleaned_texts = [t.replace("\n", " ") for t in texts]
        
        try:
            response = client.embeddings.create(
                model=model,
                input=cleaned_texts
            )
            embeddings = [data.embedding for data in response.data]
            
            for chunk, vec in zip(batch, embeddings):
                chunk['sentence_vec'] = vec
                processed_chunks.append(chunk)
                
            log_success(logger, f"Processed embeddings: {min(i + batch_size, total)}/{total}", "Embed")
            time.sleep(0.5) # Rate limit protection
            
        except Exception as e:
            log_error(logger, f"Batch embedding failed: {e}", "Embed")
            # If quota exceeded, stop early
            if "quota" in str(e).lower():
                log_error(logger, "Stopping due to quota limit.", "Embed")
                break
            continue
            
    return processed_chunks

def save_to_lancedb(topic: str, data: List[Dict[str, Any]]):
    """Save processed chunks to LanceDB normalrag table."""
    if not data:
        return
        
    project_root = get_project_root()
    # Path: src/utils/rag/ragrouter/{topic}数据库/vector_db
    db_path = project_root / "src" / "utils" / "rag" / "ragrouter" / f"{topic}数据库" / "vector_db"
    os.makedirs(db_path, exist_ok=True)
    
    try:
        db = lancedb.connect(str(db_path))
        table_name = "normalrag"
        
        # Define Schema
        dim = len(data[0]['sentence_vec'])
        schema = pa.schema([
            pa.field("sentence_id", pa.string()),
            pa.field("sentence_text", pa.string()),
            pa.field("sentence_vec", pa.list_(pa.float64(), dim)),
            pa.field("doc_id", pa.string()),
            pa.field("doc_name", pa.string()),
            pa.field("time", pa.string())
        ])
        
        if table_name in db.table_names():
            db.drop_table(table_name)
            log_success(logger, f"Dropped existing table: {table_name}", "DB")
            
        table = db.create_table(table_name, data, schema=schema)
        log_success(logger, f"Successfully saved {len(data)} records to {table_name}", "DB")
        
    except Exception as e:
        log_error(logger, f"Failed to save to LanceDB: {e}", "DB")

def rebuild_normalrag(topic: str = "test"):
    """Main function to rebuild NormalRAG."""
    log_success(logger, f"Starting NormalRAG rebuild for topic: {topic}", "Main")
    
    # 1. Fetch chunks from Graph
    chunks = fetch_graph_chunks(topic)
    if not chunks:
        log_error(logger, "No chunks found to process.", "Main")
        return
        
    # 2. Compute Embeddings
    processed_data = compute_embeddings(chunks)
    
    # 3. Save to LanceDB
    save_to_lancedb(topic, processed_data)
    
    log_success(logger, "NormalRAG rebuild completed!", "Main")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", type=str, default="test", help="Topic name")
    args = parser.parse_args()
    
    rebuild_normalrag(args.topic)
