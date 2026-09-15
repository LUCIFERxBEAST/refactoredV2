# Test Report

Generated September 14, 2026.

The test suite covers Tree-sitter-based scanning across Python, JavaScript, and
TypeScript, plus the rename, extract-function, and move-symbol refactoring
operations. It exercises snapshot creation and rollback, failure diagnosis for
both pytest and Node output, multi-hop blast radius analysis, and the MCP server
wrapper. All 91 unit tests pass.

The five end-to-end demo scenarios (Python rename, Python rename with dynamic
risk and auto-rollback, extract-function, move-symbol, and JavaScript rename
with dynamic risk and auto-rollback) were verified with `demo_run.py` and all
show "ALL DEMOS PASS". The Minimal Patch Guard review pipeline was additionally
validated against hardcoded-output, scope-expansion, and generalization-probe
scenarios during its own integration testing.