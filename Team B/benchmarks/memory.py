
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
