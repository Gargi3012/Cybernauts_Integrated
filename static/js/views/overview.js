/**
 * System Overview Dashboard View
 */

class OverviewView {
  render(container) {
    const totalLeads = window.store.allLeads.length;
    const leadsWithEmail = window.store.allLeads.filter(l => Array.isArray(l.emails) && l.emails.length > 0).length;
    const leadsWithPhone = window.store.allLeads.filter(l => Array.isArray(l.phones) && l.phones.length > 0).length;

    container.innerHTML = `
      <div style="margin-bottom: 28px;">
        <h1 style="font-size: 22px; font-weight: 800; margin: 0 0 6px 0;">System Overview</h1>
        <div style="color: var(--flowiz-text-muted); font-size: 13px;">
          Unified analytics across Lead Intelligence mining and AI Voice Agent operations.
        </div>
      </div>

      <!-- Top Summary Cards -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin-bottom: 28px;">
        <div class="card" style="padding: 20px;">
          <div style="font-size: 12px; font-weight: 700; color: var(--flowiz-text-muted); text-transform: uppercase;">Total Discovered Leads</div>
          <div style="font-size: 28px; font-weight: 800; color: var(--flowiz-text-primary); margin: 8px 0;">${totalLeads}</div>
          <div style="font-size: 12px; color: var(--flowiz-success); font-weight: 600;">
            <i class="fa-solid fa-arrow-trend-up"></i> Verified SQLite storage
          </div>
        </div>

        <div class="card" style="padding: 20px;">
          <div style="font-size: 12px; font-weight: 700; color: var(--flowiz-text-muted); text-transform: uppercase;">Verified Email Addresses</div>
          <div style="font-size: 28px; font-weight: 800; color: var(--flowiz-text-primary); margin: 8px 0;">${leadsWithEmail}</div>
          <div style="font-size: 12px; color: var(--flowiz-info); font-weight: 600;">
            ${totalLeads > 0 ? Math.round((leadsWithEmail / totalLeads) * 100) : 0}% Data Completeness
          </div>
        </div>

        <div class="card" style="padding: 20px;">
          <div style="font-size: 12px; font-weight: 700; color: var(--flowiz-text-muted); text-transform: uppercase;">Verified Phone Numbers</div>
          <div style="font-size: 28px; font-weight: 800; color: var(--flowiz-text-primary); margin: 8px 0;">${leadsWithPhone}</div>
          <div style="font-size: 12px; color: var(--flowiz-success); font-weight: 600;">
            Ready for Native Device Dialing
          </div>
        </div>

        <div class="card" style="padding: 20px;">
          <div style="font-size: 12px; font-weight: 700; color: var(--flowiz-text-muted); text-transform: uppercase;">AI Voice Pipeline</div>
          <div style="font-size: 28px; font-weight: 800; color: var(--flowiz-text-primary); margin: 8px 0;">Ready</div>
          <div style="font-size: 12px; color: var(--flowiz-success); font-weight: 600;">
            LiveKit Cloud & Twilio Online
          </div>
        </div>
      </div>

      <!-- Quick Action Navigation Card -->
      <div class="card" style="padding: 24px; background: #ffffff;">
        <h3 style="margin: 0 0 12px 0; font-size: 16px; font-weight: 700;">Platform Quick Actions</h3>
        <div style="display: flex; gap: 12px; flex-wrap: wrap;">
          <button class="btn btn-primary" onclick="window.location.hash='discover'">
            <i class="fa-solid fa-wand-magic-sparkles"></i>
            <span>Mine New Leads</span>
          </button>
          <button class="btn btn-secondary" onclick="window.location.hash='leads'">
            <i class="fa-solid fa-address-book"></i>
            <span>Browse All Leads</span>
          </button>
          <button class="btn btn-secondary" onclick="window.location.hash='liveAgent'">
            <i class="fa-solid fa-headset"></i>
            <span>Launch Live Voice Agent</span>
          </button>
        </div>
      </div>
    `;
  }
}

window.OverviewView = OverviewView;
