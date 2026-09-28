/**
 * Voice Agent — Call History View
 * Connects directly to Neon PostgreSQL via /api/call-history
 * Features:
 * - Search by phone or summary keyword
 * - Status filtering (Completed, Active, Closed)
 * - Deep Call Detail Modal with full AI summary & Technical Traceability
 */

class CallHistoryView {
  constructor() {
    this.searchQuery = '';
    this.statusFilter = '';
    this.calls = [];
  }

  async render(container) {
    container.innerHTML = `
      <div style="margin-bottom: 20px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 12px;">
        <div>
          <h1 style="font-size: 22px; font-weight: 800; margin: 0 0 6px 0; color: var(--text-primary);">Call History & Transcripts</h1>
          <div style="color: var(--text-muted); font-size: 13.5px;">
            Auditable archive of all inbound and outbound telecom qualification sessions and AI-synthesized conversation summaries.
          </div>
        </div>
      </div>

      <!-- Filters Bar -->
      <div class="card" style="margin-bottom: 20px; padding: 14px 20px;">
        <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
          <div style="position: relative; flex: 1; min-width: 240px;">
            <i class="fa-solid fa-magnifying-glass" style="position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: var(--text-muted); font-size: 12px;"></i>
            <input 
              type="text" 
              id="callHistorySearch" 
              class="form-input" 
              placeholder="Search phone numbers or summary content..." 
              value="${this.searchQuery}"
              style="padding-left: 32px;"
            />
          </div>

          <select id="callHistoryStatusFilter" class="form-input" style="max-width: 180px;">
            <option value="">All Statuses</option>
            <option value="COMPLETED" ${this.statusFilter === 'COMPLETED' ? 'selected' : ''}>Completed</option>
            <option value="CLOSED" ${this.statusFilter === 'CLOSED' ? 'selected' : ''}>Closed</option>
            <option value="ACTIVE" ${this.statusFilter === 'ACTIVE' ? 'selected' : ''}>Active</option>
          </select>
        </div>
      </div>

      <!-- History Table Container -->
      <div class="card" style="padding: 0; overflow: hidden;" id="callHistoryTableCard">
        <div style="padding: 48px; text-align: center;" class="text-muted">
          <i class="fa-solid fa-circle-notch fa-spin text-accent" style="font-size: 24px; margin-bottom: 12px;"></i>
          <div>Loading verified call history from PostgreSQL database...</div>
        </div>
      </div>

      <!-- Call Detail Modal Container -->
      <div id="callDetailModalContainer"></div>
    `;

    try {
      const data = await window.api.getCallHistory();
      this.calls = (data && Array.isArray(data.calls)) ? data.calls : [];
      this.renderTable(container);
    } catch (err) {
      const card = container.querySelector('#callHistoryTableCard');
      if (card) {
        card.innerHTML = `
          <div style="padding: 32px; text-align: center; color: var(--color-danger);">
            <i class="fa-solid fa-triangle-exclamation" style="font-size: 28px; margin-bottom: 8px;"></i>
            <div>Failed to load call history: ${err.message || err}</div>
          </div>
        `;
      }
    }

    this.attachEvents(container);
  }

  getFilteredCalls() {
    let list = [...this.calls];

    if (this.searchQuery && this.searchQuery.trim()) {
      const q = this.searchQuery.toLowerCase().trim();
      list = list.filter(c => 
        (c.phone && c.phone.toLowerCase().includes(q)) ||
        (c.summary && c.summary.toLowerCase().includes(q)) ||
        (c.transport && c.transport.toLowerCase().includes(q))
      );
    }

    if (this.statusFilter) {
      list = list.filter(c => (c.status || '').toUpperCase() === this.statusFilter.toUpperCase());
    }

    return list;
  }

