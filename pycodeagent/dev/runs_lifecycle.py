"""CLI entrypoint for new-run retention verification and cleanup planning."""

from __future__ import annotations

from pycodeagent.runtime_trace.retention import main


if __name__ == "__main__":
    raise SystemExit(main())
