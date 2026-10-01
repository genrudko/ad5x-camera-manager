from pathlib import Path
root = Path(__file__).resolve().parents[1]
s = (root / "app.py").read_text(encoding="utf-8")
u = (root / "update.sh").read_text(encoding="utf-8")

run = s.split("def run_server()",1)[1].split("def main()",1)[0]
assert "ThreadingHTTPServer" in run
assert "target=camera_bootstrap_loop" in run
assert run.index("ThreadingHTTPServer") < run.index("target=camera_bootstrap_loop")
assert "runtime.start_all()" not in run

boot = s.split("def camera_bootstrap_loop()",1)[1].split("def run_server()",1)[0]
assert "runtime.start_all()" in boot
assert "target=monitor_loop" in boot

assert "self._ops_lock = threading.RLock()" in s
assert "pid != prev_pid or ticks < prev_ticks" in s
assert "max(0.0, value)" in s
assert "'status']" in s and "ov3660_orientation.py" in s
assert '"$DATA/camera-manager.sh" start' in u
assert 'keeping existing cameras.json' in u
print("0.1.4 bootstrap/cpu/installer regression checks: PASS")
