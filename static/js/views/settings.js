/**
 * System Settings View
 */

class SettingsView {
  render(container) {
    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 20px; font-weight: 700; margin: 0 0 6px 0;">Platform Settings</h2>
        <div style="color: var(--text-muted); font-size: 13.5px;">
          Configuration parameters for Flowiz search providers, AI models, and telephony integrations.
        </div>
      </div>

      <div class="card" style="padding: 24px; max-width: 680px;">
        <h3 style="margin: 0 0 16px 0; font-size: 15px; font-weight: 600;">System Configuration</h3>
        
        <div style="display: flex; flex-direction: column; gap: 16px;">
          <div>
            <label style="display: block; font-weight: 600; font-size: 13px; margin-bottom: 6px; color: var(--text-secondary);">Server Endpoint</label>
            <input type="text" class="form-input" value="http://127.0.0.1:8000" disabled />
          </div>

          <div>
            <label style="display: block; font-weight: 600; font-size: 13px; margin-bottom: 6px; color: var(--text-secondary);">Active Transport Mode</label>
            <input type="text" class="form-input" value="LiveKit WebRTC + Twilio Telephony" disabled />
          </div>

          <div>
            <label style="display: block; font-weight: 600; font-size: 13px; margin-bottom: 6px; color: var(--text-secondary);">Database Backends</label>
            <input type="text" class="form-input" value="Team A: SQLite (leads.db) | Team B: PostgreSQL (Neon DB)" disabled />
          </div>
        </div>
      </div>
    `;
  }
}

window.SettingsView = SettingsView;
