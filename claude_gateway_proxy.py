"""Compatibility entrypoint for the auxiliary Claude API gateway.

New code should import from ``pycodeagent.auxiliary.claude_api.gateway_proxy``.
This root wrapper remains temporarily for existing commands and tests.
"""

from pycodeagent.auxiliary.claude_api.gateway_proxy import AppConfig, build_app, main

__all__ = ["AppConfig", "build_app", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
