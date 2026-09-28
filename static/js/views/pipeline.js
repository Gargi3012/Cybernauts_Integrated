/**
 * Lead Intelligence & Voice Qualification Pipeline (Kanban Board)
 * Displays leads across verified lifecycle stages:
 * New / Discovered -> Calling / In Progress -> Qualified -> Disqualified / Failed
 */

class PipelineView {
  render(container) {
    const leads = window.store.allLeads || [];

    // Categorize leads into pipeline stages
    const cols = {
      new: [],
      in_progress: [],
      qualified: [],
      disqualified: []
    };

    leads.forEach(l => {
      const qStatus = (l.qualification_status || '').toLowerCase();
      const cStatus = (l.call_status || '').toLowerCase();

      if (qStatus === 'qualified') {
        cols.qualified.push(l);
      } else if (['initiating', 'initiated', 'ringing', 'in_progress'].includes(cStatus) || qStatus === 'in_progress') {
        cols.in_progress.push(l);
      } else if (qStatus === 'disqualified' || qStatus === 'failed' || cStatus === 'failed') {
        cols.disqualified.push(l);
      } else {
        cols.new.push(l);
      }
    });

    container.innerHTML = `
      <div style="margin-bottom: 24px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 12px;">
        <div>
          <h1 style="font-size: 22px; font-weight: 800; margin: 0 0 6px 0; color: var(--text-primary);">Qualification Pipeline</h1>
          <div style="color: var(--text-muted); font-size: 13.5px;">
            Kanban workflow tracking leads from OSINT discovery through AI Voice qualification to final outcome.
          </div>
        </div>
        <div style="display: flex; gap: 8px;">
          <a href="#leads" class="btn btn-secondary btn-sm">
            <i class="fa-solid fa-list"></i> Table View
          </a>
        </div>
      </div>

      <!-- Kanban Columns Container -->
      <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; align-items: flex-start; overflow-x: auto; padding-bottom: 16px;">
        
        <!-- Column 1: New / Discovered -->
        <div style="background: var(--bg-surface-secondary); border-radius: 8px; border: 1px solid var(--border-color); padding: 14px; min-width: 250px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <div style="display: flex; align-items: center; gap: 6px; font-weight: 700; font-size: 13px; color: var(--text-primary);">
              <span class="status-indicator" style="background: #94a3b8;"></span>
              <span>Discovered</span>
            </div>
            <span class="badge badge-neutral font-mono">${cols.new.length}</span>
          </div>

          <div style="display: flex; flex-direction: column; gap: 10px;">
            ${cols.new.length === 0 ? `
              <div style="padding: 24px; text-align: center; color: var(--text-muted); font-size: 12px;">
                No new leads.
              </div>
            ` : cols.new.map(l => this.renderLeadCard(l)).join('')}
          </div>
        </div>

        <!-- Column 2: In Progress / Calling -->
        <div style="background: var(--bg-surface-secondary); border-radius: 8px; border: 1px solid var(--border-color); padding: 14px; min-width: 250px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <div style="display: flex; align-items: center; gap: 6px; font-weight: 700; font-size: 13px; color: var(--text-primary);">
              <span class="status-indicator" style="background: #f59e0b;"></span>
              <span>In Progress / Call</span>
            </div>
            <span class="badge badge-warning font-mono">${cols.in_progress.length}</span>
          </div>

          <div style="display: flex; flex-direction: column; gap: 10px;">
            ${cols.in_progress.length === 0 ? `
              <div style="padding: 24px; text-align: center; color: var(--text-muted); font-size: 12px;">
                No calls in progress.
              </div>
            ` : cols.in_progress.map(l => this.renderLeadCard(l)).join('')}
          </div>
        </div>

        <!-- Column 3: Qualified -->
        <div style="background: var(--bg-surface-secondary); border-radius: 8px; border: 1px solid var(--border-color); padding: 14px; min-width: 250px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <div style="display: flex; align-items: center; gap: 6px; font-weight: 700; font-size: 13px; color: var(--text-primary);">
              <span class="status-indicator" style="background: #16a34a;"></span>
              <span>AI Qualified</span>
            </div>
            <span class="badge badge-success font-mono">${cols.qualified.length}</span>
          </div>

          <div style="display: flex; flex-direction: column; gap: 10px;">
            ${cols.qualified.length === 0 ? `
              <div style="padding: 24px; text-align: center; color: var(--text-muted); font-size: 12px;">
                No qualified leads yet.
              </div>
            ` : cols.qualified.map(l => this.renderLeadCard(l)).join('')}
          </div>
        </div>

        <!-- Column 4: Disqualified / Review -->
        <div style="background: var(--bg-surface-secondary); border-radius: 8px; border: 1px solid var(--border-color); padding: 14px; min-width: 250px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <div style="display: flex; align-items: center; gap: 6px; font-weight: 700; font-size: 13px; color: var(--text-primary);">
              <span class="status-indicator" style="background: #dc2626;"></span>
              <span>Disqualified / Failed</span>
            </div>
            <span class="badge badge-danger font-mono">${cols.disqualified.length}</span>
          </div>

          <div style="display: flex; flex-direction: column; gap: 10px;">
            ${cols.disqualified.length === 0 ? `
              <div style="padding: 24px; text-align: center; color: var(--text-muted); font-size: 12px;">
                No disqualified leads.
              </div>
            ` : cols.disqualified.map(l => this.renderLeadCard(l)).join('')}
          </div>
        </div>

      </div>
    `;

    this.attachEvents(container);
  }

