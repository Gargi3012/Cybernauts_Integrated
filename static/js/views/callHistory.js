/**
 * Voice Agent — Call History View
 * Displays past phone call sessions, durations, and LLM-generated summaries
 */

class CallHistoryView {
  render(container) {
    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 20px; font-weight: 700; margin: 0 0 6px 0;">Voice Call History</h2>
        <div style="color: var(--text-muted); font-size: 13.5px;">
          Log of past inbound/outbound phone sessions and AI-generated caller summaries.
        </div>
      </div>

      <div class="card" style="padding: 0; overflow: hidden;">
        <table class="data-table">
          <thead>
            <tr>
              <th>CALLER / PHONE</th>
              <th>TRANSPORT</th>
              <th>DURATION</th>
              <th>STATUS</th>
              <th>AI SUMMARY</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style="font-weight: 600;">+1 (737) 221-2163</td>
              <td><span class="badge badge-info">Twilio Telephony</span></td>
              <td class="font-mono" style="font-size: 12.5px;">1m 42s</td>
              <td><span class="badge badge-success">COMPLETED</span></td>
              <td style="color: var(--text-secondary);">Caller inquired about AI capabilities and requested an executive follow-up call.</td>
            </tr>
            <tr>
              <td style="font-weight: 600;">+91 98765 43210</td>
              <td><span class="badge badge-info">LiveKit WebRTC</span></td>
              <td class="font-mono" style="font-size: 12.5px;">3m 15s</td>
              <td><span class="badge badge-success">COMPLETED</span></td>
              <td style="color: var(--text-secondary);">Tested Sarvam Shreya voice pipeline in Hinglish. Captured name and project details.</td>
            </tr>
          </tbody>
        </table>
      </div>
    `;
  }
}

window.CallHistoryView = CallHistoryView;
