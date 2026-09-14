# Refactor Guard — Test Report

**Generated:** September 14, 2026
**Project root:** `C:\Users\pondh\Downloads\REFACTOR-GAURD`
**Environment:** Windows (win32) · Python 3.14.6 · pytest 9.1.1 · google-generativeai 0.8.6
**Unit test command:** `python -m pytest tests/test_refactor_guard.py -v`
**Demo command:** `python demo_run.py`

---

## 1. Summary

- Total unit tests: **75** — **75 passed**, **0 failed**
- Total demo scenarios: **5** — **5 passed**, **0 failed**
- **Overall status: ALL PASS** ✅

**Status note.** All 75 unit tests pass and all 5 demo scenarios pass. Two previously known issues
have been resolved in this run:

1. **Model string updated** (`src/self_heal.py`): `_MODEL` changed from `"gemini-2.0-flash"` (retired
   by Google, returned 404) to `"gemini-3.6-flash"` (the recommended replacement). Live self-heal
   diagnosis now returns real, actionable AI-written root-cause + fix text — see §3 and §4.

2. **Failing test fixed** (`tests/test_refactor_guard.py`): `test_skips_diagnosis_without_api_key` now
   imports the module *before* deleting the env var, preventing `load_dotenv()` from re-populating the
   key after deletion.
---

## 2. Unit Test Results

75 tests, grouped by the source file each group exercises. Format: **test name** — what it checks, then status.

### 2.1 `src/dependency_graph.py` (24 tests — all PASS)

**TestScanRepo (repo-level scan):**
- **test_finds_definition_in_mathutils** — a scan finds the symbol's definition in `pkg/mathutils.py`. ✅ PASS
- **test_finds_static_import_in_reporter** — a scan finds a static import reference in `pkg/reporter.py`. ✅ PASS
- **test_identifies_dynamic_risk** — string-literal `getattr(obj, "name")` usage is flagged as dynamic risk. ✅ PASS
- **test_dynamic_caller_not_in_static** — the dynamic-risk caller is not listed as a static reference. ✅ PASS
- **test_build_report_no_dynamic_risk** — `build_report` has no dynamic-risk references. ✅ PASS
- **test_symbol_not_found** — an unknown symbol yields an empty result (no crash). ✅ PASS
- **test_word_boundary_at_ast_level** — AST-level word boundaries prevent substring false positives. ✅ PASS
- **test_async_def_detected** — `async def` definitions are detected as definitions. ✅ PASS
- **test_class_def_detected** — `class` definitions are detected as definitions. ✅ PASS

**TestScanSource (per-file scan):**
- **test_python_static** — a file-level scan detects static references in Python. ✅ PASS
- **test_python_dynamic** — a file-level scan detects dynamic (`getattr`, string-literal) usage in Python. ✅ PASS
- **test_js_static** — a file-level scan detects static references in JavaScript. ✅ PASS
- **test_js_dynamic** — a file-level scan detects dynamic (bracket-notation) usage in JavaScript. ✅ PASS
- **test_no_match** — files with no references return empty lists. ✅ PASS
- **test_unsupported_extension_raises** — unsupported file extensions raise instead of silently mis-scanning. ✅ PASS

**TestJsScanning (JS/TS integration):**
- **test_js_static_and_dynamic** — a JS file with both static and dynamic references is scanned correctly. ✅ PASS
- **test_js_member_access_is_static** — dot-notation member access counts as a static reference. ✅ PASS
- **test_js_shorthand_export_is_static** — shorthand-object exports (`{ buildReport }`) count as static references. ✅ PASS
- **test_ts_extension_scans_like_js** — `.ts` files are scanned with the same rules as `.js`. ✅ PASS
- **test_symbol_not_found_in_js** — an unknown symbol in JS yields an empty result. ✅ PASS

**TestBlastRadius (transitive impact):**
- **test_python_chain_abc** — a Python A→B→C import chain returns every transitively affected file. ✅ PASS
- **test_python_chain_excludes_unrelated_file** — files not connected to the chain are excluded. ✅ PASS
- **test_js_chain_require** — a JS `require()` chain is traced transitively. ✅ PASS
- **test_blast_radius_missing_symbol** — an unknown symbol returns an empty affected set. ✅ PASS

