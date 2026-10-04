"""deepgram_phone_benchmark.py — Controlled Empirical Evaluation of Deepgram STT for Phone Numbers.

Tests:
- Test A: Continuous digits "9215024687"
- Test B: Spaced digits "9 2 1 5 0 2 4 6 8 7"
- Test C: English words "nine two one five zero two four six eight seven"
- Test D: Hindi words "नौ दो एक पाँच शून्य दो चार छह आठ सात"
- Test E: Hinglish words "nine two ek five zero do four six eight seven"
- Test F: Mixed sentence "राहुल and मेरा phone number है 921 502 4687"
- Test G: Form with zeros "921 0502 4 0401"

Evaluates against Deepgram Configurations:
- Config A: model=nova-2, smart_format=true, numerals=false (Current baseline)
- Config B: model=nova-2, smart_format=false, numerals=true
- Config C: model=nova-2, smart_format=true, numerals=true
- Config D: model=nova-2-phonecall, smart_format=true, numerals=false
- Config E: model=nova-2-phonecall, smart_format=false, numerals=true
- Config F: model=nova-2-phonecall, smart_format=true, numerals=true
"""

import os
import json
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY")

TEST_CASES = {
    "Test_A_Continuous": {
        "text": "9215024687",
        "lang": "en",
        "expected": "9215024687"
    },
    "Test_B_Spaced": {
        "text": "9 2 1 5 0 2 4 6 8 7",
        "lang": "en",
        "expected": "9215024687"
    },
    "Test_C_EnglishWords": {
        "text": "nine two one five zero two four six eight seven",
        "lang": "en",
        "expected": "9215024687"
    },
    "Test_D_HindiWords": {
        "text": "नौ दो एक पाँच शून्य दो चार छह आठ सात",
        "lang": "hi",
        "expected": "9215024687"
    },
    "Test_E_HinglishWords": {
        "text": "nine two ek five zero do four six eight seven",
        "lang": "hi",
        "expected": "9215024687"
    },
    "Test_F_MixedSentence": {
        "text": "Rahul and mera phone number hai 921 502 4687",
        "lang": "hi",
        "expected": "9215024687"
    },
    "Test_G_ProblematicZeros": {
        "text": "921 05 02 4 04 01",
        "lang": "en",
        "expected": "921050240401"
    }
}

CONFIGS = [
    {"name": "Nova2_SmartTrue_NumFalse", "model": "nova-2", "language": "hi", "smart_format": "true", "numerals": "false"},
    {"name": "Nova2_SmartFalse_NumTrue", "model": "nova-2", "language": "hi", "smart_format": "false", "numerals": "true"},
    {"name": "Nova2_SmartTrue_NumTrue", "model": "nova-2", "language": "hi", "smart_format": "true", "numerals": "true"},
    {"name": "Nova2Phone_SmartTrue_NumFalse", "model": "nova-2-phonecall", "language": "en", "smart_format": "true", "numerals": "false"},
    {"name": "Nova2Phone_SmartFalse_NumTrue", "model": "nova-2-phonecall", "language": "en", "smart_format": "false", "numerals": "true"},
    {"name": "Nova2Phone_SmartTrue_NumTrue", "model": "nova-2-phonecall", "language": "en", "smart_format": "true", "numerals": "true"},
]


def synthesize_audio(text: str, lang: str) -> bytes:
    """Synthesizes PCM audio using Cartesia TTS sonic-3.5."""
    import cartesia
    client = cartesia.Cartesia(api_key=CARTESIA_API_KEY)
    voice_id = os.getenv("CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091")
    chunks = list(client.tts.bytes(
        model_id="sonic-3.5",
        transcript=text,
        voice={"mode": "id", "id": voice_id},
        output_format={"container": "wav", "sample_rate": 16000, "encoding": "pcm_s16le"},
        language=lang
    ))
    return b"".join(chunks)


