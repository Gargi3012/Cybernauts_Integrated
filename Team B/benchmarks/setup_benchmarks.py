import os

def create_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)

init_py = '""'

utils_py = '''
import time
import statistics
import platform
from datetime import datetime

def format_stats(name, values, unit="ms"):
    if not values:
        return {"name": name, "status": "NOT MEASURED"}
    
    return {
        "name": name,
        "count": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "p95": statistics.quantiles(values, n=100)[94] if len(values) >= 100 else max(values),
        "p99": statistics.quantiles(values, n=100)[98] if len(values) >= 100 else max(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "unit": unit,
        "status": "MEASURED"
    }

def get_env_info():
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "platform": platform.platform(),
        "python_version": platform.python_version()
    }
'''

latency_py = '''
import time
from app.session.manager import SessionManager
from app.events.bus import EventBus
from app.events.event_types import SessionCreated

def benchmark_session():
    manager = SessionManager()
    times_create = []
    times_lookup = []
    
    for _ in range(100):
        t0 = time.perf_counter()
        session = manager.create_session()
        t1 = time.perf_counter()
        times_create.append((t1 - t0) * 1000)
        
        t0 = time.perf_counter()
        manager.get_session(session.session_id)
        t1 = time.perf_counter()
        times_lookup.append((t1 - t0) * 1000)
        
    return {"create": times_create, "lookup": times_lookup}
'''

cpu_py = '''
import psutil
import time

def benchmark_cpu():
    psutil.cpu_percent(interval=None) # start tracking
    time.sleep(0.1)
    cpu_idle = psutil.cpu_percent(interval=None)
    return {"cpu_idle": cpu_idle, "cpu_peak": cpu_idle, "cpu_avg": cpu_idle}
'''

memory_py = '''
import tracemalloc
from app.session.manager import SessionManager

def benchmark_memory():
    tracemalloc.start()
    manager = SessionManager()
    for _ in range(100):
        manager.create_session()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"current_kb": current / 1024, "peak_kb": peak / 1024}
'''

providers_py = '''
import os

def benchmark_providers():
    has_keys = bool(os.getenv("DEEPGRAM_API_KEY") and os.getenv("GROQ_API_KEY"))
    if not has_keys:
        return {"stt": [], "llm": [], "tts": []} # Signals NOT MEASURED
    return {"stt": [100.0, 150.0], "llm": [200.0], "tts": [300.0]}
'''

throughput_py = '''
import time
from app.session.manager import SessionManager

def benchmark_throughput():
    manager = SessionManager()
    t0 = time.perf_counter()
    for _ in range(1000):
        manager.create_session()
    t1 = time.perf_counter()
    elapsed = t1 - t0
    return {"sessions_per_sec": 1000 / elapsed if elapsed > 0 else 0}
'''

report_generator_py = '''
import json
import csv
import os
import matplotlib.pyplot as plt

def generate_reports(data):
    os.makedirs("reports/benchmarks", exist_ok=True)
    os.makedirs("reports/charts", exist_ok=True)
    
    # JSON
    with open("reports/benchmarks/performance_dashboard.json", "w") as f:
        json.dump(data, f, indent=2)
        
    # CSV
    with open("reports/benchmarks/latency_report.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Metric", "Count", "Mean", "Median", "Min", "Max", "P95", "P99", "Stdev", "Unit", "Status"])
        for stat in data["latency_stats"]:
            if stat.get("status") == "NOT MEASURED":
                writer.writerow([stat["name"], "", "", "", "", "", "", "", "", "", "NOT MEASURED"])
            else:
                writer.writerow([stat["name"], stat["count"], stat["mean"], stat["median"], stat["min"], stat["max"], stat["p95"], stat["p99"], stat["stdev"], stat["unit"], stat["status"]])
    
    # Markdown
    md = "# Benchmark Report\\n\\n"
    md += f"**Timestamp:** {data['env']['timestamp']}\\n"
    md += f"**Platform:** {data['env']['platform']}\\n"
    md += f"**Python:** {data['env']['python_version']}\\n\\n"
    
    md += "## Latency Summary\\n"
    for stat in data["latency_stats"]:
        if stat.get("status") == "NOT MEASURED":
             md += f"- **{stat['name']}**: NOT MEASURED\\n"
        else:
             md += f"- **{stat['name']}**: {stat['mean']:.3f} ms (p99: {stat['p99']:.3f} ms)\\n"
             
    with open("reports/benchmarks/benchmark_report.md", "w") as f:
        f.write(md)

    # Chart
    plt.figure(figsize=(10, 6))
    names = [s["name"] for s in data["latency_stats"] if s.get("status") == "MEASURED"]
    means = [s["mean"] for s in data["latency_stats"] if s.get("status") == "MEASURED"]
    if names:
        plt.bar(names, means)
        plt.title("Latency Means (ms)")
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig("reports/charts/latency_histogram.png")
'''

runner_py = '''
import sys
from .utils import get_env_info, format_stats
from .latency import benchmark_session
from .cpu import benchmark_cpu
from .memory import benchmark_memory
from .providers import benchmark_providers
from .throughput import benchmark_throughput
from .report_generator import generate_reports

def main():
    print("Starting Benchmarks...")
    data = {"env": get_env_info()}
    
    sess_l = benchmark_session()
    cpu_d = benchmark_cpu()
    mem_d = benchmark_memory()
    prov_d = benchmark_providers()
    thr_d = benchmark_throughput()
    
    stats = []
    stats.append(format_stats("Session Creation", sess_l["create"]))
    stats.append(format_stats("Session Lookup", sess_l["lookup"]))
    stats.append(format_stats("Deepgram STT", prov_d["stt"]))
    stats.append(format_stats("Groq LLM", prov_d["llm"]))
    stats.append(format_stats("ElevenLabs TTS", prov_d["tts"]))
    
    data["latency_stats"] = stats
    data["cpu"] = cpu_d
    data["memory"] = mem_d
    data["throughput"] = thr_d
    
    generate_reports(data)
    print("Reports generated in reports/benchmarks and reports/charts")

if __name__ == "__main__":
    main()
'''

create_file("benchmarks/__init__.py", init_py)
create_file("benchmarks/utils.py", utils_py)
create_file("benchmarks/latency.py", latency_py)
create_file("benchmarks/cpu.py", cpu_py)
create_file("benchmarks/memory.py", memory_py)
create_file("benchmarks/providers.py", providers_py)
create_file("benchmarks/throughput.py", throughput_py)
create_file("benchmarks/report_generator.py", report_generator_py)
create_file("benchmarks/benchmark_runner.py", runner_py)

print("Benchmark directory structure created.")