  renderTable(container) {
    const card = container.querySelector('#callHistoryTableCard');
    if (!card) return;

    const filtered = this.getFilteredCalls();

    if (filtered.length === 0) {
      card.innerHTML = `
        <div style="padding: 48px; text-align: center;" class="text-muted">
          <i class="fa-solid fa-phone-slash" style="font-size: 32px; margin-bottom: 12px; opacity: 0.5;"></i>
          <div style="font-weight: 600; font-size: 14px;">No call sessions found</div>
          <div style="font-size: 12.5px; margin-top: 4px;">Start an outbound qualification call from any prospect in All Leads.</div>
        </div>
      `;
      return;
    }

    card.innerHTML = `
      <div style="overflow-x: auto;">
        <table class="data-table" style="width: 100%;">
          <thead>
            <tr>
              <th style="width: 22%;">Contact Phone</th>
              <th style="width: 18%;">Transport</th>
              <th style="width: 12%;">Duration</th>
              <th style="width: 12%;">Status</th>
              <th style="width: 26%;">AI Summary</th>
              <th style="width: 10%; text-align: right;">Action</th>
            </tr>
          </thead>
          <tbody>
            ${filtered.map((c, idx) => `
              <tr class="call-history-row" data-idx="${idx}">
                <td style="font-weight: 700; color: var(--text-primary);">
                  <div class="font-mono">${c.phone || 'Unknown'}</div>
                  <div class="text-muted" style="font-size: 11px; font-weight: normal; margin-top: 2px;">
                    ${c.startedAt ? new Date(c.startedAt).toLocaleString() : 'Recent'}
                  </div>
                </td>
                <td>
                  <span class="badge ${c.transport.includes('Plivo') ? 'badge-info' : 'badge-neutral'}">
                    ${c.transport || 'Plivo Telephony'}
                  </span>
                </td>
                <td class="font-mono" style="font-size: 12px;">${c.duration || '—'}</td>
                <td>
                  <span class="badge ${c.status === 'COMPLETED' || c.status === 'CLOSED' ? 'badge-success' : (c.status === 'ACTIVE' ? 'badge-warning' : 'badge-neutral')}">
                    ${c.status || 'COMPLETED'}
                  </span>
                </td>
                <td style="color: var(--text-secondary); font-size: 12.5px; line-height: 1.4;">
                  ${(c.summary || 'No summary recorded.').slice(0, 110)}${(c.summary && c.summary.length > 110) ? '...' : ''}
                </td>
                <td style="text-align: right;">
                  <button class="btn btn-secondary btn-sm btn-inspect-call" data-idx="${idx}">
                    Inspect
                  </button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;

    card.querySelectorAll('.btn-inspect-call').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.getAttribute('data-idx'), 10);
        const callItem = filtered[idx];
        if (callItem) this.showCallDetail(container, callItem);
      });
    });
  }

  showCallDetail(container, callItem) {
    const modalContainer = container.querySelector('#callDetailModalContainer');
    if (!modalContainer) return;

    modalContainer.innerHTML = `
      <div class="modal-backdrop" id="callDetailBackdrop" style="position: fixed; inset: 0; background: rgba(15, 23, 42, 0.5); backdrop-filter: blur(4px); z-index: 100; display: flex; align-items: center; justify-content: center; padding: 20px;">
        <div class="card" style="width: 580px; max-width: 100%; max-height: 85vh; overflow-y: auto; padding: 28px; box-shadow: var(--shadow-xl); background: #ffffff;">
          
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; padding-bottom: 14px; border-bottom: 1px solid var(--border-color);">
            <div>
              <span class="badge badge-info" style="margin-bottom: 6px;">${callItem.transport || 'Telecom'}</span>
              <h3 style="margin: 0; font-size: 18px; font-weight: 800; color: var(--text-primary);">Call Session Details</h3>
              <div class="font-mono text-muted" style="font-size: 12.5px;">${callItem.phone || 'Unknown'}</div>
            </div>
            <button id="btnCloseCallDetail" class="btn btn-secondary btn-sm" style="padding: 4px 10px;">✕</button>
          </div>

          <div style="display: flex; flex-direction: column; gap: 16px;">
            <!-- Call Overview Grid -->
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; background: var(--bg-surface-secondary); padding: 14px; border-radius: 8px;">
              <div>
                <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Status</div>
                <div style="font-weight: 700; font-size: 13.5px; margin-top: 2px;">${callItem.status || 'COMPLETED'}</div>
              </div>
              <div>
                <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Duration</div>
                <div class="font-mono" style="font-weight: 700; font-size: 13.5px; margin-top: 2px;">${callItem.duration || '—'}</div>
              </div>
              <div>
                <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Timestamp</div>
                <div style="font-size: 11.5px; margin-top: 2px; color: var(--text-muted);">
                  ${callItem.startedAt ? new Date(callItem.startedAt).toLocaleTimeString() : 'Recent'}
                </div>
              </div>
            </div>

            <!-- Full AI Conversation Summary -->
            <div class="card" style="padding: 16px; margin: 0;">
              <div style="font-weight: 700; font-size: 12.5px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 8px;">
                <i class="fa-solid fa-robot text-accent"></i> AI Conversation Summary
              </div>
              <div style="font-size: 13px; color: var(--text-secondary); line-height: 1.5; background: #ffffff; padding: 12px; border-radius: 6px; border: 1px solid var(--border-color);">
                ${callItem.summary || 'No conversation summary recorded for this session.'}
              </div>
            </div>

            <!-- Technical Traceability Details -->
            <div class="card" style="padding: 16px; margin: 0; background: var(--bg-surface-secondary);">
              <div style="font-weight: 700; font-size: 11px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 8px;">
                Technical Identifiers
              </div>
              <div style="display: flex; flex-direction: column; gap: 6px; font-size: 11px;" class="font-mono text-muted">
                <div><strong>Session ID:</strong> <span>${callItem.sessionId || '—'}</span></div>
                <div><strong>Database Record ID:</strong> <span>${callItem.id || '—'}</span></div>
                <div><strong>Carrier Network:</strong> <span>Plivo Voice / PSTN</span></div>
              </div>
            </div>
          </div>

        </div>
      </div>
    `;

    const btnClose = modalContainer.querySelector('#btnCloseCallDetail');
    if (btnClose) {
      btnClose.addEventListener('click', () => {
        modalContainer.innerHTML = '';
      });
    }

    const backdrop = modalContainer.querySelector('#callDetailBackdrop');
    if (backdrop) {
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) modalContainer.innerHTML = '';
      });
    }
  }

  attachEvents(container) {
    const searchInput = container.querySelector('#callHistorySearch');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        this.searchQuery = e.target.value;
        this.renderTable(container);
      });
    }

    const statusFilter = container.querySelector('#callHistoryStatusFilter');
    if (statusFilter) {
      statusFilter.addEventListener('change', (e) => {
        this.statusFilter = e.target.value;
        this.renderTable(container);
      });
    }
  }
}

window.CallHistoryView = CallHistoryView;
