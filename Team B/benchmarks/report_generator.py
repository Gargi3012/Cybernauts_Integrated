
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
    md = "# Benchmark Report\n\n"
    md += f"**Timestamp:** {data['env']['timestamp']}\n"
    md += f"**Platform:** {data['env']['platform']}\n"
    md += f"**Python:** {data['env']['python_version']}\n\n"
    
    md += "## Latency Summary\n"
    for stat in data["latency_stats"]:
        if stat.get("status") == "NOT MEASURED":
             md += f"- **{stat['name']}**: NOT MEASURED\n"
        else:
             md += f"- **{stat['name']}**: {stat['mean']:.3f} ms (p99: {stat['p99']:.3f} ms)\n"
             
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
