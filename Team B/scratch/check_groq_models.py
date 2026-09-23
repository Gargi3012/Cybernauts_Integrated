import os
import time
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
client = Groq(api_key=api_key)

models = ["openai/gpt-oss-20b", "qwen/qwen3.8-27b", "groq/compound-mini"]

for m in models:
    try:
        t0 = time.time()
        res = client.chat.completions.create(
            model=m,
            messages=[{"role": "user", "content": "Hello, how are you?"}],
            max_tokens=20,
            stream=True
        )
        first_token_time = None
        for chunk in res:
            if chunk.choices and chunk.choices[0].delta.content:
                if first_token_time is None:
                    first_token_time = time.time() - t0
        print(f"SUCCESS model='{m}' | TTFT: {first_token_time*1000:.1f} ms")
    except Exception as e:
        print(f"FAILED model='{m}': {e}")