### 2.2 `src/refactor_ops.py` (8 tests — all PASS)

**TestRenameInFile:**
- **test_basic_rename** — a simple identifier rename replaces occurrences in file text. ✅ PASS
- **test_word_boundary_skips_subtotal** — `compute_total` is not matched inside `compute_subtotal`. ✅ PASS
- **test_word_boundary_skips_total_count** — `total` is not matched inside `total_count`. ✅ PASS
- **test_import_rename** — import statements are updated when the imported name is renamed. ✅ PASS
- **test_no_match_returns_zero** — zero matches returns the count 0. ✅ PASS
- **test_multiline_replacements** — multiline replacements are handled correctly. ✅ PASS

**TestRenameInFiles:**
- **test_renames_in_multiple_files** — renames are applied across several files in one call. ✅ PASS
- **test_nonexistent_file_skipped** — a nonexistent file is skipped without raising. ✅ PASS

### 2.3 `src/snapshot.py` (1 test — all PASS)

- **test_roundtrip** — snapshot → edit → restore returns the original file contents. ✅ PASS
### 2.4 `src/test_runner.py` (22 tests — all PASS)

**TestBuildCommand:**
- **test_pytest_uses_current_python** — pytest commands are run with the current interpreter. ✅ PASS
- **test_non_pytest_passthrough** — non-pytest commands (e.g. `node --test`) pass through unchanged. ✅ PASS

**TestFindMissingSymbols:**
- **test_name_error** — a Python `NameError` maps to the missing symbol. ✅ PASS
- **test_attribute_error** — `AttributeError: module 'x' has no attribute 'y'` maps to `y`. ✅ PASS
- **test_import_error** — an `ImportError` maps to the missing module. ✅ PASS
- **test_no_match** — unrecognized failure text yields no missing symbol (no crash). ✅ PASS

**TestDiagnoseFailures:**
- **test_blames_dynamic_file** — the diagnosis points at the pre-flagged dynamic-risk file. ✅ PASS
- **test_no_dynamic_files** — with no dynamic files the diagnosis is generic. ✅ PASS
- **test_python_dynamic_file_uses_python_example** — Python dynamic refs show a Python-style fix example. ✅ PASS
- **test_js_dynamic_file_uses_js_example** — JS dynamic refs show a JS-style fix example. ✅ PASS
- **test_mixed_languages_show_both_examples** — mixed Python + JS dynamic refs show both examples. ✅ PASS
- **test_duplicate_failures_are_deduplicated** — repeated failure lines are deduplicated. ✅ PASS

**TestJsMissingSymbols (JS failure parsing):**
- **test_js_type_error** — a JS `TypeError` maps to the missing symbol. ✅ PASS
- **test_js_reference_error** — a JS `ReferenceError` maps to the missing symbol. ✅ PASS
- **test_js_bracket_notation_type_error** — `mathutils.computeTotal is not a function` maps correctly. ✅ PASS
- **test_js_single_quote_bracket_type_error** — single-quoted bracket-notation errors map correctly. ✅ PASS
- **test_js_read_property_error** — Node "Cannot read properties of undefined (reading 'x')" maps to `x`. ✅ PASS
- **test_js_read_property_error_singular** — the singular "property 'x'" phrasing maps correctly. ✅ PASS
- **test_js_ansi_colored_type_error** — ANSI-colored error output is parsed correctly. ✅ PASS
- **test_js_diagnosis_fallback_via_stack_trace** — stack-trace fallback blames the file in the trace. ✅ PASS
- **test_js_diagnosis_fallback_via_stack_trace_backslash** — same fallback with backslash (Windows) paths. ✅ PASS
- **test_js_diagnosis_fallback_no_match_generic** — no recognizable match → generic fallback text, no crash. ✅ PASS

### 2.5 `src/main.py` (5 tests — all PASS)

**TestSampleRepoIntegration:**
- **test_full_scan_compute_total** — end-to-end scan of `tests/sample_repo` for `compute_total` finds definition, static and dynamic refs. ✅ PASS
- **test_full_scan_build_report** — end-to-end scan of `tests/sample_repo` for `build_report` finds definition + static refs only. ✅ PASS
- **test_decorator_detected** — a symbol used as a decorator is detected as a reference. ✅ PASS

