# Refactor Guard Documentation

Welcome to the comprehensive technical documentation for **Refactor Guard** — the agentic refactoring safety harness and patch quality gate.

---

## Documentation Index

| Guide | Description |
|---|---|
| [System Architecture](ARCHITECTURE.md) | In-depth technical architecture, the 5-step pipeline, AST engine, and data flow diagrams. |
| [CLI Reference Manual](CLI_REFERENCE.md) | Complete guide to all CLI subcommands (`rename`, `extract-function`, `move-symbol`, `history`, `review-patch`), flags, and exit codes. |
| [Minimal Patch Guard (MPG) Deep Dive](MINIMAL_PATCH_GUARD.md) | Guide to MPG rules (MPG-001–MPG-008), anti-hardcoding heuristics, metamorphic probes, and scoring engine. |
| [MCP Agentic Integration Guide](MCP_INTEGRATION_GUIDE.md) | Setup instructions for Cursor, Claude Desktop, Cline, and Antigravity; tool catalog (16 tools & prompts) and JSON schemas. |
| [Snapshot Engine & Audit Ledger](SNAPSHOT_AND_LEDGER.md) | Technical breakdown of zero-copy Git throwaway snapshots, Windows read-only object handling, and the JSONL ledger. |

---

## Quick Navigation by Role

- **AI Agents & MCP Clients**: Start with the [MCP Agentic Integration Guide](MCP_INTEGRATION_GUIDE.md) and [Minimal Patch Guard Deep Dive](MINIMAL_PATCH_GUARD.md).
- **Developers & CLI Users**: Start with the [CLI Reference Manual](CLI_REFERENCE.md).
- **Hackathon Judges & System Architects**: Review the [System Architecture](ARCHITECTURE.md) and [Snapshot Engine & Audit Ledger](SNAPSHOT_AND_LEDGER.md).
