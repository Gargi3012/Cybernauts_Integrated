import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
client = Groq(api_key=api_key)

try:
    res = client.models.list()
    for m in res.data:
        print("Active Groq Model:", m.id)
except Exception as e:
    print("Error listing models:", e)