**TestSampleRepoJsIntegration:**
- **test_full_scan_compute_total** — end-to-end scan of `tests/sample_repo_js` for `computeTotal` works. ✅ PASS
- **test_build_report_no_dynamic_risk** — JS `buildReport` scan reports no dynamic-risk refs. ✅ PASS
### 2.6 `src/extract_function.py` (5 tests — all PASS)

- **test_analyze_derives_params_and_returns** — block analysis derives the parameters and return values. ✅ PASS
- **test_apply_extraction_shape** — the extracted function has the expected shape (new name + params). ✅ PASS
- **test_extract_into_file_tests_still_pass** — extracted code keeps the test suite green. ✅ PASS
- **test_bad_range_returns_none** — an out-of-range block returns `None` instead of raising. ✅ PASS
- **test_invalid_function_name_raises** — an invalid new-function name raises a clear error. ✅ PASS

### 2.7 `src/move_symbol.py` (5 tests — all PASS)

- **test_move_build_report_and_tests_pass** — moving `build_report` to `pkg/reportbuilder.py` keeps tests passing. ✅ PASS
- **test_find_top_level_definition** — the top-level definition of a symbol is located. ✅ PASS
- **test_dotted_module** — dotted module paths (e.g. `pkg.sub`) are handled. ✅ PASS
- **test_move_missing_symbol_raises** — moving a symbol that doesn't exist raises. ✅ PASS
- **test_move_missing_source_raises** — a missing source file raises. ✅ PASS

### 2.8 `src/self_heal.py` + `src/main.py` `_verify_step` (5 tests — all PASS)

- **test_skips_diagnosis_without_api_key** — imports module first, then deletes `GEMINI_API_KEY`; asserts `has_api_key()` is `False` (Gemini never called). ✅ PASS
- **test_request_ai_diagnosis_uses_gemini_models** — stubs `genai.configure` + `GenerativeModel` (no real call); asserts model `gemini-3.6-flash`, key passing, and prompt contains failure context. ✅ PASS
- **test_verify_step_rolls_back_without_api_key** — `_verify_step` skips AI and rolls back, no retry. ✅ PASS
- **test_verify_step_keeps_change_on_retry** — the single bounded retry passes → change is kept. ✅ PASS
- **test_verify_step_rolls_back_when_retry_fails** — the retry fails → change is rolled back. ✅ PASS
---

## 3. Demo Scenario Results

`python demo_run.py` runs 5 scenarios on fresh copies of `tests/sample_repo` / `tests/sample_repo_js`.
Each scenario's pass criterion is the **exit code matching the expected value** (0 for success scenarios,
1 for rollback scenarios that intentionally fail). All 5 scenarios PASS in every run.

### Demo 1 — rename `build_report` → `generate_report` (should succeed)

- **What it demonstrates:** a safe rename with no hidden dynamic-risk references succeeds and the change is kept.
- **Expected outcome:** tests pass; snapshot restored/deleted; final exit code 0.
- **Actual outcome:** **PASS**
- **Key output excerpt** (from `test_reports/demo_output.txt`):

```
DEMO: rename: build_report → generate_report (should SUCCEED)
  STEP 1: MAP — scanning for references to 'build_report'
  Static references found in: pkg/mathutils.py, tests/test_reporter.py
  Dynamic-risk references found in: (none)
  Blast radius — files transitively affected: pkg/mathutils.py, pkg/reporter.py, tests/test_reporter.py
  STEP 2: WARN — No dynamic-risk references detected — safe to proceed.
  STEP 4: ACT — Total replacements across 2 file(s): 4
  STEP 5: VERIFY — pytest -q ... 6 passed
  SUCCESS ✓ — All tests pass. Change is kept.
→ exit code 0 (expected 0) ✓
```

### Demo 2 — rename `compute_total` → `sum_items` (should fail + roll back)

- **What it demonstrates:** a rename that breaks a hidden `getattr` dynamic reference fails verification, triggers the bounded self-heal retry (once), still fails, and rolls the change back.
- **Expected outcome:** tests fail; self-heal section runs; rollback restores the repo; final exit code 1.
- **Actual outcome:** **PASS**
- **Key output excerpt** (self-heal section, with the live API key configured — real AI diagnosis, no 404):

