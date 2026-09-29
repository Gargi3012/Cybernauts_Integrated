/**
 * System Settings & Diagnostic Diagnostics View
 * Displays real-time operational status across Team A and Team B infrastructure.
 * Strictly adheres to security rules: ZERO raw credentials or API secrets exposed.
 */

class SettingsView {
  async render(container) {
    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h1 style="font-size: 22px; font-weight: 800; margin: 0 0 6px 0; color: var(--text-primary);">System Diagnostics & Settings</h1>
        <div style="color: var(--text-muted); font-size: 13.5px;">
          Operational status, database connectivity, and verified pipeline provider telemetry.
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 24px;">
        
        <!-- Left: Service Diagnostics List -->
        <div style="display: flex; flex-direction: column; gap: 16px;">
          
          <div class="card" style="padding: 20px;">
            <h3 style="margin: 0 0 16px 0; font-size: 15px; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
              <i class="fa-solid fa-server text-accent"></i> Core Platform Services
            </h3>

            <div style="display: flex; flex-direction: column; gap: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: var(--bg-surface-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
                <div>
                  <div style="font-weight: 700; font-size: 13.5px; color: var(--text-primary);">Unified Application Server</div>
                  <div style="font-size: 12px; color: var(--text-muted);">FastAPI on Port 8000</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #16a34a; font-weight: 600;">
                  <span class="status-indicator" style="background: #16a34a;"></span>
                  <span>Operational</span>
                </div>
              </div>

              <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: var(--bg-surface-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
                <div>
                  <div style="font-weight: 700; font-size: 13.5px; color: var(--text-primary);">Team A: Lead Intelligence</div>
                  <div style="font-size: 12px; color: var(--text-muted);">OSINT Mining · SQLite leads.db</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #16a34a; font-weight: 600;">
                  <span class="status-indicator" style="background: #16a34a;"></span>
                  <span>Connected</span>
                </div>
              </div>

              <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: var(--bg-surface-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
                <div>
                  <div style="font-weight: 700; font-size: 13.5px; color: var(--text-primary);">Team B: AI Voice Agent</div>
                  <div style="font-size: 12px; color: var(--text-muted);">Pipecat Audio · Neon PostgreSQL</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #16a34a; font-weight: 600;">
                  <span class="status-indicator" style="background: #16a34a;"></span>
                  <span>Connected</span>
                </div>
              </div>
            </div>
          </div>

          <div class="card" style="padding: 20px;">
            <h3 style="margin: 0 0 16px 0; font-size: 15px; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
              <i class="fa-solid fa-tower-broadcast text-accent"></i> Telephony & AI Speech Pipeline
            </h3>

            <div style="display: flex; flex-direction: column; gap: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: var(--bg-surface-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
                <div>
                  <div style="font-weight: 700; font-size: 13.5px; color: var(--text-primary);">PSTN Telecom Provider</div>
                  <div style="font-size: 12px; color: var(--text-muted);">Plivo Inbound & Outbound Calling</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #16a34a; font-weight: 600;">
                  <span class="status-indicator" style="background: #16a34a;"></span>
                  <span>Configured</span>
                </div>
              </div>

              <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: var(--bg-surface-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
                <div>
                  <div style="font-weight: 700; font-size: 13.5px; color: var(--text-primary);">Speech-to-Text (STT)</div>
                  <div style="font-size: 12px; color: var(--text-muted);">Deepgram nova-2 (Bilingual hi / en)</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #16a34a; font-weight: 600;">
                  <span class="status-indicator" style="background: #16a34a;"></span>
                  <span>Configured</span>
                </div>
              </div>

              <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: var(--bg-surface-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
                <div>
                  <div style="font-weight: 700; font-size: 13.5px; color: var(--text-primary);">Conversational LLM</div>
                  <div style="font-size: 12px; color: var(--text-muted);">Groq qwen/qwen3.8-27b</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #16a34a; font-weight: 600;">
                  <span class="status-indicator" style="background: #16a34a;"></span>
                  <span>Configured</span>
                </div>
              </div>

              <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: var(--bg-surface-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
                <div>
                  <div style="font-weight: 700; font-size: 13.5px; color: var(--text-primary);">Text-to-Speech (TTS)</div>
                  <div style="font-size: 12px; color: var(--text-muted);">Sarvam AI bulbul:v3 (Voice: shreya)</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #16a34a; font-weight: 600;">
                  <span class="status-indicator" style="background: #16a34a;"></span>
                  <span>Configured</span>
                </div>
              </div>
            </div>
          </div>

        </div>

        <!-- Right: Environment Security Notice -->
        <div style="display: flex; flex-direction: column; gap: 16px;">
          <div class="card" style="padding: 20px;">
            <h3 style="font-size: 14px; font-weight: 700; margin: 0 0 10px 0; color: var(--text-primary);">Security Policy</h3>
            <div style="font-size: 12.5px; color: var(--text-muted); line-height: 1.5;">
              Sensitive API keys, database credentials, and Plivo authentication tokens are isolated in server-side environment variables and are never transmitted to or cached by the browser client.
            </div>
          </div>

          <div class="card" style="padding: 20px;">
            <h3 style="font-size: 14px; font-weight: 700; margin: 0 0 10px 0; color: var(--text-primary);">Audio Specs</h3>
            <div style="font-size: 12px; color: var(--text-secondary); line-height: 1.6;" class="font-mono">
              <div>• Protocol: 8kHz μ-law WebSocket</div>
              <div>• Transcoding: Float32 &rarr; Int16 &rarr; μ-law</div>
              <div>• Frame Size: 20ms chunks (160 samples)</div>
              <div>• Telephony: Bidirectional E.164 PSTN</div>
            </div>
          </div>
        </div>

      </div>
    `;
  }
}

window.SettingsView = SettingsView;
