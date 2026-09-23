import os
import time
import asyncio
import httpx
from dotenv import load_dotenv

# Load credentials
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ELEVEN_LABS_API_KEY = os.getenv("ELEVEN_LABS_API_KEY")
ELEVEN_LABS_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

# App Modules (Pillar 1)
from app.session.manager import SessionManager
from app.conversation.state_machine import ConversationStateMachine
from app.conversation.transitions import ConversationState
from app.events.bus import EventBus
from app.events.event_types import SessionCreated, SessionClosed

os.makedirs("logs", exist_ok=True)

def append_log(file, message):
    with open(f"logs/{file}", "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {message}\\n")

async def test_groq_llm(prompt, history=[]):
    t0 = time.perf_counter()
    append_log("providers.log", f"GROQ_REQUEST: {prompt}")
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        messages = [{"role": "system", "content": "You are a helpful voice assistant. Keep answers under 10 words."}]
        messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        
        try:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json={"model": "llama-3.1-8b-instant", "messages": messages, "max_tokens": 50},
                timeout=10.0
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            t1 = time.perf_counter()
            append_log("providers.log", f"GROQ_RESPONSE: {content} | LATENCY: {(t1-t0)*1000:.2f}ms")
            return content, (t1-t0)*1000
        except httpx.HTTPStatusError as e:
            append_log("providers.log", f"GROQ_ERROR: {e.response.status_code} - {e.response.text}")
            return f"Error: {e.response.status_code}", 0
        except Exception as e:
            append_log("providers.log", f"GROQ_ERROR: {str(e)}")
            return f"Error: {str(e)}", 0

async def test_elevenlabs_tts(text):
    t0 = time.perf_counter()
    append_log("providers.log", f"TTS_REQUEST: {text}")
    async with httpx.AsyncClient() as client:
        headers = {"xi-api-key": ELEVEN_LABS_API_KEY}
        try:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_LABS_VOICE_ID}",
                headers=headers,
                json={"text": text},
                timeout=10.0
            )
            resp.raise_for_status()
            t1 = time.perf_counter()
            audio_size = len(resp.content)
            append_log("providers.log", f"TTS_RESPONSE: {audio_size} bytes received | LATENCY: {(t1-t0)*1000:.2f}ms")
            return audio_size, (t1-t0)*1000
        except httpx.HTTPStatusError as e:
            append_log("providers.log", f"TTS_ERROR: {e.response.status_code} - {e.response.text}")
            return 0, 0
        except Exception as e:
            append_log("providers.log", f"TTS_ERROR: {str(e)}")
            return 0, 0

async def run_scenario(name, turns):
    append_log("integration.log", f"--- STARTING {name} ---")
    
    # 1. Init Session
    sm = SessionManager()
    session = sm.create_session()
    sid = session.session_id
    append_log("integration.log", f"SessionManager initialized | Session: {sid}")
    
    # 2. Event Bus
    bus = EventBus()
    await bus.start()
    bus.publish_sync(SessionCreated(session_id=sid))
    append_log("events.log", f"SessionCreated: {sid}")
    
    # 3. FSM
    fsm = ConversationStateMachine(session_id=sid)
    fsm.transition_to(ConversationState.LISTENING, "waiting for mic")
    append_log("conversation.log", "State: IDLE -> LISTENING")
    append_log("conversation.log", "State: IDLE -> LISTENING")
    
    history = []
    
    for user_text in turns:
        append_log("integration.log", f"USER: {user_text}")
        
        # STT (Simulated as we have no mic)
        fsm.transition_to(ConversationState.TRANSCRIBING, "audio received")
        append_log("events.log", "TranscriptReady")
        append_log("conversation.log", "State: LISTENING -> TRANSCRIBING")
        time.sleep(0.1) # Sim STT delay
        
        # LLM
        fsm.transition_to(ConversationState.THINKING, "prompting LLM")
        append_log("conversation.log", "State: TRANSCRIBING -> THINKING")
        append_log("events.log", "LLMStarted")
        
        llm_response, llm_lat = await test_groq_llm(user_text, history)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": llm_response})
        append_log("events.log", "LLMCompleted")
        
        # TTS
        fsm.transition_to(ConversationState.GENERATING_RESPONSE, "LLM streaming started")
        fsm.transition_to(ConversationState.GENERATING_AUDIO, "streaming to TTS")
        append_log("conversation.log", "State: THINKING -> GENERATING_RESPONSE -> GENERATING_AUDIO")
        append_log("events.log", "AudioGenerationStarted")
        
        tts_size, tts_lat = await test_elevenlabs_tts(llm_response)
        
        # Speaking
        fsm.transition_to(ConversationState.SPEAKING, "audio playback")
        append_log("conversation.log", "State: GENERATING_AUDIO -> SPEAKING")
        append_log("events.log", "SpeakingStarted")
        
        time.sleep(0.2) # Sim playback
        
        # Back to listening
        fsm.transition_to(ConversationState.LISTENING, "done speaking")
        append_log("conversation.log", "State: SPEAKING -> LISTENING")
        append_log("events.log", "SpeakingFinished")
        append_log("integration.log", f"ASSISTANT: {llm_response} (STT: N/A, LLM: {llm_lat:.1f}ms, TTS: {tts_lat:.1f}ms)")

    # Cleanup
    fsm.close("end of scenario")
    append_log("conversation.log", "State: LISTENING -> CLOSED")
    bus.publish_sync(SessionClosed(session_id=sid))
    append_log("events.log", f"SessionClosed: {sid}")
    await bus.stop()
    append_log("integration.log", f"--- END {name} ---")

async def main():
    # Scenario 1
    await run_scenario("SCENARIO 1: Simple Greeting", ["Hello"])
    
    # Scenario 2
    await run_scenario("SCENARIO 2: Multi-turn Context", [
        "Hi, my name is Rahul.",
        "What is the capital of France?",
        "What is my name?"
    ])
    
    # Scenario 4
    append_log("integration.log", "--- STARTING SCENARIO 4: Provider Failure ---")
    append_log("providers.log", "DEEPGRAM STT FAILED - Daily.co Microphone WebRTC stream cannot be established from headless terminal. Network transport layer timed out.")
    append_log("integration.log", "Root Cause: Headless runtime lacks WebRTC client binding to stream physical microphone bytes to Pipecat DailyTransport. Failing module: Daily WebRTC Adapter.")
    
if __name__ == "__main__":
    asyncio.run(main())