```
  STEP 2: WARN — ⚠ WARNING: 'compute_total' appears inside string literals in: pkg/dynamic_caller.py
  STEP 5: VERIFY — FF.... ... 2 failed, 4 passed — Exit code: 1
=== Self-Heal: AI Diagnosis ===
  The root cause of the failure is that the automated refactoring tool renamed the `compute_total`
  function definition but skipped the hardcoded string literal `"compute_total"` used in the dynamic
  `getattr()` call in `pkg/dynamic_caller.py`. To fix this, manually update line 10 of
  `pkg/dynamic_caller.py` to pass the new symbol name string into `getattr` (e.g.,
  `fn = getattr(mathutils, "<new_symbol_name>")`).
  Retrying test suite exactly once…
  ... 2 failed, 4 passed — Exit code: 1
  FAILURE ✗ — tests failed after the change. Rolling back…
  Repo restored from snapshot. / Backup deleted.
→ exit code 1 (expected 1) ✓
```

### Demo 3 — extract-function (block 30–31 of `pkg/mathutils.py` → `_build_summary_and_count`)

- **What it demonstrates:** a pure refactor (extract block into a new function) with no risk passes verification and the change is kept.
- **Expected outcome:** tests pass; change kept; exit code 0.
- **Actual outcome:** **PASS**
- **Key output excerpt**:

```
  STEP 1: MAP — analyzing block 30-31 of pkg/mathutils.py
  Block found inside function 'describe_items'
  Derived parameters : ['items'] / Values passed back : ['summary', 'count']
  STEP 4: ACT — pkg/mathutils.py: extracted lines 30-31 → def _build_summary_and_count(…)
  STEP 5: VERIFY — pytest -q ... 6 passed
  SUCCESS ✓ — All tests pass. Change is kept.
→ exit code 0 (expected 0) ✓
```

### Demo 4 — move-symbol `build_report` → `pkg/reportbuilder.py`

- **What it demonstrates:** moving a symbol to another module with cross-file reference rewriting keeps tests green.
- **Expected outcome:** tests pass; change kept; exit code 0.
- **Actual outcome:** **PASS**
- **Key output excerpt**:

```
  STEP 1: MAP — Move plan: 'build_report' from pkg/mathutils.py → pkg/reportbuilder.py
  STEP 4: ACT — pkg/mathutils.py: moved def build_report -> pkg/reportbuilder.py; re-imported it locally
               pkg/reportbuilder.py: created/extended with def build_report
               tests/test_reporter.py: rewritten references for build_report
  STEP 5: VERIFY — pytest -q ... 6 passed
  SUCCESS ✓ — All tests pass. Change is kept.
→ exit code 0 (expected 0) ✓
```

### Demo 5 — JS rename `computeTotal` → `sumItems` (should fail + roll back)

- **What it demonstrates:** the same hidden-dynamic-reference hazard in JavaScript — bracket-notation access in `pkg/dynamic_call.js` survives the rename, tests fail, self-heal retry runs, and the change rolls back.
- **Expected outcome:** tests fail; self-heal section runs; rollback; final exit code 1.
- **Actual outcome:** **PASS**
- **Key output excerpt**:

```
  STEP 1: MAP — Dynamic-risk references found in: pkg/dynamic_call.js
  STEP 2: WARN — ⚠ WARNING: 'computeTotal' appears inside string literals in: pkg/dynamic_call.js
  STEP 5: VERIFY — node --test ... ✖ callComputeTotal sums items ... TypeError: mathutils.computeTotal is not a function
                   ✖ 2 fail / 3 pass — Exit code: 1
=== Self-Heal: AI Diagnosis ===
  The test failed because the automated refactoring tool skipped updating `pkg/dynamic_call.js` due to
  its pre-flagged dynamic risk, leaving line 8 invoking the old `mathutils.computeTotal` property that
  no longer exists on the object.
  To fix this, manually update line 8 in `pkg/dynamic_call.js` to invoke the new renamed function on
  `mathutils` instead of `computeTotal`.
  Retrying test suite exactly once… … (retry also failed) — Exit code: 1
  FAILURE ✗ — tests failed after the change. Rolling back… Repo restored from snapshot.
→ exit code 1 (expected 1) ✓
```

**Demo summary (every run):**

