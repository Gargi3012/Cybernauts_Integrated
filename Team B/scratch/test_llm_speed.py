import time
from groq import Groq
from app.config import GROQ_API_KEY

client = Groq(api_key=GROQ_API_KEY)
models = ["qwen/qwen3.6-27b", "openai/gpt-oss-20b", "llama-3.1-8b-instant", "llama3-8b-8192", "groq/compound"]

for m in models:
    times = []
    for i in range(3):
        try:
            t0 = time.time()
            stream = client.chat.completions.create(
                model=m,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Hello how are you?"}
                ],
                stream=True
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    times.append((time.time() - t0)*1000)
                    break
        except Exception as e:
            times.append(9999)
            print(f"Model {m} error: {e}")
            break
    if times:
        avg = sum(times)/len(times)
        print(f"Model {m}: avg TTFT = {avg:.1f} ms | runs = {[round(t,1) for t in times]}")
