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
    this.room = null;
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
            <div style="display: flex; align-items: center; gap: 16px;">
              <div style="text-align: right;">
                <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Duration</div>
                <div class="font-mono" style="font-size: 18px; font-weight: 700; color: var(--text-primary);" id="liveCallDuration">00:00</div>
              </div>
              <span class="badge ${activeCall.call_status === 'completed' ? 'badge-success' : 'badge-warning'}" style="font-size: 12px; padding: 6px 12px;">
                ${activeCall.call_status === 'completed' ? '✓ Call Completed' : '● ' + (activeCall.call_status || 'In Progress')}
              </span>
            </div>
          </div>

          <!-- Traceability IDs Bar -->
          <div style="display: flex; gap: 16px; flex-wrap: wrap; padding: 10px 12px; background: rgba(107, 33, 168, 0.05); border-radius: 6px; font-size: 11.5px; border: 1px solid rgba(107, 33, 168, 0.15);" class="font-mono text-muted">
            <div><strong>Lead:</strong> ${activeCall.lead_id || '—'}</div>
            <div><strong>Dispatch:</strong> ${activeCall.dispatch_id || '—'}</div>
            <div><strong>Session:</strong> ${activeCall.session_id || '—'}</div>
            <div><strong>Call UUID:</strong> ${activeCall.call_uuid || '—'}</div>
          </div>

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

      <!-- DIALER (WHEN IN TELEPHONY MODE & NO ACTIVE LEAD CALL) -->
      ${this.activeMode === 'telephony' && !activeCall ? `
        <div class="card" style="margin-bottom: 20px; padding: 24px;">
          <h3 style="margin: 0 0 14px 0; font-size: 15px; font-weight: 700;">Manual Outbound Telecom Dialer</h3>
          <div style="display: flex; gap: 12px; align-items: center; max-width: 480px;">
            <input 
              type="text" 
              id="txtManualPhone" 
              class="form-input font-mono" 
              placeholder="e.g. +917082968702" 
              value="+917082968702"
              style="font-size: 15px;"
            />
            <button class="btn btn-primary" id="btnManualDial" style="white-space: nowrap;">
              <i class="fa-solid fa-phone"></i>
              <span>Dial via Plivo</span>
            </button>
          </div>
          <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 8px;">
            Or launch qualification with full company context directly from any prospect in <a href="#leads" style="color: var(--color-primary); font-weight: 600;">All Leads</a>.
          </div>
        </div>
      ` : ''}

      <!-- WEBRTC BROWSER VOICE MODE (IF IN LIVEKIT MODE) -->
      ${this.activeMode === 'livekit' ? `
        <div class="card" style="margin-bottom: 20px; padding: 24px;">
          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;">
            <div>
              <h3 style="margin: 0 0 4px 0; font-size: 16px; font-weight: 700;">In-Browser WebRTC Voice Session</h3>
              <div class="text-muted" style="font-size: 13px;">Connect your microphone and speak directly with the AI Agent in real-time.</div>
            </div>
            <div>
              <button class="btn btn-primary" id="btnConnectLiveKit">
                <i class="fa-solid fa-microphone"></i>
                <span>Connect Live Microphone</span>
              </button>
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

    // Manual dial
    const btnDial = container.querySelector('#btnManualDial');
    const txtPhone = container.querySelector('#txtManualPhone');
    if (btnDial && txtPhone) {
      btnDial.addEventListener('click', async () => {
        const phone = txtPhone.value.trim();
        if (!phone) {
          alert('Please enter a phone number in E.164 format (e.g. +917082968702).');
          return;
        }

        try {
          btnDial.disabled = true;
          btnDial.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>Dialing...</span>';

          // Check if dialed phone matches a known lead
          const matchingLead = (window.store.allLeads || []).find(l => 
            Array.isArray(l.phones) && l.phones.some(p => p.replace(/[^\d]/g, '').endsWith(phone.replace(/[^\d]/g, '').slice(-10)))
          );

          const leadId = matchingLead ? (matchingLead.domain || matchingLead.website) : 'manual_dial';
          const companyName = matchingLead ? matchingLead.company_name : 'Manual Telecom Call';

          window.store.setActiveCall({
            lead_id: leadId,
            dispatch_id: 'manual_' + Date.now(),
            session_id: 'sess_' + Date.now(),
            call_uuid: 'pending',
            company_name: companyName,
            phone: phone,
            call_status: 'initiating'
          });

          this.startCallTimer();

          const extraPayload = matchingLead ? {
            lead_id: leadId,
            company_context: {
              lead_id: leadId,
              company_name: matchingLead.company_name,
              domain: matchingLead.domain || matchingLead.website,
              industry: matchingLead.industry,
              location: matchingLead.location,
              company_summary: matchingLead.description
            }
          } : {};

          const res = await window.api.triggerOutboundCall(phone, extraPayload);
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
          btnDial.disabled = false;
          btnDial.innerHTML = '<i class="fa-solid fa-phone"></i><span>Dial via Plivo</span>';
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

    // LiveKit WebRTC Join
    const btnConnectLiveKit = container.querySelector('#btnConnectLiveKit');
    if (btnConnectLiveKit) {
      btnConnectLiveKit.addEventListener('click', async () => {
        try {
          btnConnectLiveKit.disabled = true;
          btnConnectLiveKit.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>Connecting...</span>';
          
          const res = await window.api.joinLiveKit();
          if (res && res.token && res.roomUrl && window.LivekitClient) {
            const room = new window.LivekitClient.Room();
            await room.connect(res.roomUrl, res.token);
            await room.localParticipant.enableCameraAndMicrophone();
            alert('Connected to LiveKit in-browser audio room!');
          } else {
            alert('LiveKit token generated. Active on server.');
          }
        } catch (err) {
          alert('LiveKit connection: ' + (err.message || err));
        } finally {
          btnConnectLiveKit.disabled = false;
          btnConnectLiveKit.innerHTML = '<i class="fa-solid fa-microphone"></i><span>Connect Live Microphone</span>';
        }
      });
    }
  }
}

window.LiveAgentView = LiveAgentView;
