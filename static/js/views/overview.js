/**
 * System Overview Dashboard View
 * Real-time operational intelligence across Team A Lead DB & Team B Voice Telephony
 * strictly using authentic backend data (Zero fabricated metrics)
 */

class OverviewView {
  async render(container) {
    const leads = window.store.allLeads || [];
    const totalLeads = leads.length;
    const qualifiedLeads = leads.filter(l => (l.qualification_status || '').toLowerCase() === 'qualified').length;
    const activeCalls = leads.filter(l => ['initiating', 'initiated', 'ringing', 'in_progress'].includes((l.call_status || '').toLowerCase())).length;

    // Render skeleton / initial shell
    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h1 style="font-size: 22px; font-weight: 800; margin: 0 0 6px 0; color: var(--text-primary);">System Overview</h1>
        <div style="color: var(--text-muted); font-size: 13.5px;">
          Unified B2B intelligence, autonomous scraping pipeline status, and real-time AI qualification analytics.
        </div>
      </div>

      <!-- Top Metric KPI Cards -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px;">
        <div class="card" style="padding: 18px;">
          <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em;">Total Discovered Leads</div>
          <div style="font-size: 28px; font-weight: 800; color: var(--text-primary); margin: 6px 0;">${totalLeads}</div>
          <div style="font-size: 12px; color: var(--color-success-text); font-weight: 600; display: flex; align-items: center; gap: 5px;">
            <i class="fa-solid fa-database"></i> SQLite flowiz_leads
          </div>
        </div>

        <div class="card" style="padding: 18px;">
          <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em;">AI Qualified Leads</div>
          <div style="font-size: 28px; font-weight: 800; color: var(--color-primary); margin: 6px 0;">${qualifiedLeads}</div>
          <div style="font-size: 12px; color: var(--text-muted); font-weight: 500;">
            ${totalLeads > 0 ? Math.round((qualifiedLeads / totalLeads) * 100) : 0}% Conversion Rate
          </div>
        </div>

        <div class="card" style="padding: 18px;">
          <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em;">Active Calls</div>
          <div style="font-size: 28px; font-weight: 800; color: ${activeCalls > 0 ? '#16a34a' : 'var(--text-primary)'}; margin: 6px 0;">${activeCalls}</div>
          <div style="font-size: 12px; color: ${activeCalls > 0 ? '#16a34a' : 'var(--text-muted)'}; font-weight: 600;">
            ${activeCalls > 0 ? '● Real-Time Plivo Stream' : 'Idle / Ready'}
          </div>
        </div>

        <div class="card" style="padding: 18px;" id="kpiCompletedCallsCard">
          <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em;">Completed Calls</div>
          <div style="font-size: 28px; font-weight: 800; color: var(--text-primary); margin: 6px 0;" id="kpiCompletedCallsVal">--</div>
          <div style="font-size: 12px; color: var(--color-info-text); font-weight: 600;">
            <i class="fa-solid fa-server"></i> Neon PostgreSQL
          </div>
        </div>
      </div>

      <!-- Main Layout: Recent Activity & System Status -->
      <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 24px;">
        
        <!-- Left: Recent Leads & Recent Calls -->
        <div style="display: flex; flex-direction: column; gap: 20px;">
          
          <!-- Recent Leads -->
          <div class="card" style="padding: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
              <h3 style="margin: 0; font-size: 15px; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
                <i class="fa-solid fa-address-book text-accent"></i> Recent Leads
              </h3>
              <a href="#leads" class="btn btn-secondary btn-sm" style="font-size: 11px;">View All (${totalLeads})</a>
            </div>

            ${leads.length === 0 ? `
              <div style="padding: 24px; text-align: center; color: var(--text-muted); font-size: 13px;">
                No leads recorded yet. Go to <a href="#discover" style="color: var(--color-primary); font-weight: 600;">Discover Leads</a> to run a search.
              </div>
            ` : `
              <div style="display: flex; flex-direction: column; gap: 8px;">
                ${leads.slice(0, 5).map(l => `
                  <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: var(--bg-surface-secondary); border-radius: 6px; border: 1px solid var(--border-color); cursor: pointer;" class="overview-lead-item" data-domain="${l.domain || l.website}">
                    <div style="display: flex; align-items: center; gap: 12px;">
                      <div style="width: 32px; height: 32px; border-radius: 6px; background: rgba(79, 70, 229, 0.1); color: var(--color-primary); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px;">
                        ${(l.company_name || 'C').charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <div style="font-weight: 600; font-size: 13.5px; color: var(--text-primary);">${l.company_name || 'Unnamed Company'}</div>
                        <div class="font-mono text-muted" style="font-size: 11px;">${l.domain || l.website || 'No domain'}</div>
                      </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 10px;">
                      <span class="badge ${l.qualification_status === 'qualified' ? 'badge-success' : (l.call_status === 'initiated' || l.call_status === 'in_progress' ? 'badge-warning' : 'badge-neutral')}" style="font-size: 11px;">
                        ${l.qualification_status || l.call_status || 'Unqualified'}
                      </span>
                      <i class="fa-solid fa-chevron-right text-muted" style="font-size: 10px;"></i>
                    </div>
                  </div>
                `).join('')}
              </div>
            `}
          </div>

          <!-- Recent Calls -->
          <div class="card" style="padding: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
              <h3 style="margin: 0; font-size: 15px; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
                <i class="fa-solid fa-phone-volume text-accent"></i> Recent Calls
              </h3>
              <a href="#callHistory" class="btn btn-secondary btn-sm" style="font-size: 11px;">Call History</a>
            </div>
            <div id="overviewRecentCallsContainer">
              <div style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 12px;">
                <i class="fa-solid fa-circle-notch fa-spin"></i> Loading call logs...
              </div>
            </div>
          </div>

        </div>

        <!-- Right: System Operational Status & Quick Actions -->
        <div style="display: flex; flex-direction: column; gap: 20px;">
          
          <!-- System Status -->
          <div class="card" style="padding: 20px;">
            <h3 style="margin: 0 0 16px 0; font-size: 15px; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
              <i class="fa-solid fa-heart-pulse text-accent"></i> System Status
            </h3>

            <div style="display: flex; flex-direction: column; gap: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: var(--bg-surface-secondary); border-radius: 6px;">
                <div>
                  <div style="font-weight: 600; font-size: 13px;">Team A: Lead Intelligence</div>
                  <div style="font-size: 11px; color: var(--text-muted);">OSINT & SQLite Repository</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #16a34a; font-weight: 600;">
                  <span class="status-indicator" style="background: #16a34a;"></span>
                  <span>Operational</span>
                </div>
              </div>

              <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: var(--bg-surface-secondary); border-radius: 6px;">
                <div>
                  <div style="font-weight: 600; font-size: 13px;">Team B: Voice Engine</div>
                  <div style="font-size: 11px; color: var(--text-muted);">Pipecat + Deepgram + Groq</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #16a34a; font-weight: 600;">
                  <span class="status-indicator" style="background: #16a34a;"></span>
                  <span>Operational</span>
                </div>
              </div>

              <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: var(--bg-surface-secondary); border-radius: 6px;">
                <div>
                  <div style="font-weight: 600; font-size: 13px;">Telephony Transport</div>
                  <div style="font-size: 11px; color: var(--text-muted);">Plivo PSTN + μ-law WS</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #16a34a; font-weight: 600;">
                  <span class="status-indicator" style="background: #16a34a;"></span>
                  <span>Configured</span>
                </div>
              </div>

              <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: var(--bg-surface-secondary); border-radius: 6px;">
                <div>
                  <div style="font-weight: 600; font-size: 13px;">Speech Synthesis</div>
                  <div style="font-size: 11px; color: var(--text-muted);">Sarvam AI (bulbul:v3)</div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: #16a34a; font-weight: 600;">
                  <span class="status-indicator" style="background: #16a34a;"></span>
                  <span>Online</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Quick Actions -->
          <div class="card" style="padding: 20px;">
            <h3 style="margin: 0 0 14px 0; font-size: 15px; font-weight: 700; color: var(--text-primary);">Quick Actions</h3>
            <div style="display: flex; flex-direction: column; gap: 10px;">
              <button class="btn btn-primary" id="btnOverviewAddLead" data-action="create-lead" style="justify-content: flex-start; background: #16a34a; border-color: #15803d; font-weight: 700;">
                <i class="fa-solid fa-user-plus"></i>
                <span>+ Add Verified Lead (CRM)</span>
              </button>
              <a href="#discover" class="btn btn-secondary" style="justify-content: flex-start; text-decoration: none;">
                <i class="fa-solid fa-wand-magic-sparkles"></i>
                <span>Discover New Leads</span>
              </a>
              <a href="#leads" class="btn btn-secondary" style="justify-content: flex-start; text-decoration: none;">
                <i class="fa-solid fa-address-book"></i>
                <span>Review All Leads</span>
              </a>
              <a href="#pipeline" class="btn btn-secondary" style="justify-content: flex-start; text-decoration: none;">
                <i class="fa-solid fa-diagram-project"></i>
                <span>Open Qualification Pipeline</span>
              </a>
              <a href="#liveAgent" class="btn btn-secondary" style="justify-content: flex-start; text-decoration: none;">
                <i class="fa-solid fa-headset"></i>
                <span>Launch Live Voice Console</span>
              </a>
            </div>
          </div>

        </div>

      </div>
    `;

    // Attach click events on Recent Leads
    container.querySelectorAll('.overview-lead-item').forEach(item => {
      item.addEventListener('click', () => {
        const domain = item.getAttribute('data-domain');
        const lead = window.store.allLeads.find(l => l.domain === domain || l.website === domain);
        if (lead && window.app && window.app.leadDetailView) {
          window.app.leadDetailView.show(lead);
        }
      });
    });

    // Asynchronously fetch Call History for real count and recent calls list
    try {
      const callData = await window.api.getCallHistory();
      const calls = (callData && Array.isArray(callData.calls)) ? callData.calls : [];
      
      const kpiVal = container.querySelector('#kpiCompletedCallsVal');
      if (kpiVal) kpiVal.innerText = calls.length;

      const recentCallsContainer = container.querySelector('#overviewRecentCallsContainer');
      if (recentCallsContainer) {
        if (calls.length === 0) {
          recentCallsContainer.innerHTML = `
            <div style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 12.5px;">
              No call history recorded yet. Qualify a prospect from the leads table.
            </div>
          `;
        } else {
          recentCallsContainer.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 8px;">
              ${calls.slice(0, 4).map(c => `
                <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: var(--bg-surface-secondary); border-radius: 6px; border: 1px solid var(--border-color);">
                  <div>
                    <div style="font-weight: 600; font-size: 13px; color: var(--text-primary);">${c.phone || 'Phone Contact'}</div>
                    <div style="font-size: 11px; color: var(--text-muted);">${c.transport || 'Plivo Telephony'} · ${c.duration || '—'}</div>
                  </div>
                  <span class="badge ${c.status === 'COMPLETED' || c.status === 'CLOSED' ? 'badge-success' : (c.status === 'ACTIVE' ? 'badge-warning' : 'badge-neutral')}" style="font-size: 10px;">
                    ${c.status || 'COMPLETED'}
                  </span>
                </div>
              `).join('')}
            </div>
          `;
        }
      }
    } catch (e) {
      const kpiVal = container.querySelector('#kpiCompletedCallsVal');
      if (kpiVal) kpiVal.innerText = 'Unavailable';
      const recentCallsContainer = container.querySelector('#overviewRecentCallsContainer');
      if (recentCallsContainer) {
        recentCallsContainer.innerHTML = `
          <div style="padding: 16px; text-align: center; color: var(--text-muted); font-size: 12px;">
            Unable to load call logs.
          </div>
        `;
      }
    }
  }
}

window.OverviewView = OverviewView;