async def transcribe_deepgram(client: httpx.AsyncClient, audio: bytes, config: dict) -> dict:
    """Transcribes audio via Deepgram HTTP Listen API."""
    params = {
        "model": config["model"],
        "language": config["language"],
        "smart_format": config["smart_format"],
        "numerals": config["numerals"],
        "punctuate": "true",
        "encoding": "linear16",
        "sample_rate": "16000",
    }
    # Note: nova-2-phonecall only supports en
    if config["model"] == "nova-2-phonecall":
        params["language"] = "en"

    url = "https://api.deepgram.com/v1/listen"
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "audio/wav"
    }
    resp = await client.post(url, params=params, headers=headers, content=audio, timeout=25.0)
    resp.raise_for_status()
    data = resp.json()
    channels = data.get("results", {}).get("channels", [])
    transcript = ""
    words = []
    if channels:
        alts = channels[0].get("alternatives", [])
        if alts:
            transcript = alts[0].get("transcript", "")
            words = alts[0].get("words", [])
    return {
        "transcript": transcript,
        "words": [w.get("word") for w in words],
        "confidence": alts[0].get("confidence", 0.0) if alts else 0.0
    }


async def run_benchmark():
    print("=" * 80)
    print("DEEPGRAM PHONE-NUMBER RECOGNITION EMPIRICAL BENCHMARK")
    print("=" * 80)

    from app.services.phone_digit_normalizer import PhoneDigitNormalizer

    results = []

    async with httpx.AsyncClient() as client:
        # Step 1: Synthesize all test audios
        print("\n[Phase 1] Synthesizing audio for test cases via Cartesia...")
        audio_cache = {}
        for test_id, info in TEST_CASES.items():
            print(f"  Synthesizing {test_id}: '{info['text']}' (lang={info['lang']})...")
            try:
                audio = synthesize_audio(info["text"], info["lang"])
                audio_cache[test_id] = audio
                print(f"    -> Done ({len(audio)} bytes)")
            except Exception as e:
                print(f"    -> ERROR: {e}")

        # Step 2: Test across configurations
        print("\n[Phase 2] Evaluating across Deepgram configurations...")
        for cfg in CONFIGS:
            cfg_name = cfg["name"]
            print(f"\n--- Testing Configuration: {cfg_name} (model={cfg['model']}, smart_format={cfg['smart_format']}, numerals={cfg['numerals']}) ---")
            for test_id, info in TEST_CASES.items():
                if test_id not in audio_cache:
                    continue
                audio = audio_cache[test_id]
                try:
                    res = await transcribe_deepgram(client, audio, cfg)
                    raw_transcript = res["transcript"]
                    
                    # Test normalizer extraction
                    normalizer = PhoneDigitNormalizer(session_id="benchmark")
                    normalizer.process_utterance(raw_transcript)
                    extracted_digits = normalizer.digits
                    has_colon = ":" in raw_transcript

                    results.append({
                        "config": cfg_name,
                        "test_id": test_id,
                        "spoken_text": info["text"],
                        "raw_transcript": raw_transcript,
                        "has_colon_artifact": has_colon,
                        "extracted_digits": extracted_digits,
                        "expected": info["expected"],
                        "pass": extracted_digits == info["expected"]
                    })
                    print(f"  [{test_id}]")
                    print(f"    Raw STT:     '{raw_transcript}' (has_colon={has_colon})")
                    print(f"    Extracted:   '{extracted_digits}' (Expected: '{info['expected']}') -> {'PASS' if extracted_digits == info['expected'] else 'FAIL'}")
                except Exception as e:
                    print(f"  [{test_id}] ERROR: {e}")

    # Summary table
    print("\n" + "=" * 80)
    print("EMPIRICAL BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"{'Configuration':<30} | {'Test ID':<22} | {'Has Colon?':<11} | {'Raw Transcript':<35} | {'Extracted':<15} | {'Result'}")
    print("-" * 125)
    for r in results:
        res_str = "PASS" if r["pass"] else "FAIL"
        print(f"{r['config']:<30} | {r['test_id']:<22} | {str(r['has_colon_artifact']):<11} | {r['raw_transcript'][:35]:<35} | {r['extracted_digits']:<15} | {res_str}")

    # Save to json artifact
    out_path = "scratch/deepgram_phone_benchmark_results.json"
    os.makedirs("scratch", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved raw results to {out_path}")


if __name__ == "__main__":
    asyncio.run(run_benchmark())
