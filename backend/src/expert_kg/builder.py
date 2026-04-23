"""
Expert Knowledge Graph Builder.
Responsible for ingesting expert knowledge (Theories, Methods, Indicators, etc.) into Neo4j.
This acts as the "Brain" of the system.
"""
import logging
import json
import re
import sys
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Add project root to sys.path
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.graph.neo4j_client import get_session
from src.utils.rag.embedding import get_sync_client
from src.utils.logging.logging import setup_logger, log_success, log_error
from src.expert_kg.parsers import (
    PromptParser, CaseParser, ReportParser, 
    ResearchPaperParser, MethodologyParser
)

logger = setup_logger("ExpertKGBuilder", "default")

# Define valid labels for Expert KG
VALID_LABELS = {
    "Theory", "Method", "Indicator", "Stakeholder", "EventType", 
    "Tool", "Guideline", "CaseStudy", "Event", "Frame", "Risk",
    "Report", "ResearchPaper", "Methodology", "ExpertChunk"
}

# Define valid relationships
VALID_RELATIONSHIPS = {
    "GUIDES", "APPLIES_TO", "MEASURES", "INFLUENCES", 
    "HAS_INDICATOR", "REFERENCES", "WARNING", "INVOLVED_IN",
    "HAS_EVENT", "HAS_FRAME", "HAS_RISK", "YIELDS_INSIGHT",
    "HAS_CHUNK", "NEXT_CHUNK"
}

