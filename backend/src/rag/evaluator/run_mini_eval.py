"""Run a minimal RouterRAG evaluation and write report JSON."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .core import run_evaluation, run_evaluation_compare


def main() -> int:
    parser = argparse.ArgumentParser(description="Run mini evaluation for RouterRAG")
    parser.add_argument("--topic", required=True, help="RouterRAG topic")
    parser.add_argument("--eval-data", required=True, help="Path to eval JSON")
    parser.add_argument("--mode", default="mixed", help="Retrieval mode")
    parser.add_argument("--tag", default="default", help="Single experiment tag")
    parser.add_argument("--compare-tag", default="", help="Candidate tag for A/B compare")
    parser.add_argument("--out-dir", default="backend/reports/rag_eval", help="Output directory")
    parser.add_argument("--eval-scope", default="all", choices=["all", "retrieval", "generation", "ux"], help="Evaluation scope")
    parser.add_argument("--top-k", default=10, type=int, help="Top-k cutoff for retrieval metrics")
    parser.add_argument("--manual-feedback-path", default="", help="Optional manual UX feedback JSON/JSONL")
    parser.add_argument("--no-breakdown", action="store_true", help="Disable breakdown output")
    args = parser.parse_args()

    eval_path = Path(args.eval_data).resolve()
    if not eval_path.is_file():
        raise FileNotFoundError(f"eval data file not found: {eval_path}")

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    manual_feedback_path = Path(args.manual_feedback_path).resolve() if args.manual_feedback_path else None

    if args.compare_tag:
        result = run_evaluation_compare(
            topic=args.topic,
            eval_data_path=eval_path,
            mode=args.mode,
            baseline_tag=args.tag,
            candidate_tag=args.compare_tag,
            eval_scope=args.eval_scope,
            top_k=args.top_k,
            include_breakdown=not args.no_breakdown,
            manual_feedback_path=manual_feedback_path,
        )
        out_path = out_dir / f"{stamp}_{args.topic}_{args.tag}_vs_{args.compare_tag}.json"
    else:
        result = run_evaluation(
            topic=args.topic,
            eval_data_path=eval_path,
            mode=args.mode,
            experiment_tag=args.tag,
            eval_scope=args.eval_scope,
            top_k=args.top_k,
            include_breakdown=not args.no_breakdown,
            manual_feedback_path=manual_feedback_path,
        )
        out_path = out_dir / f"{stamp}_{args.topic}_{args.tag}.json"

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
