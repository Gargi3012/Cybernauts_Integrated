/**
 * Lead Intelligence — Lead Detail Drawer View
 * Displays rich scraped lead metadata with native device tel:+<number> dialer links
 */

class LeadDetailView {
  show(lead) {
    const modalContainer = document.getElementById('modalContainer');
    if (!modalContainer) return;

    modalContainer.innerHTML = `
      <div class="modal-backdrop" style="position: fixed; inset: 0; background: rgba(15, 23, 42, 0.4); backdrop-filter: blur(4px); z-index: 90; display: flex; justify-content: flex-end;">
        <div class="drawer" style="width: 540px; background: #ffffff; height: 100vh; overflow-y: auto; padding: 32px; box-shadow: var(--shadow-lg); border-left: 1px solid var(--flowiz-border); display: flex; flex-direction: column;">
          
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px;">
            <div>
              <span class="badge badge-success" style="margin-bottom: 8px;">${lead.lead_quality || 'Verified Lead'}</span>
              <h2 style="margin: 0; font-size: 22px; font-weight: 800; color: var(--flowiz-text-primary);">${lead.company_name || 'Lead Record'}</h2>
              <div class="font-mono text-muted" style="font-size: 13px;">${lead.domain || lead.website}</div>
            </div>
            <button id="btnCloseDrawer" class="btn btn-secondary btn-sm" style="padding: 4px 10px;">✕</button>
          </div>

          <div style="flex: 1; display: flex; flex-direction: column; gap: 24px;">
            
            <!-- Company Overview -->
            <div class="card" style="padding: 16px;">
              <div style="font-weight: 700; font-size: 13px; text-transform: uppercase; color: var(--flowiz-text-muted); margin-bottom: 8px;">Company Overview</div>
              <div style="font-size: 13px; color: var(--flowiz-text-secondary); line-height: 1.5;">
                ${lead.description || 'No detailed description available for this lead.'}
              </div>
              <div style="display: flex; gap: 16px; margin-top: 14px; font-size: 12px; color: var(--flowiz-text-muted);">
                <div><strong>Industry:</strong> ${lead.industry || 'B2B'}</div>
                <div><strong>Location:</strong> ${lead.location || 'Unknown'}</div>
              </div>
            </div>

            <!-- Verified Contact Vectors -->
            <div class="card" style="padding: 16px;">
              <div style="font-weight: 700; font-size: 13px; text-transform: uppercase; color: var(--flowiz-text-muted); margin-bottom: 12px;">Contact Vectors</div>
              
              <!-- Native Device Phone Link (tel: protocol) -->
              <div style="margin-bottom: 12px;">
                <div style="font-size: 12px; font-weight: 600; color: var(--flowiz-text-secondary); margin-bottom: 6px;">Phone Numbers:</div>
                ${Array.isArray(lead.phones) && lead.phones.length > 0 ? lead.phones.map(p => `
                  <a href="tel:${p}" class="btn-phone-dialer" style="margin-right: 8px; margin-bottom: 6px;" title="Click to dial using native device phone app">
                    <i class="fa-solid fa-phone"></i>
                    <span>Call ${p}</span>
                  </a>
                `).join('') : '<div style="font-size: 12px; color: var(--flowiz-text-muted);">No phone number recorded</div>'}
              </div>

              <div>
                <div style="font-size: 12px; font-weight: 600; color: var(--flowiz-text-secondary); margin-bottom: 6px;">Emails:</div>
                ${Array.isArray(lead.emails) && lead.emails.length > 0 ? lead.emails.map(e => `
                  <div style="font-size: 13px; color: var(--flowiz-text-primary); font-family: var(--font-mono); display: flex; align-items: center; gap: 6px;">
                    <i class="fa-solid fa-envelope text-accent"></i> ${e}
                  </div>
                `).join('') : '<div style="font-size: 12px; color: var(--flowiz-text-muted);">No email recorded</div>'}
              </div>
            </div>

            <!-- Tech Stack Detection -->
            <div class="card" style="padding: 16px;">
              <div style="font-weight: 700; font-size: 13px; text-transform: uppercase; color: var(--flowiz-text-muted); margin-bottom: 12px;">Detected Tech Stack</div>
              <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                ${Array.isArray(lead.tech_stack) && lead.tech_stack.length > 0 ? lead.tech_stack.map(t => `
                  <span class="badge badge-info">${t}</span>
                `).join('') : '<div style="font-size: 12px; color: var(--flowiz-text-muted);">No tech stack detected</div>'}
              </div>
            </div>

          </div>

        </div>
      </div>
    `;

    const btnClose = modalContainer.querySelector('#btnCloseDrawer');
    if (btnClose) {
      btnClose.addEventListener('click', () => {
        modalContainer.innerHTML = '';
      });
    }
  }
}

window.LeadDetailView = LeadDetailView;
