"""Verification probe: blast_radius() multi-hop chain (A calls B calls C)."""
import os, sys, tempfile, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dependency_graph import blast_radius

REPO = os.path.join(tempfile.mkdtemp(), "probe")
for d in ("pkg", "tests"):
    os.makedirs(os.path.join(REPO, d), exist_ok=True)

# a.py defines build_report; b.py imports from a and defines a wrapper;
# c.py imports from b.  Blocked/unrelated file d.py references nothing.
with open(os.path.join(REPO, "pkg", "a.py"), "w") as f:
    f.write("def build_report(x):\n    return x\n")
with open(os.path.join(REPO, "pkg", "b.py"), "w") as f:
    f.write("from .a import build_report\n\ndef wrap(x):\n    return build_report(x)\n")
with open(os.path.join(REPO, "pkg", "c.py"), "w") as f:
    f.write("from .b import wrap\n\ndef top(x):\n    return wrap(x)\n")
with open(os.path.join(REPO, "pkg", "d.py"), "w") as f:
    f.write("def unrelated():\n    return 42\n")

print("=== BLAST RADIUS MULTI-HOP VERIFICATION ===")
print("Call graph (definitions -> callers):")
print("  build_report (pkg/a.py) <- wrap (pkg/b.py) <- top (pkg/c.py)")
print("  unrelated (pkg/d.py) is isolated (no imports)")

files = blast_radius(REPO, "build_report")
print("blast_radius(REPO, 'build_report') returned:")
for f in sorted(files):
    print("  -", f)

expected = {"pkg/a.py", "pkg/b.py", "pkg/c.py"}
if set(files) == expected:
    print("RESULT: PASS — multi-hop chain fully enumerated, unrelated d.py excluded")
else:
    print(f"RESULT: FAIL — expected {sorted(expected)}, got {sorted(files)}")

unrelated = blast_radius(REPO, "unrelated")
print(f"blast_radius(REPO, 'unrelated') -> {sorted(unrelated)} (expect just itself)")

shutil.rmtree(os.path.dirname(REPO), ignore_errors=True)