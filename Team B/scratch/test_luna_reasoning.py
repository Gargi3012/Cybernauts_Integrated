import os
import time
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

# Test gpt-5.6-luna WITH reasoning_effort="none"
print("--- Testing gpt-5.6-luna WITH reasoning_effort='none' ---")
try:
    t0 = time.time()
    response = client.chat.completions.create(
        model="gpt-5.6-luna",
        messages=[{"role": "user", "content": "Hello, how are you?"}],
        reasoning_effort="none",
        max_completion_tokens=30,
        stream=True
    )
    first_token_time = None
    full_text = ""
    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            if first_token_time is None:
                first_token_time = time.time() - t0
            full_text += chunk.choices[0].delta.content
    t_total = time.time() - t0
    print(f"SUCCESS gpt-5.6-luna (reasoning=none) | TTFT: {first_token_time*1000:.1f} ms | Total: {t_total*1000:.1f} ms | Text: {full_text.strip()}")
except Exception as e:
    print(f"FAILED gpt-5.6-luna with reasoning_effort='none': {e}")
