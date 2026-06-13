from __future__ import annotations

import argparse
import json
from pathlib import Path

from pycodeagent.agent.compaction_acceptance import (
    verify_p3b_compaction_acceptance,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a P3-B real-provider model-backed compaction acceptance run."
    )
    parser.add_argument(
        "run_dir",
        nargs="?",
        default="runs/p3b_real_provider_compaction_acceptance",
        help="Run directory produced by run_p3b_real_provider_compaction_acceptance.py",
    )
    parser.add_argument(
        "--allow-fake-provider",
        action="store_true",
        help="Do not require trajectory provider metadata to indicate a real provider run.",
    )
    args = parser.parse_args()

    root = Path(args.run_dir)
    if root.is_dir():
        nested = sorted(path for path in root.iterdir() if path.is_dir())
        if nested and not (root / "runtime_trace.jsonl").exists():
            root = nested[-1]

    report = verify_p3b_compaction_acceptance(
        root,
        require_real_provider=not args.allow_fake_provider,
    )
    print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
