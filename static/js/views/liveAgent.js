/**
 * Voice Agent — Live Interactive Console View
 * Dual-Mode Voice Console:
 * 1. Telephony Outbound (Plivo PSTN with Lead Traceability)
 * 2. WebRTC Live Voice (LiveKit in-browser mic session)
 * Powered by real-time WebSocket (/ws/frontend) event streaming
 */

class LiveAgentView {
  constructor() {
    this.activeMode = 'telephony'; // 'telephony' (Plivo) or 'livekit' (WebRTC)
    this.livekitRoom = null;
    this.isLiveKitConnected = false;
    this.isLiveKitConnecting = false;
    this.ws = null;
    this.isWsConnected = false;
    this.callTimer = null;
    this.callElapsedSec = 0;
    this.initWebSocket();
  }

  initWebSocket() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProto}//${window.location.host}/ws/frontend`;
    
    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.isWsConnected = true;
        this.updateConnectionStatus(true);
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
        this.isWsConnected = false;
        this.updateConnectionStatus(false);
        this.ws = null;
        setTimeout(() => this.initWebSocket(), 3000);
      };

      this.ws.onerror = (err) => {
        this.isWsConnected = false;
        this.updateConnectionStatus(false);
      };
    } catch (err) {
      console.error('[WS EXCEPTION] Exception initializing WebSocket:', err);
    }
  }

  updateConnectionStatus(connected) {
    const pill = document.getElementById('wsConnectionPill');
    if (pill) {
      if (connected) {
        pill.innerHTML = '<span class="status-indicator" style="background:#16a34a;"></span><span>WebSocket Connected</span>';
        pill.className = 'status-pill status-online';
      } else {
        pill.innerHTML = '<span class="status-indicator" style="background:#d97706;"></span><span>Reconnecting...</span>';
        pill.className = 'status-pill status-warning';
      }
    }
  }

  handleBackendEvent(data) {
    const container = document.getElementById('viewContainer');

    switch (data.event) {
      case 'greeting_started':
        window.store.setVoiceState({
          speakerState: 'ai_speaking',
          statusMessage: 'AI greeting prospect...'
        });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;

      case 'greeting_complete':
        window.store.setVoiceState({
          speakerState: 'idle',
          statusMessage: 'Listening for prospect speech...'
        });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;

      case 'transcription_received':
        if (data.text && data.text.trim()) {
          window.store.addTranscript('user', data.text.trim(), {
            language: data.language || 'English',
            emotion: data.emotion || 'Neutral',
            latencyMs: data.latency_ms || null
          });
          window.store.setVoiceState({
            language: data.language || 'English',
            latencyMs: data.latency_ms || 420,
            speakerState: 'user_speaking',
            statusMessage: `Prospect speaking (${data.language || 'Detected'})`
          });
          if (container && window.store.currentView === 'liveAgent') this.render(container);
        }
        break;

      case 'llm_response_generating':
        window.store.setVoiceState({
          speakerState: 'thinking',
          statusMessage: 'AI generating response...'
        });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;

      case 'llm_response_complete':
        if (data.full_text && data.full_text.trim()) {
          window.store.addTranscript('agent', data.full_text.trim(), {
            latencyMs: data.latency_ms || null
          });
          window.store.setVoiceState({
            latencyMs: data.latency_ms || 450,
            statusMessage: 'Synthesizing voice audio...'
          });
          if (container && window.store.currentView === 'liveAgent') this.render(container);
        }
        break;

      case 'tts_playing':
        window.store.setVoiceState({
          speakerState: 'ai_speaking',
          latencyMs: data.latency_ms || data.duration_ms || 400,
          statusMessage: 'AI speaking...'
        });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;

      case 'tts_complete':
        window.store.setVoiceState({
          speakerState: 'idle',
          statusMessage: 'Listening for prospect...'
        });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;

      case 'lead_qualification_completed':
        // Real qualification result from backend
        if (data.lead_id && data.qualification) {
          window.store.updateLeadQualification(data.lead_id, data.qualification);
          window.store.updateActiveCall({
            call_status: 'completed',
            qualification: data.qualification
          });
          window.store.setVoiceState({
            isCallActive: false,
            speakerState: 'idle',
            statusMessage: 'Call completed. Qualification evaluated.'
          });
          this.stopCallTimer();
          if (container && window.store.currentView === 'liveAgent') this.render(container);
        }
        break;

      case 'session_analytics':
        if (data.summary) {
          window.store.addTranscript('system', `Session Closed. Summary: ${data.summary}`);
          if (container && window.store.currentView === 'liveAgent') this.render(container);
        }
        break;

      case 'error':
        window.store.setVoiceState({
          statusMessage: `Pipeline notice: ${data.error_message}`
        });
        if (container && window.store.currentView === 'liveAgent') this.render(container);
        break;
    }
  }

  startCallTimer() {
    this.stopCallTimer();
    this.callElapsedSec = 0;
    this.callTimer = setInterval(() => {
      this.callElapsedSec++;
      const timerEl = document.getElementById('liveCallDuration');
      if (timerEl) {
        const mins = String(Math.floor(this.callElapsedSec / 60)).padStart(2, '0');
        const secs = String(this.callElapsedSec % 60).padStart(2, '0');
        timerEl.innerText = `${mins}:${secs}`;
      }
    }, 1000);
  }

  stopCallTimer() {
    if (this.callTimer) {
      clearInterval(this.callTimer);
      this.callTimer = null;
    }
  }

  render(container) {
    const activeCall = window.store.activeCall;
    const voiceState = window.store.voiceState;
    const transcripts = voiceState.transcripts || [];
    const speakerState = voiceState.speakerState || 'idle';
    const statusMsg = voiceState.statusMessage || 'Console Ready';
    const latencyVal = voiceState.latencyMs ? `${voiceState.latencyMs}ms` : '—';
    const langVal = voiceState.language || 'English / Hindi';

    container.innerHTML = `
      <div style="margin-bottom: 20px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 12px;">
        <div>
          <h1 style="font-size: 22px; font-weight: 800; margin: 0 0 6px 0; color: var(--text-primary);">AI Voice Agent Console</h1>
          <div style="color: var(--text-muted); font-size: 13.5px;">
            Real-time conversational pipeline monitoring, live transcript streaming, and bilingual prospect qualification.
          </div>
        </div>
        <div id="wsConnectionPill" class="status-pill ${this.isWsConnected ? 'status-online' : 'status-warning'}">
          <span class="status-indicator" style="background: ${this.isWsConnected ? '#16a34a' : '#d97706'};"></span>
          <span>${this.isWsConnected ? 'WebSocket Connected' : 'Connecting...'}</span>
        </div>
      </div>

      <!-- Mode Selector Tabs -->
      <div style="margin-bottom: 20px;">
        <div class="segmented-control">
          <button class="segmented-tab ${this.activeMode === 'telephony' ? 'active' : ''}" id="tabModeTelephony">
            <i class="fa-solid fa-phone"></i>
            <span>Plivo Telephony (PSTN)</span>
          </button>
          <button class="segmented-tab ${this.activeMode === 'livekit' ? 'active' : ''}" id="tabModeLiveKit">
            <i class="fa-solid fa-microphone-lines"></i>
            <span>LiveKit WebRTC (Browser)</span>
          </button>
        </div>
      </div>

      <!-- ACTIVE TELEPHONY CALL HERO (IF CALL IS ACTIVE) -->
      ${activeCall ? `
        <div class="card" style="margin-bottom: 20px; padding: 20px; border: 1px solid rgba(107, 33, 168, 0.3); background: linear-gradient(180deg, #faf5ff 0%, #ffffff 100%);">
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 14px;">
            <div style="display: flex; align-items: center; gap: 12px;">
              <div style="width: 42px; height: 42px; border-radius: 8px; background: #6b21a8; color: #ffffff; display: flex; align-items: center; justify-content: center; font-size: 18px;">
                <i class="fa-solid fa-phone-volume ${activeCall.call_status === 'initiated' || activeCall.call_status === 'in_progress' ? 'fa-shake' : ''}"></i>
              </div>
              <div>
                <div style="font-weight: 800; font-size: 16px; color: var(--text-primary);">${activeCall.company_name || 'Active Prospect Call'}</div>
                <div class="font-mono text-muted" style="font-size: 12px;">
                  Target: <strong>${activeCall.phone}</strong> · Provider: Plivo PSTN
                </div>
              </div>
            </div>

            <!-- Call State & Timer -->
            <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
              <div style="text-align: right;">
                <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Duration</div>
                <div class="font-mono" style="font-size: 18px; font-weight: 700; color: var(--text-primary);" id="liveCallDuration">00:00</div>
              </div>
              <span class="badge ${activeCall.call_status === 'completed' ? 'badge-success' : 'badge-warning'}" style="font-size: 12px; padding: 6px 12px;">
                ${activeCall.call_status === 'completed' ? '✓ Call Completed' : '● ' + (activeCall.call_status || 'In Progress')}
              </span>
              ${activeCall.call_status !== 'completed' ? `
                <button class="btn btn-sm" id="btnHangupLiveCall" style="background: #dc2626; border: 1px solid #b91c1c; color: #ffffff; padding: 6px 12px; font-weight: 700; cursor: pointer;" title="Immediately hang up phone call">
                  <i class="fa-solid fa-phone-slash" style="margin-right: 4px;"></i>Hang Up
                </button>
              ` : `
                <button class="btn btn-sm btn-primary" id="btnNewCallTelephony" style="background: #6b21a8; border: 1px solid #581c87; color: #ffffff; padding: 6px 14px; font-weight: 700; cursor: pointer;" title="Dial another phone number">
                  <i class="fa-solid fa-phone" style="margin-right: 4px;"></i>Dial Another Number
                </button>
              `}
              <button class="btn btn-sm btn-secondary" id="btnDismissCallHero" style="padding: 6px 10px; font-size: 12px; cursor: pointer;" title="Dismiss call summary">
                <i class="fa-solid fa-xmark"></i>
              </button>
            </div>
          </div>

          <!-- Traceability IDs Bar -->
          <div style="display: flex; gap: 16px; flex-wrap: wrap; padding: 10px 12px; background: rgba(107, 33, 168, 0.05); border-radius: 6px; font-size: 11.5px; border: 1px solid rgba(107, 33, 168, 0.15);" class="font-mono text-muted">
            <div><strong>Lead:</strong> ${activeCall.lead_id || '—'}</div>
            <div><strong>Dispatch:</strong> ${activeCall.dispatch_id || '—'}</div>
            <div><strong>Session:</strong> ${activeCall.session_id || '—'}</div>
            <div><strong>Call UUID:</strong> ${activeCall.call_uuid || '—'}</div>
          </div>

          <!-- Active Custom Script Preview (if configured) -->
          ${activeCall.call_prompt ? `
            <div style="margin-top: 12px; padding: 10px 14px; background: rgba(107, 33, 168, 0.06); border-radius: 6px; font-size: 12px; border: 1px dashed rgba(107, 33, 168, 0.3);">
              <div style="font-weight: 700; color: #581c87; margin-bottom: 3px; display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-scroll"></i>
                <span>Active Call-Specific Script & Instructions:</span>
              </div>
              <div style="color: var(--text-primary); font-style: italic; line-height: 1.4;">
                "${activeCall.call_prompt}"
              </div>
            </div>
          ` : ''}

          <!-- Completed Qualification Card (if available) -->
          ${activeCall.qualification ? `
            <div style="margin-top: 14px; padding: 14px; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 6px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <div style="font-weight: 700; color: #065f46; font-size: 14px;">
                  ✓ AI Qualification Evaluated
                </div>
                <span class="badge badge-success" style="font-size: 12px;">Score: ${activeCall.qualification.qualification_score || 0}/100</span>
              </div>
              <div style="font-size: 12.5px; color: #047857; margin-bottom: 8px;">
                ${activeCall.qualification.conversation_summary || 'Outbound qualification concluded successfully.'}
              </div>
              <button class="btn btn-secondary btn-sm" id="btnBackToLead" data-domain="${activeCall.lead_id}">
                <i class="fa-solid fa-address-card"></i> Return to Updated Lead Dossier
              </button>
            </div>
          ` : ''}
        </div>
      ` : ''}

      <!-- DIALER & CALL PROMPTING CONSOLE (WHEN IN TELEPHONY MODE & NO ACTIVE UNFINISHED CALL) -->
      ${this.activeMode === 'telephony' && (!activeCall || activeCall.call_status === 'completed') ? `
        <div class="card" style="margin-bottom: 20px; padding: 24px; border: 1px solid var(--border-color); box-shadow: var(--shadow-sm);">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; border-bottom: 1px solid var(--border-color); padding-bottom: 14px; flex-wrap: wrap; gap: 12px;">
            <div>
              <h3 style="margin: 0 0 4px 0; font-size: 16px; font-weight: 800; color: var(--text-primary);">
                <i class="fa-solid fa-headset" style="color: #6b21a8; margin-right: 6px;"></i>
                AI Outbound Dialer & Call Script Console
              </h3>
              <div style="font-size: 12.5px; color: var(--text-muted);">
                Describe what the customer is and what they are discussing, customize the AI prompt, and dial via Plivo PSTN.
              </div>
            </div>
            <div style="display: flex; gap: 8px; align-items: center;">
              <select id="selHarvestedLead" class="form-control" style="font-size: 12px; padding: 6px 10px; border-radius: 6px; max-width: 250px; background: #ffffff; border: 1px solid var(--border-color);">
                <option value="">-- Quick Load Lead (Optional) --</option>
                ${(window.store.allLeads || []).map(l => `
                  <option value="${l.domain || l.website}">${l.company_name || l.domain} (${(l.phones && l.phones[0]) ? l.phones[0] : 'no phone'})</option>
                `).join('')}
              </select>
            </div>
          </div>

          <!-- Customer Context & Dial Information -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 16px;">
            <div>
              <label for="txtManualPhone" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                <i class="fa-solid fa-phone" style="color: #6b21a8; margin-right: 4px;"></i> Phone Number (E.164) *
              </label>
              <input 
                type="text" 
                id="txtManualPhone" 
                class="form-input font-mono" 
                placeholder="e.g. +917082968702" 
                value="+917082968702"
                style="font-size: 13.5px; width: 100%;"
              />
            </div>
            <div>
              <label for="txtCustomerName" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                <i class="fa-solid fa-building" style="color: #6b21a8; margin-right: 4px;"></i> Customer / Company Name
              </label>
              <input 
                type="text" 
                id="txtCustomerName" 
                class="form-input" 
                placeholder="e.g. Cybernauts Technologies" 
                value=""
                style="font-size: 13.5px; width: 100%;"
              />
            </div>
            <div>
              <label for="txtCustomerContext" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                <i class="fa-solid fa-briefcase" style="color: #6b21a8; margin-right: 4px;"></i> Customer Context / Topics Discussed
              </label>
              <input 
                type="text" 
                id="txtCustomerContext" 
                class="form-input" 
                placeholder="e.g. AI automation software, looking to automate qualification" 
                value=""
                style="font-size: 13.5px; width: 100%;"
              />
            </div>
          </div>

          <!-- Prompting Area: Call Script & Instructions -->
          <div style="background: var(--bg-surface-secondary); padding: 16px; border-radius: 8px; border: 1px solid var(--border-color); margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
              <label for="txtCallPrompt" style="font-size: 13px; font-weight: 800; color: var(--text-primary); display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-scroll" style="color: #6b21a8;"></i>
                <span>Call Script & AI Agent Prompt (Optional)</span>
              </label>
              <div style="display: flex; align-items: center; gap: 8px;">
                <select id="selCallScriptTemplate" class="form-control" style="font-size: 11.5px; padding: 4px 8px; border-radius: 6px; background: #fff; border: 1px solid var(--border-color);">
                  <option value="">-- Script Templates --</option>
                  <option value="b2b_discovery">Standard B2B Discovery</option>
                  <option value="ai_automation">AI Voice Automation Pitch</option>
                  <option value="executive_followup">Executive Follow-Up</option>
                </select>
                <span id="callPromptCharCountLive" style="font-size: 11px; font-family: monospace; color: var(--text-muted);">0 / 2500</span>
                <button type="button" id="btnClearPromptLive" class="btn btn-secondary btn-sm" style="padding: 2px 8px; font-size: 11px;">Clear</button>
              </div>
            </div>

            <textarea 
              id="txtCallPrompt" 
              class="form-input" 
              rows="4" 
              maxlength="2500" 
              placeholder="Write what this call is about, topics to discuss, questions to ask, qualification criteria, and how the AI agent should handle the customer. (e.g. Introduce yourself as Sara from Flowiz. Inquire about their current outbound lead qualification process and biggest bottlenecks. If interested, propose a 15-minute product walkthrough. Be warm and concise.)."
              style="width: 100%; font-size: 12.5px; line-height: 1.45; resize: vertical; font-family: inherit;"
            ></textarea>

            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; font-size: 11px; color: var(--text-muted); flex-wrap: wrap; gap: 6px;">
              <span style="display: flex; align-items: center; gap: 4px;">
                <i class="fa-solid fa-shield-halved" style="color: #6b21a8;"></i>
                <strong>Call Scoped:</strong> Injected as Level 3 LLM instruction for this call only. Core safety, phone validation, and auto-hangup remain active.
              </span>
            </div>
          </div>

          <!-- Launch Button Bar -->
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
            <div style="font-size: 12px; color: var(--text-muted);">
              Or launch directly with pre-filled context from <a href="#leads" style="color: var(--color-primary); font-weight: 700;">All Leads</a>.
            </div>
            <div>
              <button class="btn btn-primary" id="btnManualDial" style="background: #6b21a8; border-color: #581c87; padding: 10px 22px; font-weight: 700; font-size: 13.5px;">
                <i class="fa-solid fa-phone-volume" style="margin-right: 6px;"></i>
                <span>Launch AI Call with Script</span>
              </button>
            </div>
          </div>
        </div>
      ` : ''}

      <!-- WEBRTC BROWSER VOICE MODE (IF IN LIVEKIT MODE) -->
      ${this.activeMode === 'livekit' ? `
        <div class="card" style="margin-bottom: 20px; padding: 24px; border: 1px solid ${this.isLiveKitConnected ? 'rgba(107, 33, 168, 0.4)' : 'var(--border-color)'}; background: ${this.isLiveKitConnected ? 'linear-gradient(180deg, #faf5ff 0%, #ffffff 100%)' : 'var(--bg-card)'};">
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;">
            <div style="display: flex; align-items: center; gap: 14px;">
              <div style="width: 44px; height: 44px; border-radius: 10px; background: ${this.isLiveKitConnected ? '#6b21a8' : 'var(--bg-surface-secondary)'}; color: ${this.isLiveKitConnected ? '#fff' : 'var(--text-secondary)'}; display: flex; align-items: center; justify-content: center; font-size: 20px;">
                <i class="fa-solid fa-headset ${this.isLiveKitConnected ? 'fa-beat-fade' : ''}"></i>
              </div>
              <div>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <h3 style="margin: 0; font-size: 16px; font-weight: 800; color: var(--text-primary);">In-Browser WebRTC Voice Session</h3>
                  <span class="badge ${this.isLiveKitConnected ? 'badge-success' : 'badge-neutral'}" style="font-size: 11px;">
                    ${this.isLiveKitConnected ? '● Connected & Speaking' : (this.isLiveKitConnecting ? '● Connecting...' : '○ Disconnected')}
                  </span>
                </div>
                <div class="text-muted" style="font-size: 13px; margin-top: 2px;">
                  ${this.isLiveKitConnected 
                    ? 'Microphone active (Camera OFF). Speak naturally; the AI Agent will respond in real time.' 
                    : 'Connect your microphone and speak directly with Sara AI in English & Hindi with zero latency.'}
                </div>
              </div>
            </div>
            <div style="display: flex; gap: 10px; align-items: center;">
              ${this.isLiveKitConnected ? `
                <button class="btn" id="btnDisconnectLiveKit" style="background: #dc2626; border: 1px solid #b91c1c; color: #fff; padding: 9px 18px; font-weight: 700; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 6px;" title="Hang up and stop microphone">
                  <i class="fa-solid fa-phone-slash"></i>
                  <span>Hang Up / Disconnect</span>
                </button>
              ` : `
                <button class="btn btn-primary" id="btnConnectLiveKit" ${this.isLiveKitConnecting ? 'disabled' : ''} style="background: #6b21a8; border-color: #581c87; padding: 9px 20px; font-weight: 700; border-radius: 6px; display: flex; align-items: center; gap: 6px; cursor: pointer;">
                  <i class="fa-solid ${this.isLiveKitConnecting ? 'fa-circle-notch fa-spin' : 'fa-microphone'}"></i>
                  <span>${this.isLiveKitConnecting ? 'Connecting...' : 'Connect Live Microphone'}</span>
                </button>
              `}
            </div>
          </div>
        </div>
      ` : ''}

      <!-- REAL-TIME CONVERSATION TRANSCRIPT & BARGE-IN CONSOLE -->
      <div class="card" style="padding: 24px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 1px solid var(--border-color); padding-bottom: 14px;">
          
          <!-- Barge-in / Speaker State -->
          <div style="display: flex; align-items: center; gap: 10px;">
            <span class="status-indicator" style="background: ${
              speakerState === 'ai_speaking' ? '#8b5cf6' :
              (speakerState === 'user_speaking' ? '#10b981' :
              (speakerState === 'thinking' ? '#f59e0b' : '#94a3b8'))
            };"></span>
            <div>
              <div style="font-weight: 700; font-size: 13.5px; color: var(--text-primary);">
                ${
                  speakerState === 'ai_speaking' ? '● AI Speaking' :
                  (speakerState === 'user_speaking' ? '● Prospect Speaking' :
                  (speakerState === 'thinking' ? '● AI Thinking / Generating...' : '● Idle / Listening'))
                }
              </div>
              <div style="font-size: 11.5px; color: var(--text-muted);">${statusMsg}</div>
            </div>
          </div>

          <!-- Metadata Chips -->
          <div style="display: flex; gap: 10px; align-items: center; font-size: 12px;">
            <span class="badge badge-info font-mono">Lang: ${langVal}</span>
            <span class="badge badge-neutral font-mono">Latency: ${latencyVal}</span>
            <button class="btn btn-secondary btn-sm" id="btnClearTranscripts" title="Clear transcript window">
              <i class="fa-solid fa-trash-can"></i>
            </button>
          </div>
        </div>

        <!-- Transcript Messages Stream -->
        <div id="transcriptStreamContainer" style="min-height: 280px; max-height: 440px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding: 12px; background: var(--bg-surface-secondary); border-radius: 8px; border: 1px solid var(--border-color);">
          ${transcripts.length === 0 ? `
            <div style="margin: auto; text-align: center; color: var(--text-muted); padding: 48px 16px;">
              <i class="fa-solid fa-comments" style="font-size: 32px; margin-bottom: 10px; opacity: 0.4;"></i>
              <div style="font-weight: 600; font-size: 14px;">No utterances recorded yet</div>
              <div style="font-size: 12px; margin-top: 4px;">Transcript messages will stream here in real-time as the call progresses.</div>
            </div>
          ` : transcripts.map(t => {
            const isAgent = t.role === 'agent';
            const isSystem = t.role === 'system';

            if (isSystem) {
              return `
                <div style="align-self: center; font-size: 11.5px; color: var(--text-muted); background: #ffffff; padding: 4px 12px; border-radius: 12px; border: 1px solid var(--border-color);">
                  <i class="fa-solid fa-circle-info text-accent" style="margin-right: 4px;"></i>${t.text}
                </div>
              `;
            }

            return `
              <div style="display: flex; flex-direction: column; align-items: ${isAgent ? 'flex-start' : 'flex-end'};">
                <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px; font-size: 11px; color: var(--text-muted);">
                  <strong>${isAgent ? 'AI Agent' : 'Prospect'}</strong>
                  ${t.language ? `<span class="badge badge-neutral" style="font-size: 9px; padding: 1px 4px;">${t.language}</span>` : ''}
                  ${t.emotion ? `<span class="badge badge-neutral" style="font-size: 9px; padding: 1px 4px;">${t.emotion}</span>` : ''}
                  <span>${t.timestamp || ''}</span>
                </div>
                <div style="max-width: 80%; padding: 10px 14px; border-radius: ${isAgent ? '4px 14px 14px 14px' : '14px 4px 14px 14px'}; font-size: 13.5px; line-height: 1.45; ${
                  isAgent 
                    ? 'background: #f5f3ff; color: #4c1d95; border: 1px solid #ddd6fe;' 
                    : 'background: #ffffff; color: var(--text-primary); border: 1px solid var(--border-color); box-shadow: var(--shadow-sm);'
                }">
                  ${t.text}
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;

    this.attachEvents(container);

    // Auto-scroll transcript container to bottom
    const stream = container.querySelector('#transcriptStreamContainer');
    if (stream) {
      stream.scrollTop = stream.scrollHeight;
    }
  }

  attachEvents(container) {
    // Mode toggles
    const tabTelephony = container.querySelector('#tabModeTelephony');
    if (tabTelephony) {
      tabTelephony.addEventListener('click', () => {
        if (this.isLiveKitConnected) {
          this.disconnectLiveKit(container);
        }
        this.activeMode = 'telephony';
        this.render(container);
      });
    }

    const tabLiveKit = container.querySelector('#tabModeLiveKit');
    if (tabLiveKit) {
      tabLiveKit.addEventListener('click', () => {
        this.activeMode = 'livekit';
        this.render(container);
      });
    }

    // Start New Call / Redial button
    const btnNewCall = container.querySelector('#btnNewCallTelephony');
    if (btnNewCall) {
      btnNewCall.addEventListener('click', () => {
        window.store.clearActiveCall();
        this.stopCallTimer();
        this.render(container);
      });
    }

    // Dismiss active call hero card
    const btnDismiss = container.querySelector('#btnDismissCallHero');
    if (btnDismiss) {
      btnDismiss.addEventListener('click', () => {
        window.store.clearActiveCall();
        this.stopCallTimer();
        this.render(container);
      });
    }

    // Hang up active call
    const btnHangup = container.querySelector('#btnHangupLiveCall');
    if (btnHangup) {
      btnHangup.addEventListener('click', async () => {
        const activeCall = window.store.activeCall;
        const callUuid = activeCall ? (activeCall.call_uuid || activeCall.callSid) : null;
        btnHangup.disabled = true;
        btnHangup.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>Hanging up...</span>';
        if (callUuid && callUuid !== 'pending') {
          try {
            await window.api.hangupCall(callUuid);
          } catch (err) {
            console.warn("Hangup notice:", err);
          }
        }
        window.store.updateActiveCall({ call_status: 'completed' });
        this.stopCallTimer();
        this.render(container);
      });
    }

    // Lead quick-select autofill
    const selLead = container.querySelector('#selHarvestedLead');
    const txtPhone = container.querySelector('#txtManualPhone');
    const txtCustName = container.querySelector('#txtCustomerName');
    const txtCustCtx = container.querySelector('#txtCustomerContext');
    if (selLead) {
      selLead.addEventListener('change', () => {
        const selectedDomain = selLead.value;
        if (!selectedDomain) return;
        const lead = (window.store.allLeads || []).find(l => (l.domain || l.website) === selectedDomain);
        if (lead) {
          if (txtPhone && lead.phones && lead.phones.length) {
            txtPhone.value = lead.phones[0];
          }
          if (txtCustName) {
            txtCustName.value = lead.company_name || lead.domain;
          }
          if (txtCustCtx) {
            txtCustCtx.value = lead.description || (lead.industry ? `${lead.industry} business` : '');
          }
        }
      });
    }

    // Call prompt templates & character count
    const SCRIPT_TEMPLATES = {
      b2b_discovery: "Introduce yourself as Sara from Flowiz and Cybernauts. Personalize the conversation with the prospect's company and industry. Ask how they currently handle lead qualification and customer follow-ups. Inquire about their biggest operational bottlenecks. If they show interest, briefly explain our automated workflows and ask if they are open to a brief follow-up discussion. Do not be pushy.",
      ai_automation: "This call is for introducing our Voice AI Telephony agents to automate outbound customer reach and qualification. Ask the prospect if their sales team currently faces high call volume or manual dialer delays. Explain how our voice agents achieve zero-latency natural conversations in English and Hindi. If interested, ask for the best contact person and timeline for a live demonstration.",
      executive_followup: "Follow up with the prospect regarding our previous discussion on enterprise automation. Inquire if they have reviewed our technical capabilities and if they have any specific questions regarding integration or pricing. If they are ready, offer to schedule a technical alignment call with our engineering leads."
    };

    const selTemplate = container.querySelector('#selCallScriptTemplate');
    const txtPrompt = container.querySelector('#txtCallPrompt');
    const charCount = container.querySelector('#callPromptCharCountLive');
    const btnClearPrompt = container.querySelector('#btnClearPromptLive');

    if (txtPrompt && charCount) {
      txtPrompt.addEventListener('input', () => {
        charCount.textContent = `${txtPrompt.value.length} / 2500`;
      });
    }

    if (selTemplate && txtPrompt) {
      selTemplate.addEventListener('change', () => {
        const tpl = SCRIPT_TEMPLATES[selTemplate.value];
        if (tpl) {
          txtPrompt.value = tpl;
          if (charCount) charCount.textContent = `${txtPrompt.value.length} / 2500`;
        }
      });
    }

    if (btnClearPrompt && txtPrompt) {
      btnClearPrompt.addEventListener('click', () => {
        txtPrompt.value = '';
        if (selTemplate) selTemplate.value = '';
        if (charCount) charCount.textContent = '0 / 2500';
      });
    }

    // Manual dial with call script
    const btnDial = container.querySelector('#btnManualDial');
    if (btnDial && txtPhone) {
      btnDial.addEventListener('click', async () => {
        const phone = txtPhone.value.trim();
        if (!phone) {
          alert('Please enter a phone number in E.164 format (e.g. +917082968702).');
          return;
        }

        const customerName = txtCustName ? txtCustName.value.trim() : '';
        const customerCtx = txtCustCtx ? txtCustCtx.value.trim() : '';
        const callPrompt = txtPrompt ? txtPrompt.value.trim() : '';

        try {
          btnDial.disabled = true;
          btnDial.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>Initiating Call...</span>';

          // Check if dialed phone matches a known lead
          const matchingLead = (window.store.allLeads || []).find(l => 
            Array.isArray(l.phones) && l.phones.some(p => p.replace(/[^\d]/g, '').endsWith(phone.replace(/[^\d]/g, '').slice(-10)))
          );

          const leadId = matchingLead ? (matchingLead.domain || matchingLead.website) : (customerName ? customerName.toLowerCase().replace(/[^a-z0-9]/g, '_') : 'manual_dial');
          const companyName = customerName || (matchingLead ? matchingLead.company_name : 'Manual Telecom Call');
          const sessionId = 'sess_' + Date.now();
          const dispatchId = 'disp_' + Date.now();

          window.store.setActiveCall({
            lead_id: leadId,
            dispatch_id: dispatchId,
            session_id: sessionId,
            call_uuid: 'pending',
            company_name: companyName,
            phone: phone,
            call_prompt: callPrompt || undefined,
            has_call_prompt: Boolean(callPrompt),
            call_prompt_len: callPrompt ? callPrompt.length : 0,
            call_status: 'initiating'
          });

          this.startCallTimer();

          const companyContext = {
            lead_id: leadId,
            company_name: companyName,
            domain: matchingLead ? (matchingLead.domain || matchingLead.website) : leadId,
            industry: matchingLead ? matchingLead.industry : 'B2B Services',
            location: matchingLead ? matchingLead.location : 'India',
            company_summary: customerCtx || (matchingLead ? matchingLead.description : 'Outbound qualification prospect')
          };

          const payload = {
            phoneNumber: phone,
            phone_number: phone,
            company_context: companyContext,
            lead_id: leadId,
            session_id: sessionId,
            dispatch_id: dispatchId,
            call_prompt: callPrompt || undefined
          };

          const res = await window.api.triggerOutboundCall(phone, payload);
          if (res && res.status === 'success') {
            window.store.updateActiveCall({
              call_status: 'in_progress',
              call_uuid: res.callSid || res.call_id
            });
            this.render(container);
          }
        } catch (err) {
          alert('Failed to place outbound call: ' + (err.message || err));
          window.store.clearActiveCall();
          this.stopCallTimer();
          this.render(container);
        } finally {
          if (btnDial) {
            btnDial.disabled = false;
            btnDial.innerHTML = '<i class="fa-solid fa-phone-volume"></i><span>Launch AI Call with Script</span>';
          }
        }
      });
    }

    // Clear transcripts
    const btnClear = container.querySelector('#btnClearTranscripts');
    if (btnClear) {
      btnClear.addEventListener('click', () => {
        window.store.clearTranscripts();
        this.render(container);
      });
    }

    // Back to Lead Dossier
    const btnBackToLead = container.querySelector('#btnBackToLead');
    if (btnBackToLead) {
      btnBackToLead.addEventListener('click', () => {
        const domain = btnBackToLead.getAttribute('data-domain');
        const lead = window.store.allLeads.find(l => l.domain === domain || l.website === domain);
        if (lead && window.app && window.app.leadDetailView) {
          window.app.leadDetailView.show(lead);
        }
      });
    }

    // LiveKit WebRTC Connect & Disconnect handlers
    const btnConnectLiveKit = container.querySelector('#btnConnectLiveKit');
    if (btnConnectLiveKit) {
      btnConnectLiveKit.addEventListener('click', () => {
        this.connectLiveKit(container);
      });
    }

    const btnDisconnectLiveKit = container.querySelector('#btnDisconnectLiveKit');
    if (btnDisconnectLiveKit) {
      btnDisconnectLiveKit.addEventListener('click', () => {
        this.disconnectLiveKit(container);
      });
    }
  }

  async connectLiveKit(container) {
    if (this.isLiveKitConnected || this.isLiveKitConnecting) return;
    this.isLiveKitConnecting = true;
    this.render(container);

    try {
      const res = await window.api.joinLiveKit();
      if (!res || !res.token || !res.roomUrl) {
        throw new Error(res?.detail || 'Could not retrieve LiveKit credentials from server.');
      }

      if (!window.LivekitClient) {
        throw new Error('LiveKit WebRTC client library is not loaded in browser.');
      }

      // Cleanup any previous session/tracks first
      this.cleanupLiveKit();

      const room = new window.LivekitClient.Room({
        adaptiveStream: true,
        dynacast: true,
        audioCaptureDefaults: {
          autoGainControl: true,
          echoCancellation: true,
          noiseSuppression: true,
        }
      });
      this.livekitRoom = room;

      // CRITICAL: When remote bot publishes audio, attach it to DOM and play so user hears the AI speak!
      room.on(window.LivekitClient.RoomEvent.TrackSubscribed, (track, publication, participant) => {
        console.log('[LiveKit] Remote track subscribed:', track.kind, 'from', participant.identity);
        if (track.kind === window.LivekitClient.Track.Kind.Audio) {
          const audioElement = track.attach();
          audioElement.id = 'livekit-bot-audio-' + (track.sid || Date.now());
          audioElement.autoplay = true;
          document.body.appendChild(audioElement);
          audioElement.play().catch(e => {
            console.warn('[LiveKit] Autoplay warning on track:', e);
          });
        }
      });

      room.on(window.LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {
        track.detach().forEach(el => el.remove());
      });

      room.on(window.LivekitClient.RoomEvent.Disconnected, () => {
        console.log('[LiveKit] Room disconnected event received.');
        this.cleanupLiveKit();
        this.render(container);
      });

      // Connect to LiveKit Cloud Room
      await room.connect(res.roomUrl, res.token);

      // Unlock AudioContext for modern browser autoplay security policies
      await room.startAudio().catch(e => console.warn('[LiveKit] startAudio warning:', e));

      // CRITICAL: ONLY enable Microphone (NO CAMERA! Explicitly audio-only)
      await room.localParticipant.setMicrophoneEnabled(true);

      this.isLiveKitConnected = true;
      this.isLiveKitConnecting = false;

      window.store.setVoiceState({
        isCallActive: true,
        callMode: 'livekit',
        speakerState: 'idle',
        statusMessage: 'LiveKit session connected. Microphone active (Camera OFF). Start speaking!'
      });

      window.store.addTranscript('system', 'LiveKit WebRTC audio session connected. Sara AI is listening.');
      this.render(container);

    } catch (err) {
      console.error('[LiveKit ERROR]', err);
      this.cleanupLiveKit();
      this.isLiveKitConnecting = false;
      alert('LiveKit Connection Error: ' + (err.message || err));
      this.render(container);
    }
  }

  cleanupLiveKit() {
    if (this.livekitRoom) {
      try {
        // Explicitly stop all local tracks so browser microphone icon / camera hardware is released immediately!
        if (this.livekitRoom.localParticipant) {
          this.livekitRoom.localParticipant.tracks.forEach(pub => {
            if (pub.track) {
              pub.track.stop();
            }
          });
        }
        this.livekitRoom.disconnect();
      } catch (e) {
        console.warn('[LiveKit] Disconnect notice:', e);
      }
      this.livekitRoom = null;
    }
    // Remove attached audio elements from body
    document.querySelectorAll("[id^='livekit-bot-audio-']").forEach(el => el.remove());
    this.isLiveKitConnected = false;
    this.isLiveKitConnecting = false;
  }

  disconnectLiveKit(container) {
    this.cleanupLiveKit();
    window.store.setVoiceState({
      isCallActive: false,
      speakerState: 'idle',
      statusMessage: 'LiveKit session ended.'
    });
    window.store.addTranscript('system', 'LiveKit voice session disconnected.');
    this.render(container);
  }
}

window.LiveAgentView = LiveAgentView;
