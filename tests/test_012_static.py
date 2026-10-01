from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=(root/"app.py").read_text()
i=(root/"install.sh").read_text() + (root/"update.sh").read_text()
h=(root/"drivers/ov3660_orientation.py").read_text()
assert "item.get('capture') and item.get('vid') and item.get('pid')" in s
assert "verified-external-helper" in s
assert "for attempt in range(1, 11)" in s
assert "drivers/ov3660_orientation.py" in i
assert "SENSOR_SLAVE = 0x3C" in h
assert "target20 = before[\"r3820\"] & ~0x06" in h
assert "target21 = before[\"r3821\"] | 0x06" in h
assert "target4514 = 0xBB" in h
print("0.1.2 static checks: PASS")
