# generate_demo_logs.py
from datetime import datetime, timedelta
import random, re, pathlib

BGL = pathlib.Path("loghub/BGL/BGL_2k.log").read_text(encoding="utf-8").splitlines()

bgl_pattern = re.compile(
    r"^(?P<label>-|\d+)\s+(?P<unix_ts>\d+)\s+(?P<date>\d{4}\.\d{2}\.\d{2})\s+(?P<node>\S+)\s+"
    r"(?P<time>\d{4}-\d{2}-\d{2}-\d{2}\.\d{2}\.\d{2}\.\d{6})\s+(?P<device>\S+)\s+"
    r"(?P<component>RAS)\s+(?P<sub_component>\w+)\s+(?P<level>\w+)\s+(?P<msg>.*)$"
)

def parse_line(l: str):
    m = bgl_pattern.match(l)
    return m.groupdict() if m else None

def rebuild(p: dict) -> str:
    return (
        f"{p['label']} {p['unix_ts']} {p['date']} {p['node']} {p['time']} "
        f"{p['device']} {p['component']} {p['sub_component']} {p['level']} {p['msg']}"
    )

parsed = [p for l in BGL if (p := parse_line(l))]
anomalies = [p for p in parsed if p["level"] in {"ERROR", "WARN", "FATAL"}]
normals   = [p for p in parsed if p not in anomalies]

now  = datetime.now()
past = now - timedelta(days=2)

# Present spike (ERROR x20)
base_a = random.choice(anomalies)
anomaly_a = []
for _ in range(20):
    p = base_a.copy()
    p["unix_ts"] = str(int(now.timestamp()))
    p["date"]    = now.strftime("%Y.%m.%d")
    p["time"]    = now.strftime("%Y-%m-%d-%H.%M.%S.%f")  # keep microseconds
    p["level"]   = "ERROR"
    anomaly_a.append(p)

# Past similar (WARN x20, slight message tweak)
base_b = random.choice(anomalies)
anomaly_b = []
for _ in range(20):
    p = base_b.copy()
    p["unix_ts"] = str(int(past.timestamp()))
    p["date"]    = past.strftime("%Y.%m.%d")
    p["time"]    = past.strftime("%Y-%m-%d-%H.%M.%S.%f")
    p["level"]   = "WARN"
    p["msg"]     = p["msg"].replace("ASSERT", "TIMEOUT")
    anomaly_b.append(p)

# Normal noise (500 lines spread over last 72h)
noise = random.choices(normals, k=500)
for i, p in enumerate(noise):
    dt           = now - timedelta(hours=i % 72)
    p["unix_ts"] = str(int(dt.timestamp()))
    p["date"]    = dt.strftime("%Y.%m.%d")
    p["time"]    = dt.strftime("%Y-%m-%d-%H.%M.%S.%f")

sample = [*map(rebuild, anomaly_b), *map(rebuild, noise), *map(rebuild, anomaly_a)]
pathlib.Path("logs").mkdir(exist_ok=True, parents=True)
pathlib.Path("logs/sample.log").write_text("\n".join(sample) + "\n", encoding="utf-8")
print("sample.log ready ✓  (past anomaly ~2 days ago; present spike last hour)")
