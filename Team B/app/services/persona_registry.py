"""
AI Agent Persona Registry for Dynamic Multi-Voice & Multi-Persona Architecture.

Provides canonical persona profiles bound to Sarvam AI voice models, genders,
names, and natural conversational greetings. Ensures full identity and gender
grammar consistency across English and natural Hinglish.
"""

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    gender: str          # "female" | "male"
    voice: str           # Sarvam voice id, e.g. "shreya", "arvind", "meera", "dhruv"
    model: str           # e.g. "bulbul:v3"
    role: str
    tone: str
    accent: str
    avatar: str
    greeting_en: str
    greeting_hi: str
    greeting_hinglish: str
    hindi_verb: str      # "रही हूँ" (female) | "रहा हूँ" (male)
    hindi_can_verb: str  # "कर सकती हूँ" (female) | "कर सकता हूँ" (male)
    sample_text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Canonical 4 Personas: Shreya (F), Ritu (F), Ratan (M), Manan (M)
CANONICAL_PERSONAS: Dict[str, Persona] = {
    "shreya": Persona(
        id="shreya",
        name="Shreya",
        gender="female",
        voice="shreya",
        model="bulbul:v3",
        role="Friendly Sales & Success Specialist",
        tone="Warm, Conversational & Approachable",
        accent="Indian English / Hinglish",
        avatar="👩",
        greeting_en="Hi, this is Shreya from Flowiz and Cybernauts. I'm calling to discuss workflow automation and voice AI solutions—do you have a quick minute?",
        greeting_hi="नमस्ते, मैं Flowiz से Shreya बोल रही हूँ। मैं आपके बिज़नेस वर्कफ़्लो ऑटोमेशन के बारे में बात करने के लिए कॉल कर रही हूँ—क्या आपके पास एक मिनट है?",
        greeting_hinglish="Hi, main Flowiz se Shreya bol rahi hoon. Main aapke business workflow automation ke baare me baat karne ke liye call kar rahi hoon—kya aapke paas ek minute hai?",
        hindi_verb="रही हूँ",
        hindi_can_verb="कर सकती हूँ",
        sample_text="Hi, main Flowiz se Shreya bol rahi hoon. Hum aapki sales team ke calls ko automate karne me help karte hain."
    ),
    "ritu": Persona(
        id="ritu",
        name="Ritu",
        gender="female",
        voice="ritu",
        model="bulbul:v3",
        role="Client Onboarding & Operations Lead",
        tone="Calm, Clear & Supportive",
        accent="Polite Indian English / Hindi",
        avatar="👩‍💼",
        greeting_en="Hi, this is Ritu from Flowiz and Cybernauts. I'm calling to discuss automating your business workflows—do you have a quick minute?",
        greeting_hi="नमस्ते, मैं Flowiz से Ritu बोल रही हूँ। मैं आपके बिज़नेस ऑपरेशन्स ऑटोमेशन के बारे में बात करने के लिए कॉल कर रही हूँ—क्या आपके पास एक मिनट है?",
        greeting_hinglish="Hi, main Flowiz se Ritu bol rahi hoon. Main aapke business operations automation ke baare me baat karne ke liye call kar rahi hoon—kya aapke paas ek minute hai?",
        hindi_verb="रही हूँ",
        hindi_can_verb="कर सकती हूँ",
        sample_text="Hello, main Flowiz se Ritu bol rahi hoon. Aapka platform onboarding process smooth aur simple banana hamari priority hai."
    ),
    "ratan": Persona(
        id="ratan",
        name="Ratan",
        gender="male",
        voice="ratan",
        model="bulbul:v3",
        role="Enterprise Solutions Consultant",
        tone="Professional, Confident & Authoritative",
        accent="Corporate Indian English / Hinglish",
        avatar="👨",
        greeting_en="Hi, this is Ratan from Flowiz and Cybernauts. I'm calling to discuss automating your business workflows—do you have a quick minute?",
        greeting_hi="नमस्ते, मैं Flowiz से Ratan बोल रहा हूँ। मैं आपके बिज़नेस वर्कफ़्लो ऑटोमेशन के बारे में बात करने के लिए कॉल कर रहा हूँ—क्या आपके पास एक मिनट है?",
        greeting_hinglish="Hi, main Flowiz se Ratan bol raha hoon. Main aapke business workflow automation ke baare me baat karne ke liye call kar raha hoon—kya aapke paas ek minute hai?",
        hindi_verb="रहा हूँ",
        hindi_can_verb="कर सकता हूँ",
        sample_text="Hi, main Flowiz se Ratan bol raha hoon. Hum enterprise businesses ke outbound lead operations ko automate karte hain."
    ),
    "manan": Persona(
        id="manan",
        name="Manan",
        gender="male",
        voice="manan",
        model="bulbul:v3",
        role="Tech Automation & Product Advisor",
        tone="Energetic, Sharp & Modern",
        accent="Modern Indian Tech Hinglish",
        avatar="👨‍💻",
        greeting_en="Hey, this is Manan from Flowiz and Cybernauts. I'm calling to discuss automating your workflows—do you have a quick minute?",
        greeting_hi="नमस्ते, मैं Flowiz से Manan बोल रहा हूँ। मैं आपके वर्कफ़्लो ऑटोमेशन के बारे में बात करने के लिए कॉल कर रहा हूँ—क्या आपके पास एक मिनट है?",
        greeting_hinglish="Hey, main Flowiz se Manan bol raha hoon. Main aapke workflow automation ke baare me baat karne ke liye call kar raha hoon—kya aapke paas ek minute hai?",
        hindi_verb="रहा हूँ",
        hindi_can_verb="कर सकता हूँ",
        sample_text="Hey! Main Flowiz se Manan bol raha hoon. Real-time voice AI pipelines aur automated qualification hamara core expertise hai."
    ),
}

