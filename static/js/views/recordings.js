/**
 * Call Recordings Dashboard View
 * Browse, listen to, filter, and manage audio recordings from both
 * Telephony (Plivo PSTN) and LiveKit (WebRTC In-Browser) calls.
 */

class RecordingsView {
  constructor() {
    this.recordings = [];
    this.isLoading = false;
    this.filterChannel = 'all';
    this.searchQuery = '';
  }

  async loadRecordings() {
    this.isLoading = true;
    try {
      const res = await window.api.getRecordings({
        channel: this.filterChannel !== 'all' ? this.filterChannel : '',
        search: this.searchQuery || ''
      });
      if (res && res.recordings) {
        this.recordings = res.recordings;
      }
    } catch (err) {
      console.error('[RecordingsView] Error loading recordings:', err);
    } finally {
      this.isLoading = false;
    }
  }

  formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '00:00';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch (_) {
      return dateStr;
    }
  }

  formatFileSize(kb) {
    if (!kb || kb <= 0) return '—';
    if (kb >= 1024) return (kb / 1024).toFixed(1) + ' MB';
    return kb + ' KB';
  }

  async render(container) {
    await this.loadRecordings();

    const totalCount = this.recordings.length;
    const telephonyCount = this.recordings.filter(r => r.channel === 'telephony').length;
    const livekitCount = this.recordings.filter(r => r.channel === 'livekit').length;
    const totalSecs = this.recordings.reduce((sum, r) => sum + (r.duration_seconds || 0), 0);
    const totalMins = Math.round(totalSecs / 60);

    // Update sidebar badge if element exists
    const badge = document.getElementById('sidebarRecordingCount');
    if (badge) badge.textContent = totalCount;

    container.innerHTML = `
      <div style="margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 14px;">
        <div>
          <h1 style="font-size: 22px; font-weight: 800; margin: 0 0 6px 0; color: var(--text-primary); display: flex; align-items: center; gap: 10px;">
            <i class="fa-solid fa-microphone-lines" style="color: #6b21a8;"></i>
            <span>Call Recordings Dashboard</span>
          </h1>
          <div style="color: var(--text-muted); font-size: 13.5px;">
            Manage, play, and export high-fidelity audio recordings captured across Plivo PSTN calls and LiveKit voice sessions.
          </div>
        </div>
        <div style="display: flex; gap: 10px; align-items: center;">
          <button class="btn btn-secondary btn-sm" id="btnRefreshRecordings" style="padding: 7px 14px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 6px;">
            <i class="fa-solid fa-rotate-right ${this.isLoading ? 'fa-spin' : ''}"></i>
            <span>Refresh</span>
          </button>
        </div>
      </div>

      <!-- KPI Stats Bar -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 24px;">
        <div class="card" style="padding: 16px; border: 1px solid var(--border-color); display: flex; align-items: center; gap: 14px;">
          <div style="width: 42px; height: 42px; border-radius: 8px; background: #f3e8ff; color: #7e22ce; display: flex; align-items: center; justify-content: center; font-size: 18px;">
            <i class="fa-solid fa-record-vinyl"></i>
          </div>
          <div>
            <div style="font-size: 11.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Total Recordings</div>
            <div style="font-size: 20px; font-weight: 800; color: var(--text-primary);">${totalCount}</div>
          </div>
        </div>

        <div class="card" style="padding: 16px; border: 1px solid var(--border-color); display: flex; align-items: center; gap: 14px;">
          <div style="width: 42px; height: 42px; border-radius: 8px; background: #ede9fe; color: #6b21a8; display: flex; align-items: center; justify-content: center; font-size: 18px;">
            <i class="fa-solid fa-phone"></i>
          </div>
          <div>
            <div style="font-size: 11.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Telephony (Plivo)</div>
            <div style="font-size: 20px; font-weight: 800; color: var(--text-primary);">${telephonyCount}</div>
          </div>
        </div>

        <div class="card" style="padding: 16px; border: 1px solid var(--border-color); display: flex; align-items: center; gap: 14px;">
          <div style="width: 42px; height: 42px; border-radius: 8px; background: #ecfdf5; color: #059669; display: flex; align-items: center; justify-content: center; font-size: 18px;">
            <i class="fa-solid fa-headset"></i>
          </div>
          <div>
            <div style="font-size: 11.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">LiveKit WebRTC</div>
            <div style="font-size: 20px; font-weight: 800; color: var(--text-primary);">${livekitCount}</div>
          </div>
        </div>

        <div class="card" style="padding: 16px; border: 1px solid var(--border-color); display: flex; align-items: center; gap: 14px;">
          <div style="width: 42px; height: 42px; border-radius: 8px; background: #fef3c7; color: #d97706; display: flex; align-items: center; justify-content: center; font-size: 18px;">
            <i class="fa-solid fa-clock"></i>
          </div>
          <div>
            <div style="font-size: 11.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Total Time</div>
            <div style="font-size: 20px; font-weight: 800; color: var(--text-primary);">${totalMins} <span style="font-size: 13px; font-weight: 500;">mins</span></div>
          </div>
        </div>
      </div>

      <!-- Filters & Search Toolbar -->
      <div class="card" style="padding: 16px 20px; margin-bottom: 20px; border: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px;">
        <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
          <div class="segmented-control" style="font-size: 12px;">
            <button class="segmented-tab ${this.filterChannel === 'all' ? 'active' : ''}" data-filter="all">All (${totalCount})</button>
            <button class="segmented-tab ${this.filterChannel === 'telephony' ? 'active' : ''}" data-filter="telephony">
              <i class="fa-solid fa-phone" style="margin-right: 4px;"></i> Telephony
            </button>
            <button class="segmented-tab ${this.filterChannel === 'livekit' ? 'active' : ''}" data-filter="livekit">
              <i class="fa-solid fa-headset" style="margin-right: 4px;"></i> LiveKit
            </button>
          </div>
        </div>

        <div style="display: flex; gap: 10px; align-items: center; flex: 1; max-width: 380px;">
          <div style="position: relative; width: 100%;">
            <i class="fa-solid fa-magnifying-glass" style="position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: var(--text-muted); font-size: 12px;"></i>
            <input 
              type="text" 
              id="txtSearchRecordings" 
              class="form-input" 
              placeholder="Filter by name, phone, or session..." 
              value="${this.searchQuery}"
              style="padding-left: 32px; font-size: 12.5px; width: 100%;"
            />
          </div>
        </div>
      </div>

      <!-- Recordings Table Card -->
      <div class="card" style="padding: 0; overflow: hidden; border: 1px solid var(--border-color);">
        ${this.recordings.length === 0 ? `
          <div style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
            <div style="width: 56px; height: 56px; border-radius: 50%; background: #f3e8ff; color: #7e22ce; display: flex; align-items: center; justify-content: center; font-size: 24px; margin: 0 auto 16px auto;">
              <i class="fa-solid fa-microphone-slash"></i>
            </div>
            <h3 style="margin: 0 0 6px 0; font-size: 16px; font-weight: 700; color: var(--text-primary);">No Call Recordings Found</h3>
            <p style="font-size: 13px; margin: 0; max-width: 440px; margin: 0 auto;">
              ${this.searchQuery || this.filterChannel !== 'all' 
                ? 'No recordings match your current filters. Try resetting the search query.' 
                : 'Turn on the "Record Call" switch in the Live Agent console before placing a Telephony or LiveKit call to archive recordings here.'}
            </p>
          </div>
        ` : `
          <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;">
              <thead>
                <tr style="background: var(--bg-surface-secondary); border-bottom: 1px solid var(--border-color); color: var(--text-muted); font-size: 11.5px; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px;">
                  <th style="padding: 12px 18px;">Prospect / Lead</th>
                  <th style="padding: 12px 14px;">Channel</th>
                  <th style="padding: 12px 14px;">Duration</th>
                  <th style="padding: 12px 14px; min-width: 250px;">In-Line Audio Player</th>
                  <th style="padding: 12px 14px;">Recorded Date</th>
                  <th style="padding: 12px 18px; text-align: right;">Actions</th>
                </tr>
              </thead>
              <tbody>
                ${this.recordings.map(rec => `
                  <tr style="border-bottom: 1px solid var(--border-color); transition: background 0.15s ease;" class="hover-row">
                    <!-- Prospect Details -->
                    <td style="padding: 14px 18px;">
                      <div style="display: flex; align-items: center; gap: 10px;">
                        <div style="width: 34px; height: 34px; border-radius: 8px; background: ${rec.channel === 'telephony' ? '#ede9fe' : '#ecfdf5'}; color: ${rec.channel === 'telephony' ? '#6b21a8' : '#059669'}; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px;">
                          ${(rec.lead_name || 'P')[0].toUpperCase()}
                        </div>
                        <div>
                          <div style="font-weight: 700; color: var(--text-primary); font-size: 13.5px;">
                            ${rec.lead_name || 'Prospect'}
                          </div>
                          <div class="font-mono text-muted" style="font-size: 11.5px;">
                            ${rec.phone_number || rec.session_id || '—'}
                          </div>
                        </div>
                      </div>
                    </td>

                    <!-- Channel Tag -->
                    <td style="padding: 14px 14px;">
                      ${rec.channel === 'telephony' ? `
                        <span class="badge" style="background: #faf5ff; color: #6b21a8; border: 1px solid #d8b4fe; font-size: 11px; padding: 4px 8px; display: inline-flex; align-items: center; gap: 4px;">
                          <i class="fa-solid fa-phone"></i> Plivo PSTN
                        </span>
                      ` : `
                        <span class="badge" style="background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; font-size: 11px; padding: 4px 8px; display: inline-flex; align-items: center; gap: 4px;">
                          <i class="fa-solid fa-headset"></i> LiveKit WebRTC
                        </span>
                      `}
                    </td>

                    <!-- Duration & Size -->
                    <td style="padding: 14px 14px;">
                      <div class="font-mono" style="font-weight: 700; color: var(--text-primary);">
                        <i class="fa-regular fa-clock" style="color: var(--text-muted); margin-right: 4px;"></i>
                        ${this.formatDuration(rec.duration_seconds)}
                      </div>
                      ${rec.file_size_kb ? `
                        <div class="text-muted font-mono" style="font-size: 11px;">${this.formatFileSize(rec.file_size_kb)}</div>
                      ` : ''}
                    </td>

                    <!-- Audio Player Widget -->
                    <td style="padding: 14px 14px;">
                      <div style="display: flex; align-items: center; gap: 8px;">
                        <audio 
                          controls 
                          preload="none" 
                          src="${rec.file_path}" 
                          style="height: 36px; max-width: 260px; outline: none; border-radius: 20px; filter: drop-shadow(0 1px 1px rgba(0,0,0,0.05));"
                        ></audio>
                      </div>
                    </td>

                    <!-- Recorded Date -->
                    <td style="padding: 14px 14px;">
                      <div style="font-size: 12.5px; color: var(--text-primary);">${this.formatDate(rec.created_at)}</div>
                    </td>

                    <!-- Actions -->
                    <td style="padding: 14px 18px; text-align: right;">
                      <div style="display: flex; justify-content: flex-end; gap: 6px; align-items: center;">
                        <a 
                          href="${rec.file_path}" 
                          target="_blank" 
                          download="recording_${rec.session_id || rec.id}" 
                          class="btn btn-secondary btn-sm" 
                          style="padding: 6px 10px; font-size: 12px; display: inline-flex; align-items: center; gap: 4px;" 
                          title="Download audio file"
                        >
                          <i class="fa-solid fa-download"></i>
                        </a>
                        <button 
                          class="btn btn-secondary btn-sm btn-delete-recording" 
                          data-id="${rec.id}" 
                          data-title="${rec.lead_name || rec.session_id}" 
                          style="padding: 6px 10px; font-size: 12px; color: #dc2626;" 
                          title="Delete recording permanently"
                        >
                          <i class="fa-solid fa-trash-can"></i>
                        </button>
                      </div>
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `}
      </div>
    `;

    this.attachEvents(container);
  }

  attachEvents(container) {
    // Refresh button
    const btnRefresh = container.querySelector('#btnRefreshRecordings');
    if (btnRefresh) {
      btnRefresh.addEventListener('click', () => this.render(container));
    }

    // Channel filter tabs
    container.querySelectorAll('.segmented-tab[data-filter]').forEach(tab => {
      tab.addEventListener('click', () => {
        this.filterChannel = tab.getAttribute('data-filter');
        this.render(container);
      });
    });

    // Search filter
    const txtSearch = container.querySelector('#txtSearchRecordings');
    if (txtSearch) {
      let debounceTimer = null;
      txtSearch.addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          this.searchQuery = e.target.value.trim();
          this.render(container);
        }, 300);
      });
    }

    // Delete recording button
    container.querySelectorAll('.btn-delete-recording').forEach(btn => {
      btn.addEventListener('click', async () => {
        const recId = btn.getAttribute('data-id');
        const title = btn.getAttribute('data-title');
        if (!confirm(`Are you sure you want to delete the recording for "${title}"?`)) return;

        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';

        try {
          await window.api.deleteRecording(recId);
          await this.render(container);
        } catch (err) {
          alert('Failed to delete recording: ' + (err.message || err));
          btn.disabled = false;
          btn.innerHTML = '<i class="fa-solid fa-trash-can"></i>';
        }
      });
    });
  }
}

window.RecordingsView = RecordingsView;
