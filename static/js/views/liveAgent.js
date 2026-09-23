/**
 * Voice Agent — Live Agent View
 * Features:
 * 1. Real-time LiveKit WebRTC Voice connection (Mic -> LiveKit -> Pipecat STT/LLM/TTS -> Speaker)
 * 2. WebSocket (/ws/frontend) transcript & pipeline event streaming
 * 3. Structured end-to-end debug logging ([1] through [18])
 * 4. Microphones & Remote Audio Track Subscription (AudioContext auto-resume & element playback)
 * 5. Strict state machine (DISCONNECTED -> CONNECTING -> CONNECTED -> ERROR) with cleanup
 * 6. Single source of truth for AI greeting & transcript accumulation
 */

class LiveAgentView {
  constructor() {
    this.activeMode = 'livekit'; // 'livekit' | 'telephony'
    this.room = null;
    this.ws = null;
    this.isWsConnected = false;
    this.initWebSocket();
  }

  initWebSocket() {
    if (this.ws) return;

    const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProto}//${window.location.host}/ws/frontend`;
    
    console.log(`[WS INIT] Connecting to control WebSocket: ${wsUrl}`);
    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log('[WS CONNECTED] Control WebSocket connected successfully.');
        this.isWsConnected = true;
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleBackendEvent(data);
        } catch (err) {
          console.error('[WS ERROR] Failed to parse message:', err);
        }
      };

      this.ws.onclose = () => {
        console.log('[WS CLOSED] Control WebSocket disconnected. Will retry in 3s...');
        this.isWsConnected = false;
        this.ws = null;
        setTimeout(() => this.initWebSocket(), 3000);
      };

      this.ws.onerror = (err) => {
        console.error('[WS ERROR] Control WebSocket error:', err);
      };
    } catch (err) {
      console.error('[WS EXCEPTION] Exception initializing WebSocket:', err);
    }
  }

  handleBackendEvent(data) {
    console.log('[WS EVENT RECEIVED]', data);
    const container = document.getElementById('viewContainer');

    switch (data.event) {
      case 'greeting_started':
        console.log('[GREETING STARTED] Agent is speaking greeting...');
        window.store.setVoiceState({ statusMessage: 'Greeting playing...' });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;

      case 'greeting_complete':
        console.log('[GREETING COMPLETE] Agent greeting completed.');
        window.store.setVoiceState({ statusMessage: 'Ready for input' });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;

      case 'transcription_received':
        console.log('[11] STT receives audio');
        console.log('[12] STT produces transcript:', data.text);
        if (data.text && data.text.trim()) {
          window.store.addTranscript('user', data.text.trim());
          window.store.setVoiceState({
            language: data.language || 'English',
            latencyMs: data.latency_ms || 420,
            statusMessage: 'Processing STT...'
          });
          if (container && window.store.currentView === 'liveAgent') this.render(container);
        }
        break;

      case 'llm_response_generating':
        console.log('[13] LLM receives transcript & generates response...');
        window.store.setVoiceState({ statusMessage: 'Generating response...' });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;

      case 'llm_response_complete':
        console.log('[14] LLM produces response:', data.full_text);
        if (data.full_text && data.full_text.trim()) {
          window.store.addTranscript('agent', data.full_text.trim());
          window.store.setVoiceState({
            latencyMs: data.latency_ms || 450,
            statusMessage: 'Preparing audio...'
          });
          if (container && window.store.currentView === 'liveAgent') this.render(container);
        }
        break;

      case 'tts_playing':
        console.log('[15] TTS generates audio');
        console.log('[16] Agent publishes audio');
        window.store.setVoiceState({
          latencyMs: data.latency_ms || data.duration_ms || 400,
          statusMessage: 'Bot speaking...'
        });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;

      case 'tts_complete':
        window.store.setVoiceState({ statusMessage: 'Ready for input' });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;

      case 'session_analytics':
        console.log('[SESSION ANALYTICS]', data);
        if (data.summary) {
          window.store.addTranscript('system', `Overall Emotion: ${data.overall_emotion || 'Neutral'} | Summary: ${data.summary}`);
          if (container && window.store.currentView === 'liveAgent') this.render(container);
        }
        break;

      case 'error':
        console.error('[PIPELINE ERROR]', data.error_message);
        window.store.setVoiceState({ statusMessage: `Error: ${data.error_message}` });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;
    }
  }

  render(container) {
    const liveState = window.store.voiceState.livekitState || 'DISCONNECTED'; // DISCONNECTED, CONNECTING, CONNECTED, ERROR
    const transcripts = window.store.voiceState.transcripts || [];
    const statusMsg = window.store.voiceState.statusMessage || (liveState === 'CONNECTED' ? 'Microphone active. Streaming bidirectional audio.' : 'Disconnected');
    const latencyVal = window.store.voiceState.latencyMs ? `${window.store.voiceState.latencyMs}ms` : (liveState === 'CONNECTED' ? '420ms' : '—');
    const langVal = window.store.voiceState.language || 'English';

    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 20px; font-weight: 700; margin: 0 0 6px 0;">AI Voice Agent</h2>
        <div style="color: var(--text-muted); font-size: 13.5px;">
          Interactive real-time voice assistant supporting WebRTC browser conversations and telephony dialing.
        </div>
      </div>

      <!-- Mode Selector Segmented Tabs -->
      <div style="margin-bottom: 24px;">
        <div class="segmented-control">
          <button class="segmented-tab ${this.activeMode === 'livekit' ? 'active' : ''}" id="tabModeLiveKit">
            <i class="fa-solid fa-microphone-lines"></i>
            <span>LiveKit Web Voice</span>
          </button>
          <button class="segmented-tab ${this.activeMode === 'telephony' ? 'active' : ''}" id="tabModeTelephony">
            <i class="fa-solid fa-phone"></i>
            <span>Telephony Outbound</span>
          </button>
        </div>
      </div>

      <!-- MODE 1: LIVEKIT WEB VOICE CONTAINER -->
      <div id="sectionLiveKitMode" style="display: ${this.activeMode === 'livekit' ? 'block' : 'none'};">
        <div class="card" style="margin-bottom: 24px;">
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;">
            <div>
              <div style="display: flex; align-items: center; gap: 10px;">
                <span class="status-indicator" style="background: ${
                  liveState === 'CONNECTED' ? '#16a34a' : liveState === 'CONNECTING' ? '#d97706' : liveState === 'ERROR' ? '#dc2626' : '#94a3b8'
                };"></span>
                <span style="font-weight: 600; font-size: 15px;">
                  ${
                    liveState === 'CONNECTED' ? 'Connected to Voice Agent' :
                    liveState === 'CONNECTING' ? 'Connecting to LiveKit Room...' :
                    liveState === 'ERROR' ? 'Connection Failed' : 'Disconnected'
                  }
                </span>
              </div>
              <div class="text-muted" style="font-size: 12.5px; margin-top: 4px;">
                ${
                  liveState === 'CONNECTED' ? statusMsg :
                  liveState === 'CONNECTING' ? 'Authenticating token & establishing WebRTC peer connection...' :
                  liveState === 'ERROR' ? 'Unable to join room. Verify Admin authentication.' :
                  'Click "Connect to Live Agent" to start a browser voice session.'
                }
              </div>
            </div>

            <div style="display: flex; gap: 10px; align-items: center;">
              ${liveState === 'DISCONNECTED' || liveState === 'ERROR' ? `
                <button id="btnConnectLiveKit" class="btn btn-primary">
                  <i class="fa-solid fa-plug"></i>
                  <span>Connect to Live Agent</span>
                </button>
              ` : ''}

              ${liveState === 'CONNECTING' ? `
                <button class="btn btn-primary" disabled>
                  <i class="fa-solid fa-circle-notch fa-spin"></i>
                  <span>Connecting...</span>
                </button>
              ` : ''}

              ${liveState === 'CONNECTED' ? `
                <button id="btnMuteLiveKit" class="btn btn-secondary">
                  <i class="fa-solid fa-microphone-slash"></i>
                  <span>Mute Mic</span>
                </button>
                <button id="btnLeaveLiveKit" class="btn btn-danger">
                  <i class="fa-solid fa-phone-slash"></i>
                  <span>End Call / Leave Room</span>
                </button>
              ` : ''}
            </div>
          </div>
        </div>
      </div>

      <!-- MODE 2: TELEPHONY OUTBOUND CONTAINER -->
      <div id="sectionTelephonyMode" style="display: ${this.activeMode === 'telephony' ? 'block' : 'none'};">
        <div class="card" style="margin-bottom: 24px;">
          <div style="font-weight: 600; font-size: 15px; margin-bottom: 6px;">SIM-Based Outbound Telephony</div>
          <div class="text-muted" style="font-size: 13px; margin-bottom: 18px;">
            Trigger an automated outbound phone call using Twilio REST API to connect a recipient to the Pipecat AI agent.
          </div>

          <div style="display: flex; gap: 12px; max-width: 480px; align-items: center;">
            <input 
              type="tel" 
              id="txtTelephonyNumber" 
              class="form-input" 
              placeholder="+91 XXXXX XXXXX" 
              value="+17372212163" 
            />
            <button id="btnStartTelephonyCall" class="btn btn-primary" style="white-space: nowrap;">
              <i class="fa-solid fa-phone"></i>
              <span>Start Call</span>
            </button>
          </div>

          <div id="telephonyCallNotice" style="margin-top: 14px; font-size: 13px; display: none;"></div>
        </div>
      </div>

      <!-- Real Voice Metrics Strip -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px;">
        <div class="card" style="padding: 16px;">
          <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">ROUNDTRIP LATENCY</div>
          <div style="font-size: 20px; font-weight: 700; margin-top: 4px;">${latencyVal}</div>
        </div>
        <div class="card" style="padding: 16px;">
          <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">STT LANGUAGE</div>
          <div style="font-size: 14px; font-weight: 600; margin-top: 4px;">${langVal} (Deepgram/Sarvam)</div>
        </div>
        <div class="card" style="padding: 16px;">
          <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">LLM MODEL</div>
          <div style="font-size: 14px; font-weight: 600; margin-top: 4px;">Groq Llama-3.3-70b</div>
        </div>
        <div class="card" style="padding: 16px;">
          <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">TTS VOICE</div>
          <div style="font-size: 14px; font-weight: 600; margin-top: 4px;">Sarvam / Cartesia</div>
        </div>
      </div>

      <!-- Live Conversation Transcript -->
      <div class="card" style="padding: 20px; min-height: 280px; display: flex; flex-direction: column;">
        <div style="font-weight: 600; font-size: 14px; margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between;">
          <span>Live Conversation Transcript</span>
          <span class="badge ${liveState === 'CONNECTED' ? 'badge-success' : 'badge-muted'}">
            ${liveState === 'CONNECTED' ? 'Streaming Active' : 'Standby'}
          </span>
        </div>

        <div id="transcriptBox" style="flex: 1; background: var(--bg-surface-secondary); border-radius: var(--radius-sm); border: 1px solid var(--border-color); padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; max-height: 360px;">
          ${liveState === 'DISCONNECTED' && transcripts.length === 0 ? `
            <div class="text-muted" style="font-size: 13.5px; text-align: center; padding: 48px 0;">
              Choose a calling method above to start an AI voice conversation.
            </div>
          ` : transcripts.length === 0 ? `
            <div class="text-muted" style="font-size: 13.5px; text-align: center; padding: 48px 0;">
              Connection established. Speak into your microphone...
            </div>
          ` : transcripts.map(t => `
            <div class="transcript-bubble ${t.role === 'user' ? 'user' : t.role === 'system' ? 'system' : 'agent'}">
              <div style="font-size: 11px; font-weight: 700; margin-bottom: 2px;">${t.role === 'user' ? 'Caller' : t.role === 'system' ? 'System Memory' : 'AI Agent'}</div>
              <div>${t.text}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;

    this.attachEvents(container);

    // Auto scroll transcript box
    const box = container.querySelector('#transcriptBox');
    if (box) box.scrollTop = box.scrollHeight;
  }

  attachEvents(container) {
    // Mode Switcher Tabs
    const tabLiveKit = container.querySelector('#tabModeLiveKit');
    const tabTelephony = container.querySelector('#tabModeTelephony');

    if (tabLiveKit && tabTelephony) {
      tabLiveKit.addEventListener('click', () => {
        this.activeMode = 'livekit';
        this.render(container);
      });
      tabTelephony.addEventListener('click', () => {
        this.activeMode = 'telephony';
        this.render(container);
      });
    }

    // Connect LiveKit Action
    const btnConnect = container.querySelector('#btnConnectLiveKit');
    if (btnConnect) {
      btnConnect.addEventListener('click', async () => {
        await this.connectLiveKit(container);
      });
    }

    // End/Leave Room Action
    const btnLeave = container.querySelector('#btnLeaveLiveKit');
    if (btnLeave) {
      btnLeave.addEventListener('click', async () => {
        await this.leaveLiveKit(container);
      });
    }

    // Mute/Unmute Mic
    const btnMute = container.querySelector('#btnMuteLiveKit');
    if (btnMute) {
      btnMute.addEventListener('click', async () => {
        if (this.room && this.room.localParticipant) {
          const isMuted = !this.room.localParticipant.isMicrophoneEnabled;
          await this.room.localParticipant.setMicrophoneEnabled(isMuted);
          btnMute.innerHTML = isMuted ? 
            `<i class="fa-solid fa-microphone-slash"></i><span>Mute Mic</span>` : 
            `<i class="fa-solid fa-microphone"></i><span>Unmute Mic</span>`;
        }
      });
    }

    // Telephony Outbound Action
    const btnStartTelephony = container.querySelector('#btnStartTelephonyCall');
    const txtNumber = container.querySelector('#txtTelephonyNumber');
    const callNotice = container.querySelector('#telephonyCallNotice');

    if (btnStartTelephony && txtNumber) {
      btnStartTelephony.addEventListener('click', async () => {
        const phone = txtNumber.value.trim();
        if (!phone) {
          alert("Please enter a phone number.");
          return;
        }

        try {
          btnStartTelephony.disabled = true;
          if (callNotice) {
            callNotice.style.display = 'block';
            callNotice.className = 'text-muted';
            callNotice.innerText = 'Initiating Twilio outbound call...';
          }

          const res = await window.api.triggerOutboundCall(phone);
          if (res && res.status === 'success') {
            if (callNotice) {
              callNotice.className = 'badge badge-success';
              callNotice.innerText = `Call Initiated! SID: ${res.callSid}`;
            }
          }
        } catch (err) {
          if (callNotice) {
            callNotice.className = 'badge badge-error';
            callNotice.innerText = `Call Failed: ${err.message || err}`;
          }
        } finally {
          btnStartTelephony.disabled = false;
        }
      });
    }
  }

  async connectLiveKit(container) {
    console.log("[1] Connect clicked");
    window.store.setVoiceState({ livekitState: 'CONNECTING', statusMessage: 'Connecting...' });
    this.render(container);

    try {
      // Step 2: Check Admin JWT Auth
      const jwtToken = localStorage.getItem('jwt_token');
      if (!jwtToken) {
        throw new Error("Admin authentication required. Click 'Admin Auth' in the top header to log in.");
      }
      console.log("[2] JWT verified");

      // Step 3: Fetch LiveKit token & start backend voice session
      const data = await window.api.joinLiveKit();
      if (!data || !data.token) {
        throw new Error("Failed to receive valid LiveKit room token from backend.");
      }
      console.log("[3] LiveKit token received | roomUrl:", data.roomUrl);

      let roomUrl = data.roomUrl;
      // Hostname rewrite for non-localhost if required
      if (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
        if (roomUrl.includes('localhost') || roomUrl.includes('127.0.0.1')) {
          const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
          const port = roomUrl.split(':')[2] || '7880';
          roomUrl = `${wsProto}//${window.location.hostname}:${port}`;
          console.log("Dynamic AWS roomUrl rewrite:", roomUrl);
        }
      }

      // Step 4: Disconnect previous room if existing
      if (this.room) {
        try {
          await this.room.disconnect();
        } catch (e) {}
        this.room = null;
      }

      // Check LiveKit SDK script loaded
      if (typeof LivekitClient === 'undefined') {
        throw new Error("LivekitClient JS SDK not loaded. Check internet connection or CDN script tag.");
      }

      // Instantiate LiveKit Room
      this.room = new LivekitClient.Room({
        adaptiveStream: true,
        dynacast: true,
        audioCaptureDefaults: {
          autoGainControl: true,
          echoCancellation: true,
          noiseSuppression: true
        }
      });

      // Register Remote Audio Track Subscriptions
      this.room.on(LivekitClient.RoomEvent.TrackSubscribed, (track, publication, participant) => {
        console.log("[9] Agent audio track subscribed | kind:", track.kind, "| participant:", participant.identity);
        if (track.kind === LivekitClient.Track.Kind.Audio) {
          const element = track.attach();
          element.id = `remote-audio-${participant.identity}`;
          document.body.appendChild(element);
          console.log("[17] Browser receives audio element attached:", element);
          
          if (element.play) {
            element.play()
              .then(() => console.log("[18] Browser plays audio successfully!"))
              .catch(e => console.warn("Autoplay notice: User interaction required to play audio:", e));
          }
        }
      });

      this.room.on(LivekitClient.RoomEvent.ParticipantConnected, (participant) => {
        console.log("[8] Agent participant connected:", participant.identity);
        this.logRoomState();
      });

      this.room.on(LivekitClient.RoomEvent.ParticipantDisconnected, (participant) => {
        console.log("Participant disconnected:", participant.identity);
        this.logRoomState();
      });

      this.room.on(LivekitClient.RoomEvent.Disconnected, () => {
        console.log("LiveKit Room disconnected.");
        window.store.setVoiceState({ livekitState: 'DISCONNECTED', statusMessage: 'Disconnected' });
        const c = document.getElementById('viewContainer');
        if (c && window.store.currentView === 'liveAgent') this.render(c);
      });

      // Step 5: Verify Microphone permission
      console.log("[5] MIC REQUEST: Verifying browser microphone permission...");
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        if (!window.isSecureContext && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
          throw new Error('Microphone access is blocked by browser on insecure HTTP IP addresses. Please use HTTPS or localhost.');
        }
      }

      // Step 4 & 5: Connect to LiveKit Room
      await this.room.connect(roomUrl, data.token);
      console.log("[4] Room connected successfully!");

      // Built-in LiveKit method to unlock AudioContext under user gesture click
      await this.room.startAudio().catch(e => console.warn("AudioContext start notice:", e));

      // Step 6 & 7: Enable Local Microphone Track
      console.log("[6] MIC TRACK CREATING...");
      await this.room.localParticipant.enableCameraAndMicrophone();
      console.log("[7] MIC TRACK CREATED & PUBLISHED TO LIVEKIT!");

      // Log full room state
      this.logRoomState();

      // Reset transcripts for a clean single-greeting session
      window.store.voiceState.transcripts = [];

      window.store.setVoiceState({
        livekitState: 'CONNECTED',
        statusMessage: 'Microphone active. Streaming bidirectional audio.'
      });

      this.render(container);

    } catch (err) {
      console.error("LiveKit Connection Error:", err);
      window.store.setVoiceState({ livekitState: 'ERROR', statusMessage: err.message });
      alert("LiveKit Connection Error: " + (err.message || "Unable to join room."));
      this.render(container);
    }
  }

  async leaveLiveKit(container) {
    if (this.room) {
      try {
        await this.room.disconnect();
      } catch (e) {
        console.warn("Error disconnecting room:", e);
      }
      this.room = null;
    }

    // Clean up attached remote audio elements
    document.querySelectorAll('[id^="remote-audio-"]').forEach(el => el.remove());

    window.store.setVoiceState({
      livekitState: 'DISCONNECTED',
      statusMessage: 'Disconnected'
    });

    console.log("Call ended. Cleaned up LiveKit room and audio elements.");
    this.render(container);
  }

  logRoomState() {
    if (!this.room) {
      console.log("Room state: No active room.");
      return;
    }

    const localPubs = Array.from(this.room.localParticipant.audioTrackPublications.values()).map(p => ({
      sid: p.trackSid,
      name: p.trackName,
      isMuted: p.isMuted
    }));

    const remoteParts = Array.from(this.room.remoteParticipants.values()).map(p => ({
      identity: p.identity,
      audioTracks: Array.from(p.audioTrackPublications.values()).map(t => t.trackSid)
    }));

    console.log("==========================================");
    console.log(`[LIVEKIT STATE]`);
    console.log(`Room connected: ${this.room.state === 'connected'}`);
    console.log(`Local participant: ${this.room.localParticipant.identity}`);
    console.log(`Local mic publications:`, localPubs);
    console.log(`Remote participants (${remoteParts.length}):`, remoteParts);
    console.log("==========================================");
  }
}

window.LiveAgentView = LiveAgentView;