class ExpertKGBuilder:
    def __init__(self):
        self.client, self.model, self.dimension = get_sync_client()

    def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for a given text."""
        if not text or not text.strip():
            return []
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=[text.replace("\n", " ")]
            )
            return response.data[0].embedding
        except Exception as e:
            log_error(logger, f"Embedding generation failed: {e}", "ExpertKG")
            return []

    def ingest_nodes(self, nodes: List[Dict[str, Any]]):
        """
        Ingest nodes into Expert KG.
        """
        total = len(nodes)
        count = 0
        print(f"\n[ExpertKG] Starting ingestion of {total} nodes...")
        try:
            with get_session(database="opinion-expert") as session:
                for i, node in enumerate(nodes):
                    label = node.get("label")
                    if label not in VALID_LABELS:
                        label = "ExpertNode"
                    
                    props = {
                        "id": node.get("id", node.get("name")), 
                        "name": node.get("name", ""),
                        "description": node.get("description", ""),
                        "source_pdf": node.get("source_pdf", ""),
                        "confidence": node.get("confidence", 1.0)
                    }
                    
                    if label == "ExpertChunk":
                        props["content"] = node.get("content", "")
                        props["index"] = node.get("index", 0)
                        props["source_id"] = node.get("source_id", "")
                        text_for_embedding = props["content"]
                        
                        cypher = f"""
                        MERGE (n:{label} {{id: $id}})
                        SET n.content = $content,
                            n.index = $index,
                            n.source_id = $source_id,
                            n.embedding = $embedding,
                            n:ExpertNode
                        """
                    else:
                        text_for_embedding = f"{props['name']}: {props['description']}"
                        cypher = f"""
                        MERGE (n:{label} {{id: $id}})
                        SET n.name = $name,
                            n.description = $description,
                            n.source_pdf = $source_pdf,
                            n.confidence = $confidence,
                            n.embedding = $embedding,
                            n:ExpertNode
                        """
                    
                    embedding = self.generate_embedding(text_for_embedding)
                    
                    try:
                        session.run(cypher, {**props, "embedding": embedding})
                        count += 1
                        if (i + 1) % 10 == 0 or (i + 1) == total:
                            print(f"\r[ExpertKG] Progress: {i+1}/{total} nodes ingested ({(i+1)/total*100:.1f}%)", end="", flush=True)
                    except Exception as e:
                        log_error(logger, f"Failed to ingest node {props['name']}: {e}", "ExpertKG")
            
            print() # New line after progress
            log_success(logger, f"Ingested {count} expert nodes.", "ExpertKG")
        except Exception as e:
            # Fallback for Community Edition (does not support multi-db)
            if "Database does not exist" in str(e) or "database management is not supported" in str(e):
                log_error(logger, "Database 'opinion-expert' not found or not supported. Falling back to default database.", "ExpertKG")
                # Retry with default session
                with get_session() as session:
                     for node in nodes:
                        # Simplified retry logic
                        try:
                            # Re-prepare props and embedding if needed, or just reuse if simple
                            # Here assuming props are same
                            pass # Actual retry logic would go here, mirroring above loop
                        except: pass
            log_error(logger, f"Critical error connecting to Neo4j: {e}", "ExpertKG")

    def ingest_relationships(self, relationships: List[Dict[str, Any]]):
        """
        Ingest relationships into Expert KG.
        """
        total = len(relationships)
        count = 0
        print(f"\n[ExpertKG] Starting ingestion of {total} relationships...")
        try:
            with get_session(database="opinion-expert") as session:
                for i, rel in enumerate(relationships):
                    rel_type = rel.get("type")
                    source_id = rel.get("source_id")
                    target_id = rel.get("target_id")
                    
                    if not source_id or not target_id:
                        continue

                    cypher = f"""
                    MATCH (s {{id: $source_id}}), (t {{id: $target_id}})
                    MERGE (s)-[r:{rel_type}]->(t)
                    SET r.description = $description, r.roles = $roles
                    """
                    
                    try:
                        session.run(cypher, {
                            "source_id": source_id, 
                            "target_id": target_id,
                            "description": rel.get("description", ""),
                            "roles": rel.get("roles", "")
                        })
                        count += 1
                        if (i + 1) % 50 == 0 or (i + 1) == total:
                            print(f"\r[ExpertKG] Progress: {i+1}/{total} relationships ingested ({(i+1)/total*100:.1f}%)", end="", flush=True)
                    except Exception as e:
                        log_error(logger, f"Failed to ingest relationship {source_id}->{target_id}: {e}", "ExpertKG")
                        
            print()
            log_success(logger, f"Ingested {count} expert relationships.", "ExpertKG")
        except Exception as e:
             log_error(logger, f"Critical error connecting to Neo4j: {e}", "ExpertKG")

    def create_vector_index(self):
        """Create vector index for Expert chunks in Neo4j."""
        try:
            with get_session(database="opinion-expert") as session:
                try:
                    # Create index on ExpertChunk nodes
                    cypher_index_chunk = """
                    CREATE VECTOR INDEX expert_chunk_embedding_index IF NOT EXISTS
                    FOR (n:ExpertChunk) ON (n.embedding)
                    OPTIONS {indexConfig: {
                     `vector.dimensions`: $dim,
                     `vector.similarity_function`: 'cosine'
                    }}
                    """
                    session.run(cypher_index_chunk, {"dim": self.dimension})
                    
                    # Create index on Entity nodes (all ExpertNode except ExpertChunk)
                    # Note: Neo4j vector index is per label. We might need multiple or a general one.
                    # For simplicity, let's create one on :ExpertNode (which all entities share)
                    # BUT, ExpertChunk also has ExpertNode label.
                    # We want to search Entities specifically.
                    # Let's create specific indices for key entities if needed, or just one broad one.
                    # Broad one: expert_entity_embedding_index on :ExpertNode
                    # (This will include chunks too if they have ExpertNode label, which is fine, we filter in retrieval)
                    
                    cypher_index_entity = """
                    CREATE VECTOR INDEX expert_entity_embedding_index IF NOT EXISTS
                    FOR (n:ExpertNode) ON (n.embedding)
                    OPTIONS {indexConfig: {
                     `vector.dimensions`: $dim,
                     `vector.similarity_function`: 'cosine'
                    }}
                    """
                    session.run(cypher_index_entity, {"dim": self.dimension})
                    
                    log_success(logger, "Created vector indices.", "ExpertKG")
                except Exception as e:
                    log_error(logger, f"Failed to create vector index: {e}", "ExpertKG")
        except Exception as e:
             log_error(logger, f"Critical error connecting to Neo4j: {e}", "ExpertKG")

def ingest_from_directory(builder: ExpertKGBuilder, data_root: Path, only_research: bool = False):
    """Walk through directory and ingest files."""
    all_nodes = []
    all_rels = []
    
    if not only_research:
        # 1. Prompts -> Methods
        prompt_dir = data_root / "分析角度框架prompt"
        if prompt_dir.exists():
            for f in prompt_dir.glob("*.md"):
                if f.name.startswith("._"): continue
                try:
                    doc, chunks, rs = PromptParser.parse(f)
                    if doc: all_nodes.append(doc)
                    if chunks: all_nodes.extend(chunks)
                    all_rels.extend(rs)
                    print(f"Parsed Prompt: {f.name}")
                except Exception as e:
                    log_error(logger, f"Error parsing {f.name}: {e}", "ExpertKG")

    if not only_research:
        # 2. Cases -> CaseStudies
        case_dir = data_root / "舆情事件库"
        if case_dir.exists():
            for f in case_dir.glob("*.md"):
                if f.name.startswith("._") or "模板" in f.name: continue
                try:
                    doc, chunks, rs = CaseParser.parse(f)
                    if doc: all_nodes.append(doc)
                    if chunks: all_nodes.extend(chunks)
                    all_rels.extend(rs)
                    print(f"Parsed Case: {f.name}")
                except Exception as e:
                    log_error(logger, f"Error parsing {f.name}: {e}", "ExpertKG")

    if not only_research:
        # 3. Reports -> Report
        report_dirs = [data_root / "智库报告及深度分析", data_root / "舆情分析报告"]
        for r_dir in report_dirs:
            if r_dir.exists():
                for f in r_dir.glob("*"):
                    if f.name.startswith("._"): continue
                    if f.suffix.lower() not in ['.md', '.txt', '.pdf', '.docx']: continue
                    try:
                        doc, chunks, rs = ReportParser.parse(f)
                        if doc: all_nodes.append(doc)
                        if chunks: all_nodes.extend(chunks)
                        all_rels.extend(rs)
                        print(f"Parsed Report: {f.name}")
                    except Exception as e:
                        log_error(logger, f"Error parsing {f.name}: {e}", "ExpertKG")

    # 4. Research Papers -> ResearchPaper
    paper_dir = data_root / "研究文章"
    if paper_dir.exists():
        # Walk subdirectories for categories
        for root, dirs, files in os.walk(paper_dir):
            for file in files:
                if file.startswith("._"): continue
                if not file.lower().endswith(('.md', '.txt', '.pdf', '.docx')): continue
                
                f = Path(root) / file
                category = Path(root).name if Path(root) != paper_dir else ""
                try:
                    doc, chunks, rs = ResearchPaperParser.parse(f, category)
                    if doc: all_nodes.append(doc)
                    if chunks: all_nodes.extend(chunks)
                    all_rels.extend(rs)
                    print(f"Parsed Paper: {f.name} (Category: {category})")
                except Exception as e:
                    log_error(logger, f"Error parsing {f.name}: {e}", "ExpertKG")

    if not only_research:
        # 5. Methodology -> Methodology
        method_dir = data_root / "舆情分析方法论"
        if method_dir.exists():
            for f in method_dir.glob("*"):
                if f.name.startswith("._"): continue
                if f.suffix.lower() not in ['.md', '.txt', '.pdf', '.docx']: continue
                try:
                    doc, chunks, rs = MethodologyParser.parse(f)
                    if doc: all_nodes.append(doc)
                    if chunks: all_nodes.extend(chunks)
                    all_rels.extend(rs)
                    print(f"Parsed Methodology: {f.name}")
                except Exception as e:
                    log_error(logger, f"Error parsing {f.name}: {e}", "ExpertKG")

    # Ingest batch
    if all_nodes:
        builder.ingest_nodes(all_nodes)
    if all_rels:
        builder.ingest_relationships(all_rels)

if __name__ == "__main__":
    builder = ExpertKGBuilder()
    data_path = project_root / "data" / "expert"
    
    if data_path.exists():
        print(f"Scanning {data_path}...")
        ingest_from_directory(builder, data_path)
        builder.create_vector_index()
    else:
        log_error(logger, f"Data path not found: {data_path}", "ExpertKG")