```
  ✓ PASS  demo1 rename build_report -> generate_report (success)
  ✓ PASS  demo2 rename compute_total -> sum_items (rollback)
  ✓ PASS  demo3 extract-function
  ✓ PASS  demo4 move-symbol build_report -> pkg/reportbuilder.py
  ✓ PASS  demo5 js rename computeTotal -> sumItems (rollback)
ALL DEMOS PASS
```
---

## 4. Feature-Specific Verification

### 4.1 Blast radius — multi-hop chain (A calls B calls C)

Targeted probe: `test_reports/_verify_blast.py`, which builds a temp repo and calls `blast_radius()` on a
three-level chain plus an unrelated file.

**Repo layout (`pkg/`):**
- `a.py` — `def build_report(x): ...`
- `b.py` — `from .a import build_report; def wrap(x): return build_report(x)`
- `c.py` — `from .b import wrap; def top(x): return wrap(x)`
- `d.py` — `def unrelated(): return 42` (no imports from the chain)

**Before:** only `a.py` defines the symbol. **After calling `blast_radius(REPO, "build_report")`:**

```
blast_radius(REPO, 'build_report') returned:
  - pkg/a.py
  - pkg/b.py
  - pkg/c.py
RESULT: PASS — multi-hop chain fully enumerated, unrelated d.py excluded
blast_radius(REPO, 'unrelated') -> ['pkg/d.py'] (expect just itself)
```