# Persona aliases for backward compatibility
PERSONA_ALIASES: Dict[str, str] = {
    "sara": "shreya",
    "default": "shreya",
    "female": "shreya",
    "male": "ratan",
    "arvind": "ratan",
    "meera": "ritu",
    "dhruv": "manan",
}


def get_persona(persona_id_or_voice: Optional[str] = None) -> Persona:
    """Retrieve a canonical persona by ID, voice name, or alias.
    
    Defaults cleanly to 'shreya' if None or unmapped.
    """
    if not persona_id_or_voice:
        return CANONICAL_PERSONAS["shreya"]

    key = str(persona_id_or_voice).strip().lower()

    # Check direct canonical keys
    if key in CANONICAL_PERSONAS:
        return CANONICAL_PERSONAS[key]

    # Check aliases
    if key in PERSONA_ALIASES:
        resolved_key = PERSONA_ALIASES[key]
        return CANONICAL_PERSONAS.get(resolved_key, CANONICAL_PERSONAS["shreya"])

    # Check voice matching across personas
    for p in CANONICAL_PERSONAS.values():
        if p.voice.lower() == key:
            return p

    # Fallback default
    return CANONICAL_PERSONAS["shreya"]


def list_personas() -> List[Dict[str, Any]]:
    """Return all available personas as a JSON-serializable list."""
    return [p.to_dict() for p in CANONICAL_PERSONAS.values()]


def get_all_personas() -> List[Persona]:
    """Return all available Persona objects."""
    return list(CANONICAL_PERSONAS.values())


SARVAM_VOICE_MAP: Dict[str, str] = {
    "shreya": "shreya",
    "ritu": "ritu",
    "ratan": "ratan",
    "manan": "manan",
    "sara": "shreya",
    "arvind": "ratan",
    "meera": "ritu",
    "dhruv": "manan",
}


def resolve_persona_voice(persona_id: Optional[str] = None, custom_voice: Optional[str] = None) -> str:
    """Resolve the final Sarvam voice identifier."""
    if custom_voice and custom_voice.strip():
        v = custom_voice.strip().lower()
        return SARVAM_VOICE_MAP.get(v, v)
    persona = get_persona(persona_id)
    v = persona.voice.lower()
    return SARVAM_VOICE_MAP.get(v, v)


def resolve_opening_greeting(
    persona_id_or_voice: Optional[str] = None,
    company_context: Optional[Any] = None,
    call_prompt: Optional[str] = None,
    previous_summary: Optional[str] = None,
) -> str:
    """Return the exact, deterministic opening greeting for a call session.
    
    Used consistently across pre-warming tasks and runtime adapter greeting frames
    to guarantee 100% cache hits and sub-millisecond audio delivery.
    """
    import json
    import re

    persona = get_persona(persona_id_or_voice)
    p_name = persona.name

    c_dict: Dict[str, Any] = {}
    if isinstance(company_context, dict):
        c_dict = company_context
    elif isinstance(company_context, str) and company_context.strip():
        try:
            parsed = json.loads(company_context)
            if isinstance(parsed, dict):
                c_dict = parsed
            else:
                c_dict = {"company_name": company_context.strip()}
        except Exception:
            c_dict = {"company_name": company_context.strip()}

    c_name = str(c_dict.get("company_name") or "").strip()
    contact = str(c_dict.get("contact_name") or "").strip()

    # 1. Custom call prompt specified
    if call_prompt and call_prompt.strip():
        cfg_p = call_prompt.strip()
        m = re.search(r'["\'](Hi\b[^"\']+|Hello\b[^"\']+|Hey\b[^"\']+)', cfg_p, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # 2. Outbound company context specified
    if contact and c_name:
        return f"Hi {contact}! This is {p_name} from Flowiz and Cybernauts. I'm reaching out regarding {c_name}—do you have a quick moment to speak?"
    if contact:
        return f"Hi {contact}! This is {p_name} from Flowiz and Cybernauts. Do you have a brief moment to speak?"
    if c_name and c_name.lower() not in ("manual telecom call", "there", "unknown"):
        return f"Hello! This is {p_name} from Flowiz and Cybernauts. I'm reaching out regarding {c_name}—do you have a quick moment to speak?"
    if c_dict:
        return f"Hello! This is {p_name} from Flowiz and Cybernauts. Do you have a brief moment to speak about automating your operations?"

    # 3. Returning customer summary
    if previous_summary and previous_summary.strip():
        return f"Welcome back! This is {p_name} from Flowiz and Cybernauts. How may I assist you today?"

    # 4. Inbound / General fallback
    return persona.greeting_en


# Aliases
PERSONAS = CANONICAL_PERSONAS
AgentPersona = Persona