  renderLeadCard(l) {
    const hasPhone = Array.isArray(l.phones) && l.phones.length > 0;
    const phone = hasPhone ? l.phones[0] : null;
    const person = (Array.isArray(l.people) && l.people.length > 0) ? l.people[0] : null;
    const qualScore = l.qualification_score;

    return `
      <div class="card pipeline-card" style="padding: 12px; margin: 0; cursor: pointer; transition: transform 0.15s ease, box-shadow 0.15s ease;" data-domain="${l.domain || l.website}">
        <div style="font-weight: 700; font-size: 13.5px; color: var(--text-primary); margin-bottom: 2px;">
          ${l.company_name || 'Prospect'}
        </div>
        <div class="font-mono text-muted" style="font-size: 11px; margin-bottom: 8px;">
          ${l.domain || l.website || 'No domain'}
        </div>

        ${person ? `
          <div style="font-size: 11.5px; color: var(--text-secondary); margin-bottom: 6px;">
            <i class="fa-solid fa-user text-muted" style="font-size: 10px; margin-right: 4px;"></i>${person.name}
          </div>
        ` : ''}

        ${phone ? `
          <div class="font-mono" style="font-size: 11px; color: #4338ca; margin-bottom: 8px;">
            <i class="fa-solid fa-phone" style="font-size: 9px; margin-right: 3px;"></i>${phone}
          </div>
        ` : ''}

        <div style="display: flex; justify-content: space-between; align-items: center; pt-2; border-top: 1px solid var(--border-color); padding-top: 8px;">
          <span class="badge badge-info" style="font-size: 10px;">${l.industry || 'B2B'}</span>
          ${qualScore !== undefined && qualScore !== null && qualScore > 0 ? `
            <span class="badge badge-success" style="font-size: 10px;">${qualScore}/100</span>
          ` : `
            <span class="text-muted" style="font-size: 10.5px;">View Dossier →</span>
          `}
        </div>
      </div>
    `;
  }

  attachEvents(container) {
    container.querySelectorAll('.pipeline-card').forEach(card => {
      card.addEventListener('click', () => {
        const domain = card.getAttribute('data-domain');
        const lead = window.store.allLeads.find(l => l.domain === domain || l.website === domain);
        if (lead && window.app && window.app.leadDetailView) {
          window.app.leadDetailView.show(lead);
        }
      });
    });
  }
}

window.PipelineView = PipelineView;