**Verdict:** ✅ **PASS** — all transitively affected files (`a → b → c`) are returned; the isolated file
`d.py` is correctly excluded. (The repo's own unit tests `TestBlastRadius` — 4 tests — also pass; see §2.1.)

### 4.2 Self-heal — WITH a valid API key configured

A real `GEMINI_API_KEY` is present in `.env` (supplied by the user). Two live results:

**(a) Actual product path (`python demo_run.py`) — LIVE, fixed model** — `_verify_step` detected the key,
printed the self-heal section, and the Gemini API returned a real, actionable diagnosis. Demo2's
`getattr(mathutils, "compute_total")` rename failure produced:

```
=== Self-Heal: AI Diagnosis ===
  The root cause of the failure is that the automated refactoring tool renamed the `compute_total`
  function definition but skipped the hardcoded string literal `"compute_total"` used in the dynamic
  `getattr()` call in `pkg/dynamic_caller.py`. To fix this, manually update line 10 of
  `pkg/dynamic_caller.py` to pass the new symbol name string into `getattr` (e.g.,
  `fn = getattr(mathutils, "<new_symbol_name>")`).
```

Full excerpts for demo2 and demo5 are in §3. **No 404, no crash** — the bounded retry ran, failed again,
and rollback restored the repo. This is the fixed production path: `_MODEL = "gemini-3.6-flash"`.

**(b) Live probe with the recommended model** — `test_reports/_verify_selfheal.py` replayed the same prompt
through `gemini-3.6-flash`. The diagnosis text actually returned was:

```
=== SELF-HEAL LIVE PROBE (gemini-3.6-flash) ===

model='gemini-3.6-flash':
**(a)** The failure occurred because the automated refactoring tool updated the `compute_total` function
definition in `pkg.mathutils` but missed the hardcoded string literal inside the dynamic `getattr()` call
in `pkg/dynamic_caller.py`. **(b)** To fix this, manually update line 10 of `pkg/dynamic_caller.py` to
pass the new function name string to `getattr` (e.g., `fn = getattr(mathutils, "<new_symbol_name>")`).

model='gemini-2.0-flash' -> ERROR: 404 This model models/gemini-2.0-flash is no longer available.
    Please update your code to use models/gemini-3.6-flash ...
```

**Verdict:** ✅ **PASS** — the key is accepted, the prompt pipeline works, and the live Gemini API returns
a correct, actionable diagnosis. The retired-model caveat from the previous run is gone: the product now
uses the current `gemini-3.6-flash` model.

### 4.3 Self-heal — WITHOUT an API key (graceful skip)

Ran the full demo suite with `GEMINI_API_KEY=''` (process env var set to empty → `load_dotenv()` never
overrides an already-set env var). Capture: `test_reports/demo_output_nokey.txt`.

**Both failing demos (demo2 Python + demo5 JS) exhibit the same graceful path — no crash, no API call:**

```
  === Self-Heal: AI Diagnosis ===
  Skipping AI diagnosis — no API key configured
  ...
  FAILURE ✗ — tests failed after the change. Rolling back…
  Repo restored from snapshot. / Backup deleted.
→ exit code 1 (expected 1) ✓
```

Final summary line: `ALL DEMOS PASS`. **Verdict:** ✅ **PASS** — graceful skip, no crash, no network call.
Also confirmed by the passing unit test `test_verify_step_rolls_back_without_api_key` (§2.8).
---

## 5. Known Limitations

Honest list of things not working, not implemented, or working with caveats:

**Previously reported — now resolved in this run:**
- ~~`gemini-2.0-flash` retired (404) → AI diagnosis broken~~ → `_MODEL = "gemini-3.6-flash"` in `src/self_heal.py`; live demo2/demo5 self-heal now returns real AI diagnoses (§3, §4.2a).
- ~~`test_skips_diagnosis_without_api_key` test-isolation failure~~ → fixed (import before delenv); suite is **75/75 pass**.

1. **`google.generativeai` (v0.8.6) is a deprecated namespace.** Google now directs users to the newer `google.genai` SDK; importing it emits a `FutureWarning`. The project suppresses that one warning with a message-matched `warnings.filterwarnings` (see `src/self_heal.py:24-30`) so output stays clean. A future migration to `google.genai` would remove the suppression and align with Google's roadmap. The deprecated package still works today.

2. **Self-heal retry is bounded to exactly one retry** (by design). A genuinely transient failure after the single retry causes a rollback even if a second attempt might have passed. Documented behavior, not a regression.

3. **The AI step only diagnoses; it never auto-applies a fix.** The model can produce a suggested one-line fix, but Refactor Guard never edits code based on it — the change is either kept (retry passes) or rolled back. For the JS dynamic-bracket case (demo5), the emitted fix is explicitly "manual."

4. **Diagnosis quality depends on the dynamic-risk scan, which only catches string-literal indirection** (`getattr(obj, "name")`, `obj["name"]`). Any dynamic reference constructed at runtime (e.g. `getattr(obj, prefix + "total")`) is invisible to the scanner and will not be flagged or diagnosed.

5. **Raw capture files (`test_reports/*.txt`) are UTF-8 and include all glyphs correctly** (→, ⚠, ✓). If a log is viewed on a non-UTF-8 terminal the glyphs may render as mojibake; the underlying text is correct.

6. **Live diagnosis text is non-deterministic** — each `gemini-3.6-flash` call returns a slightly different (but equivalent and correct) wording of the root cause/fix. The excerpts in this report match the specific run they were captured from.

7. **Everything else requested** — multi-hop blast radius, snapshot/verify/rollback cycle, all 5 demos, JS/TS scanning, extract-function, move-symbol, live AI self-heal — **passed without caveats**.

---

## 6. Full Raw Output Logs

Complete, unedited capture files (written from a wrapper script `test_reports/_capture.py` with UTF-8
encoding so nothing is lost from the terminal):

| File | Content |
|---|---|
| `test_reports/pytest_output.txt` | Full verbose `pytest tests/test_refactor_guard.py -v` output (75 results — all PASS) |
| `test_reports/demo_output.txt` | Full `python demo_run.py` output — run WITH the live API key in `.env` (real `gemini-3.6-flash` AI diagnoses, no 404) |
| `test_reports/demo_output_nokey.txt` | Full `python demo_run.py` output — run with `GEMINI_API_KEY=''` (shows graceful-skip self-heal) |
| `test_reports/blast_probe.txt` | Output of the blast radius multi-hop probe (§4.1) |
| `test_reports/selfheal_probe.txt` | Output of the live `gemini-3.6-flash` diagnosis probe (§4.2b) |
| `test_reports/_capture.py`, `_verify_blast.py`, `_verify_selfheal.py` | The wrapper + probe scripts used to produce the above |

Summary of the crucial raw log tails:

- `pytest_output.txt` → `75 passed in 7.54s`
- `demo_output.txt` → `ALL DEMOS PASS` (with real `gemini-3.6-flash` diagnoses)
- `demo_output_nokey.txt` → `ALL DEMOS PASS`

They are appended as separate files (as permitted for long outputs) rather than inline so the document
stays navigable; each file is byte-for-byte the emitted stdout/stderr of the command described above.