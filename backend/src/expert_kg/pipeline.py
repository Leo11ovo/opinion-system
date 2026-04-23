import argparse
import sys
import os
print("[DIAGNOSE] Script started. Importing libraries...", flush=True)
from pathlib import Path

# Add project root to sys.path
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

print("[DIAGNOSE] Importing ExpertKGBuilder...", flush=True)
from src.expert_kg.builder import ExpertKGBuilder, ingest_from_directory
from src.expert_kg.planning_graph_builder import PlanningGraphBuilder
print("[DIAGNOSE] Importing ExpertKGEvaluator...", flush=True)
from src.expert_kg.evaluator import ExpertKGEvaluator
print("[DIAGNOSE] Importing logger...", flush=True)
from src.utils.logging.logging import setup_logger, log_success, log_error

print("[DIAGNOSE] All imports successful.", flush=True)
logger = setup_logger("ExpertKGPipeline", "default")

class ExpertKGPipeline:
    def __init__(self):
        self.builder = ExpertKGBuilder()
        self.evaluator = ExpertKGEvaluator()

    def run(
        self,
        rebuild: bool = False,
        only_research: bool = False,
        build_planning_graph: bool = True,
        planning_only: bool = True,
        resume: bool = True,
        force_reextract: bool = False,
        flush_every_docs: int = 5,
    ):
        """Run the Expert KG construction pipeline."""
        print("Starting Expert KG Construction Pipeline...")
        
        # 1. Rebuild (optional)
        if rebuild:
            print("\n[Step 1/4] Rebuilding Database (optional)...")
            # In Neo4j, rebuilding usually means deleting existing ExpertNode nodes
            # and starting fresh.
            from src.graph.neo4j_client import get_session
            try:
                with get_session(database="opinion-expert") as session:
                    print("  Clearing existing expert data in 'opinion-expert'...")
                    session.run("MATCH (n:ExpertNode) DETACH DELETE n")
                log_success(logger, "Cleared existing expert data.", "ExpertKG")
            except Exception as e:
                # Fallback to default DB if opinion-expert fails
                if "Database does not exist" in str(e) or "database management is not supported" in str(e):
                    try:
                        with get_session() as session:
                            print("  Clearing existing expert data in default database (using labels)...")
                            session.run("MATCH (n:ExpertNode) DETACH DELETE n")
                    except Exception as inner_e:
                        log_error(logger, f"Failed to clear expert data (fallback): {inner_e}", "ExpertKG")
                else:
                    log_error(logger, f"Failed to clear expert data: {e}", "ExpertKG")
        
        # 2. Ingest
        print("\n[Step 2/4] Ingesting Data...")
        data_path = project_root / "data" / "expert"
        if not data_path.exists():
            log_error(logger, f"Data path not found: {data_path}", "ExpertKG")
            return
        
        try:
            if planning_only:
                planning_builder = PlanningGraphBuilder(data_root=data_path)
                result = planning_builder.build(
                    resume=resume,
                    force_reextract=force_reextract,
                    flush_every_docs=flush_every_docs,
                )
                if result.get("status") != "ok":
                    log_error(logger, f"Planning Graph build failed: {result.get('message', 'unknown')}", "ExpertKG")
                    return
                log_success(logger, "Planning Graph ingestion completed.", "ExpertKG")
            else:
                ingest_from_directory(self.builder, data_path, only_research=only_research)
                log_success(logger, "Data ingestion completed.", "ExpertKG")
        except Exception as e:
            log_error(logger, f"Data ingestion failed: {e}", "ExpertKG")
            return

        # 3. Create Vector Index
        print("\n[Step 3/4] Creating Vector Index...")
        try:
            self.builder.create_vector_index()
            log_success(logger, "Vector index creation completed.", "ExpertKG")
        except Exception as e:
            log_error(logger, f"Vector index creation failed: {e}", "ExpertKG")

        # 4. Verify/Evaluate
        print("\n[Step 4/4] Running Quality Evaluation...")
        try:
            self.evaluator.run_evaluation()
            log_success(logger, "Quality evaluation completed.", "ExpertKG")
        except Exception as e:
            log_error(logger, f"Quality evaluation failed: {e}", "ExpertKG")

        if build_planning_graph:
            print("\n[Step 5/5] Building Planning Graph vocab...")
            try:
                from src.rag.planner import PlanningGraphEngine
                planner = PlanningGraphEngine()
                planner.build_vocab(force_refresh=True)
                log_success(logger, "Planning Graph vocab built.", "ExpertKG")
            except Exception as e:
                log_error(logger, f"Planning Graph build failed: {e}", "ExpertKG")

        print("\nExpert KG Construction Pipeline finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Expert KG Construction Pipeline")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the Expert KG from scratch")
    parser.add_argument("--only-research", action="store_true", help="Only ingest data/expert/研究文章")
    parser.add_argument("--no-planning-graph", action="store_true", help="Skip planning graph vocab build")
    parser.add_argument("--legacy-expert-graph", action="store_true", help="Use legacy parser pipeline instead of 5-type planning graph")
    parser.add_argument("--no-resume", action="store_true", help="Disable resume-from-checkpoint for planning graph build")
    parser.add_argument("--force-reextract", action="store_true", help="Re-extract all documents even when checkpoint exists")
    parser.add_argument("--flush-every-docs", type=int, default=5, help="Incremental graph flush interval (docs)")
    args = parser.parse_args()
    
    pipeline = ExpertKGPipeline()
    pipeline.run(
        rebuild=args.rebuild,
        only_research=args.only_research,
        build_planning_graph=not args.no_planning_graph,
        planning_only=not args.legacy_expert_graph,
        resume=not args.no_resume,
        force_reextract=args.force_reextract,
        flush_every_docs=args.flush_every_docs,
    )
