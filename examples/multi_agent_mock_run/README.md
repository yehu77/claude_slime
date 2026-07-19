# Phase-one multi-agent mock golden

This directory is the single tracked golden for the phase-one synthetic multi-agent scaffold. It is generated from a fixed `MockAdapter` scenario using the strict native Claude ToolView (`mock_base`).

Do not edit these artifacts by hand. Update them with:

```bash
python -B -m pycodeagent.testing.multi_agent_mock_golden --write
```

Verify both manifest integrity and deterministic regeneration with:

```bash
python -B -m pycodeagent.testing.multi_agent_mock_golden --check
```

The bundle preserves RawAgentTrace, the emitted native tool catalog, agent identity, canonical normalization, and one representative schema-following sample. Tests consume this directory directly; no duplicated fixture is kept.
