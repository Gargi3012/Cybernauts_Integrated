
import psutil
import time

def benchmark_cpu():
    psutil.cpu_percent(interval=None) # start tracking
    time.sleep(0.1)
    cpu_idle = psutil.cpu_percent(interval=None)
    return {"cpu_idle": cpu_idle, "cpu_peak": cpu_idle, "cpu_avg": cpu_idle}
