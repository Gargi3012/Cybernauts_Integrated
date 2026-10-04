# Check CriticalCallMemory in context_manager.py
sed -i '' -e 's/session_id: str = ""/session_id: str = ""\
    call_id: str = ""/' app/adapters/pipecat/context_manager.py

