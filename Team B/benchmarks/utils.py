
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
