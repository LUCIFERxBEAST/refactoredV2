# Refactor Guard: MCP Agentic Integration Guide

Refactor Guard includes a native **Model Context Protocol (MCP)** server (`src/mcp_server.py`) built on `FastMCP`. It allows AI coding assistants (Claude Desktop, Cursor, Cline, Windsurf, Google Antigravity) to perform safe refactoring operations and run patch reviews autonomously.

---

## 1. IDE & Client Configuration

Add Refactor Guard to your client's MCP configuration file (e.g. `claude_desktop_config.json`, `.cursor/mcp.json`, or Cline MCP settings):

```json
{
  "mcpServers": {
    "refactor-guard": {
      "command": "python",
      "args": [
        "-m",
        "src.mcp_server"
      ],
      "cwd": "/absolute/path/to/refactor-guard"
    }
  }
}
```

If using a virtual environment:
```json
{
  "mcpServers": {
    "refactor-guard": {
      "command": "/absolute/path/to/refactor-guard/.venv/bin/python",
      "args": [
        "-m",
        "src.mcp_server"
      ],
      "cwd": "/absolute/path/to/refactor-guard"
    }
  }
}
```

---

## 2. MCP Tools Catalog

The MCP server exposes **16 tools** (8 primary functions + 8 backward-compatible aliases) and **1 agent prompt**.

### Core Refactoring Tools (Formatted Narration)

| Tool Name | Alias | Purpose |
|---|---|---|
| `refactor_guard_rename` | `refactor_rename` | Multi-language AST symbol rename with rollback. |
| `refactor_guard_extract_function` | `refactor_extract_function` | Extract Python code block into new function. |
| `refactor_guard_move_symbol` | `refactor_move_symbol` | Move top-level Python symbol & rewrite all imports. |
| `refactor_guard_history` | `refactor_history` | Query past refactor records from ledger. |

### Minimal Patch Guard Tools (Structured JSON)

| Tool Name | Alias | Purpose |
|---|---|---|
| `refactor_guard_review_patch` | `refactor_review_patch` | Complete 11-phase patch review with risk score and decision. |
| `refactor_guard_check_minimality` | `refactor_check_minimality` | Fast scope check detecting unrelated file modifications. |
| `refactor_guard_check_generalization`| `refactor_check_generalization`| Execute metamorphic & differential edge probes on pure functions. |
| `refactor_guard_compare_runs` | `refactor_compare_runs` | Run verification comparing baseline vs candidate failures. |

---

## 3. Tool Specifications & Example Calls

### `refactor_guard_rename`
```json
{
  "repo_root": "/path/to/project",
  "symbol": "old_name",
  "to": "new_name",
  "test_cmd": "pytest -q",
  "dry_run": false
}
```
**Response Format**:
```text
[SUCCESS]

============================================================
  STEP 1: MAP
  → Scanning the codebase with Tree-sitter...
  Found 3 static reference(s) across 2 file(s).
...
```

### `refactor_guard_review_patch`
```json
{
  "repo_root": "/path/to/project",
  "base_ref": "HEAD",
  "test_cmd": "pytest -q",
  "strict_minimality": true,
  "max_files_changed": 5
}
```
**Response Format**: Structured JSON containing `score`, `risk_level`, `decision`, `findings`, `verification`, and `suggested_prompt`.

---

## 4. Anti-Hardcoding Safety Prompt

The MCP server exposes a dedicated prompt template: **`strict_refactoring_guidelines`**.

When instructing AI agents in automated workflows, include this prompt to enforce architectural generality:

```markdown
# Refactor Guard: Agent Constraints
You are operating within the Refactor Guard safety harness. 

1. GENERALITY MANDATE: Never write hardcoded logic, mock-style bypasses, or if/else branches tailored to specific test inputs.
2. ARCHITECTURAL FIXES: If a dynamic reference breaks, fix the mechanism (e.g., dynamically resolving the new symbol string), do not hardcode the expected output.
3. FAIL FAST: If a general solution cannot be found, explain why rather than forcing a narrow fix.
```
