"""Run the preregistered Phase 8 Elliptic++ research experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.new_ml.training import run_elliptic_plus_experiment, verify_artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data/external/elliptic_plus_plus"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--task", choices=("transfer_risk", "wallet_risk"), required=True)
    parser.add_argument("--seed", type=int, default=26183)
    args = parser.parse_args()
    manifest = run_elliptic_plus_experiment(args.data_dir, args.output_dir, seed=args.seed, task=args.task)
    verification = verify_artifact(args.output_dir, manifest, args.data_dir)
    print(json.dumps({"experiment": manifest["experiment_version"], "state": manifest["state"],
                      "selected_model": manifest["selected_model"], "quality_gates": manifest["quality_gates"],
                      "artifact_verification": verification}, indent=2))
    return 0 if verification["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
