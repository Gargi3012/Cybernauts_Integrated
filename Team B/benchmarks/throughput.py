
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
