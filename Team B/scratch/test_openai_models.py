import os
import time
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

test_names = ["gpt-5.6-luna", "gpt-4o-mini"]

for model in test_names:
    try:
        t0 = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hello, how are you?"}],
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
        print(f"SUCCESS model='{model}' | TTFT: {first_token_time*1000:.1f} ms | Total: {t_total*1000:.1f} ms | Text: {full_text.strip()}")
    except Exception as e:
        print(f"FAILED model='{model}': {e}")
