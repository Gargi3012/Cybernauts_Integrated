from groq import Groq
from app.config import GROQ_API_KEY

client = Groq(api_key=GROQ_API_KEY)
models = [m.id for m in client.models.list().data]
print("Available Groq models:", models)
