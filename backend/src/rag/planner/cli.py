"""CLI for generating planning graph retrieval plan."""
from __future__ import annotations

import argparse
import json

from .engine import PlanningGraphEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate retrieval plan from Planning Graph")
    parser.add_argument("--query", required=True, help="User query text")
    parser.add_argument("--threshold", type=float, default=0.75, help="NEXT writeback confidence threshold")
    parser.add_argument("--model", default="qwen-plus", help="LLM model for planning")
    args = parser.parse_args()

    planner = PlanningGraphEngine(next_threshold=args.threshold, model=args.model)
    payload = planner.generate_plan(args.query)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

