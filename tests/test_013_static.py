from pathlib import Path
root = Path(__file__).resolve().parents[1]
s = (root / "app.py").read_text(encoding="utf-8")
assert "import sys" in s
assert "[sys.executable, str(helper), device, 'apply']" in s
print("0.1.3 sys-import regression check: PASS")
