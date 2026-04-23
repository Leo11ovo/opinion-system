import sys
from pathlib import Path
from typing import Dict, Any

# Add project root to sys.path
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.graph.neo4j_client import get_session
from src.utils.logging.logging import setup_logger, log_success, log_error

logger = setup_logger("ExpertKGEvaluator", "default")

class ExpertKGEvaluator:
    def __init__(self):
        pass

    def get_node_counts(self) -> Dict[str, int]:
        """Get counts of nodes by label."""
        counts = {}
        try:
            with get_session(database="opinion-expert") as session:
                # Fallback logic is handled inside get_session or by catching specific errors if needed
                # Here we assume get_session handles the connection correctly (including fallback to default DB if configured)
                # But strictly speaking, if we want to query specifically expert nodes, we should rely on labels if DB separation fails.
                
                # Query all nodes that have ExpertNode label (plus their specific label)
                result = session.run("MATCH (n:ExpertNode) RETURN labels(n) as labels, count(n) as count")
                for record in result:
                    labels = record["labels"]
                    # We are interested in the specific type (e.g. Theory, Method), not just ExpertNode
                    for label in labels:
                        if label == "ExpertNode": continue
                        counts[label] = counts.get(label, 0) + record["count"]
        except Exception as e:
            # Handle potential database not found error for Community Edition fallback logic check
            if "Database does not exist" in str(e) or "database management is not supported" in str(e):
                 # Retry with default session (assuming logic in neo4j_client handles this, but here we explicitly retry if the session context manager didn't hide it)
                 # Actually, my previous neo4j_client implementation attempts to use the passed DB.
                 # Let's try a fallback block here just in case.
                 try:
                    with get_session() as session:
                        result = session.run("MATCH (n:ExpertNode) RETURN labels(n) as labels, count(n) as count")
                        for record in result:
                            labels = record["labels"]
                            for label in labels:
                                if label == "ExpertNode": continue
                                counts[label] = counts.get(label, 0) + record["count"]
                 except Exception as inner_e:
                     log_error(logger, f"Error getting node counts (fallback): {inner_e}", "ExpertKG")
            else:
                log_error(logger, f"Error getting node counts: {e}", "ExpertKG")
        return counts

    def get_orphan_nodes(self) -> int:
        """Count nodes with no relationships."""
        try:
            with get_session(database="opinion-expert") as session:
                result = session.run("""
                    MATCH (n:ExpertNode)
                    WHERE NOT (n)--()
                    RETURN count(n) as count
                """)
                return result.single()["count"]
        except Exception as e:
            if "Database does not exist" in str(e) or "database management is not supported" in str(e):
                try:
                    with get_session() as session:
                        result = session.run("""
                            MATCH (n:ExpertNode)
                            WHERE NOT (n)--()
                            RETURN count(n) as count
                        """)
                        return result.single()["count"]
                except: return -1
            log_error(logger, f"Error counting orphan nodes: {e}", "ExpertKG")
            return -1

    def get_relationship_count(self) -> int:
        try:
            with get_session(database="opinion-expert") as session:
                # Count relationships where at least one node is an ExpertNode
                result = session.run("MATCH (n:ExpertNode)-[r]-() RETURN count(distinct r) as count")
                return result.single()["count"]
        except Exception as e:
             if "Database does not exist" in str(e) or "database management is not supported" in str(e):
                try:
                    with get_session() as session:
                        result = session.run("MATCH (n:ExpertNode)-[r]-() RETURN count(distinct r) as count")
                        return result.single()["count"]
                except: return -1
             log_error(logger, f"Error counting relationships: {e}", "ExpertKG")
             return -1

    def get_chunk_metrics(self) -> Dict[str, Any]:
        """Get metrics related to ExpertChunk and Documents."""
        metrics = {"total_chunks": 0, "avg_chunks_per_doc": 0.0, "total_docs": 0}
        
        query = """
        MATCH (c:ExpertChunk)
        WITH count(c) as total_chunks
        // Count all entity types (not just docs) to see structure scale
        MATCH (n:ExpertNode) WHERE NOT n:ExpertChunk
        WITH total_chunks, count(n) as total_entities
        RETURN total_chunks, total_entities
        """
        
        try:
            with get_session(database="opinion-expert") as session:
                result = session.run(query)
                record = result.single()
                if record:
                    metrics["total_chunks"] = record["total_chunks"]
                    metrics["total_docs"] = record["total_entities"] # Renamed for report compatibility
                    if metrics["total_docs"] > 0:
                        metrics["avg_chunks_per_doc"] = metrics["total_chunks"] / metrics["total_docs"]
        except Exception as e:
            if "Database does not exist" in str(e) or "database management is not supported" in str(e):
                try:
                    with get_session() as session:
                        result = session.run(query)
                        record = result.single()
                        if record:
                            metrics["total_chunks"] = record["total_chunks"]
                            metrics["total_docs"] = record["total_docs"]
                            if metrics["total_docs"] > 0:
                                metrics["avg_chunks_per_doc"] = metrics["total_chunks"] / metrics["total_docs"]
                except Exception as inner_e:
                     log_error(logger, f"Error getting chunk metrics (fallback): {inner_e}", "ExpertKG")
            else:
                 log_error(logger, f"Error getting chunk metrics: {e}", "ExpertKG")
        
        return metrics

    def get_orphan_chunks(self) -> int:
        """Count ExpertChunk nodes not linked to any Document."""
        query = """
        MATCH (c:ExpertChunk)
        WHERE NOT (c)<-[:HAS_CHUNK]-()
        RETURN count(c) as count
        """
        try:
            with get_session(database="opinion-expert") as session:
                result = session.run(query)
                return result.single()["count"]
        except Exception as e:
            if "Database does not exist" in str(e) or "database management is not supported" in str(e):
                try:
                    with get_session() as session:
                        result = session.run(query)
                        return result.single()["count"]
                except: return -1
            log_error(logger, f"Error counting orphan chunks: {e}", "ExpertKG")
            return -1

    def run_evaluation(self):
        print("=== Expert KG Quality Report ===")
        
        # 1. Node Counts
        counts = self.get_node_counts()
        print("\n[Node Counts]")
        total_nodes = 0
        for label, count in counts.items():
            print(f"  {label}: {count}")
            total_nodes += count
        
        # Note: total_nodes might be slightly off if nodes have multiple specific labels, but usually they don't in this schema.
        # Better to get total unique nodes count from DB if needed, but this is fine for overview.
        
        # 2. Relationships
        rel_count = self.get_relationship_count()
        print(f"\n[Relationships]\n  Total: {rel_count}")
        
        # 3. Density/Orphans
        orphans = self.get_orphan_nodes()
        print(f"\n[Connectivity]\n  Orphan Nodes: {orphans}")
        
        if total_nodes > 0:
            avg_degree = rel_count / total_nodes
            print(f"  Avg Degree (approx): {avg_degree:.2f}")
            
        # 4. Chunk Metrics
        chunk_metrics = self.get_chunk_metrics()
        print(f"\n[Chunk Metrics]")
        print(f"  Total Chunks: {chunk_metrics['total_chunks']}")
        print(f"  Total Documents: {chunk_metrics['total_docs']}")
        print(f"  Avg Chunks/Doc: {chunk_metrics['avg_chunks_per_doc']:.2f}")
        
        orphan_chunks = self.get_orphan_chunks()
        print(f"  Orphan Chunks: {orphan_chunks}")

        print("\n=== End Report ===")

if __name__ == "__main__":
    evaluator = ExpertKGEvaluator()
    evaluator.run_evaluation()
