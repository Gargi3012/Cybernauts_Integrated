
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
