/**
 * Voice Agent — Call History View
 * Displays past phone call sessions, durations, and LLM-generated summaries
 * Connected directly to Team B Backend Database API (/api/call-history)
 */

class CallHistoryView {
  async render(container) {
    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 20px; font-weight: 700; margin: 0 0 6px 0;">Voice Call History</h2>
        <div style="color: var(--text-muted); font-size: 13.5px;">
          Log of past inbound/outbound phone sessions and AI-generated caller summaries.
        </div>
      </div>

      <div class="card" style="padding: 0; overflow: hidden;" id="callHistoryCard">
        <div style="padding: 48px; text-align: center;" class="text-muted">
          <i class="fa-solid fa-circle-notch fa-spin" style="font-size: 24px; margin-bottom: 12px; color: var(--color-primary);"></i>
          <div>Loading call history from Team B database...</div>
        </div>
      </div>
    `;

    try {
      const data = await window.api.getCallHistory();
      const calls = (data && data.calls) || [];
      const card = container.querySelector('#callHistoryCard');

      if (!card) return;

      if (calls.length === 0) {
        card.innerHTML = `
          <div style="padding: 48px; text-align: center;" class="text-muted">
            <i class="fa-solid fa-phone-slash" style="font-size: 32px; margin-bottom: 12px;"></i>
            <div>No call sessions recorded yet. Start a call via Live Agent!</div>
          </div>
        `;
        return;
      }

      card.innerHTML = `
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
            ${calls.map(c => `
              <tr>
                <td style="font-weight: 600;">${c.phone || 'Unknown Caller'}</td>
                <td><span class="badge badge-info">${c.transport || 'Voice Session'}</span></td>
                <td class="font-mono" style="font-size: 12.5px;">${c.duration || '—'}</td>
                <td><span class="badge ${c.status === 'COMPLETED' || c.status === 'ACTIVE' ? 'badge-success' : 'badge-muted'}">${c.status || 'COMPLETED'}</span></td>
                <td style="color: var(--text-secondary); max-width: 400px; font-size: 13px;">${c.summary || 'No summary recorded.'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    } catch (err) {
      console.error("Failed to load call history:", err);
      const card = container.querySelector('#callHistoryCard');
      if (card) {
        card.innerHTML = `
          <div style="padding: 32px; text-align: center; color: var(--color-danger);">
            <i class="fa-solid fa-triangle-exclamation" style="font-size: 24px; margin-bottom: 8px;"></i>
            <div>Failed to load call history: ${err.message || err}</div>
          </div>
        `;
      }
    }
  }
}

window.CallHistoryView = CallHistoryView;
