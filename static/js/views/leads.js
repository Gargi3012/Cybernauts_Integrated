/**
 * Lead Intelligence — All Leads Management View
 * Enterprise B2B SaaS Table with Filtering, Sorting, Pagination,
 * AI Qualification status badges, and 1-Click Call Qualification Launch
 */

class LeadsView {
  render(container) {
    const allFiltered = window.store.getFilteredLeads();
    const categories = Object.keys(window.store.categories || {});
    
    // Pagination slicing
    const totalCount = allFiltered.length;
    const page = window.store.page || 1;
    const pageSize = window.store.pageSize || 15;
    const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
    const currentPage = Math.min(page, totalPages);
    const startIdx = (currentPage - 1) * pageSize;
    const endIdx = Math.min(startIdx + pageSize, totalCount);
    const pageLeads = allFiltered.slice(startIdx, endIdx);

    container.innerHTML = `
      <div style="margin-bottom: 20px; display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 12px;">
        <div>
          <h1 style="font-size: 22px; font-weight: 800; margin: 0 0 6px 0; color: var(--text-primary);">All Leads Directory</h1>
          <div style="color: var(--text-muted); font-size: 13.5px;">
            Verified B2B company intelligence repository. Select any prospect to inspect data or initiate an AI qualification call.
          </div>
        </div>
        <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
          <button class="btn btn-primary btn-sm" id="btnOpenCreateLeadModal" style="background: #16a34a; border-color: #15803d; font-weight: 700; display: flex; align-items: center; gap: 6px; box-shadow: 0 1px 3px rgba(22, 163, 74, 0.3);">
            <i class="fa-solid fa-user-plus"></i>
            <span>+ Add Verified Lead</span>
          </button>
          <a href="#discover" class="btn btn-secondary btn-sm" style="text-decoration: none;">
            <i class="fa-solid fa-compass"></i>
            <span>Discover Pipeline</span>
          </a>
        </div>
      </div>

      <!-- Filter Controls Bar -->
      <div class="card" style="margin-bottom: 20px; padding: 16px 20px;">
        <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
          
          <!-- Search input -->
          <div style="position: relative; flex: 1; min-width: 240px;">
            <i class="fa-solid fa-magnifying-glass" style="position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: var(--text-muted); font-size: 12px;"></i>
            <input 
              type="text" 
              id="leadSearchInput" 
              class="form-input" 
              placeholder="Search companies, domains, contacts, or industries..." 
              value="${window.store.searchQuery || ''}" 
              style="padding-left: 32px;"
            />
          </div>

          <!-- Industry dropdown -->
          <select id="leadCategorySelect" class="form-input" style="max-width: 180px;">
            <option value="">All Industries (${window.store.allLeads.length})</option>
            ${categories.map(c => `
              <option value="${c}" ${window.store.activeCategory === c ? 'selected' : ''}>
                ${c} (${window.store.categories[c]})
              </option>
            `).join('')}
          </select>

          <!-- Qualification Status filter -->
          <select id="leadQualStatusSelect" class="form-input" style="max-width: 170px;">
            <option value="">All Qualification</option>
            <option value="qualified" ${window.store.activeQualStatus === 'qualified' ? 'selected' : ''}>Qualified</option>
            <option value="in_progress" ${window.store.activeQualStatus === 'in_progress' ? 'selected' : ''}>In Progress</option>
            <option value="failed" ${window.store.activeQualStatus === 'failed' ? 'selected' : ''}>Failed / Disqualified</option>
            <option value="unqualified" ${window.store.activeQualStatus === 'unqualified' ? 'selected' : ''}>Unqualified</option>
          </select>

          <!-- Quality Tier filter -->
          <select id="leadQualitySelect" class="form-input" style="max-width: 130px;">
            <option value="">All Quality</option>
            <option value="High" ${window.store.activeQuality === 'High' ? 'selected' : ''}>High</option>
            <option value="Medium" ${window.store.activeQuality === 'Medium' ? 'selected' : ''}>Medium</option>
            <option value="Low" ${window.store.activeQuality === 'Low' ? 'selected' : ''}>Low</option>
          </select>

          <!-- Checkbox filters -->
          <div style="display: flex; gap: 12px; font-size: 12.5px; align-items: center;">
            <label style="display: flex; align-items: center; gap: 5px; cursor: pointer;">
              <input type="checkbox" id="chkEmail" ${window.store.filterHasEmail ? 'checked' : ''} />
              <span>Email</span>
            </label>
            <label style="display: flex; align-items: center; gap: 5px; cursor: pointer;">
              <input type="checkbox" id="chkPhone" ${window.store.filterHasPhone ? 'checked' : ''} />
              <span>Phone</span>
            </label>
          </div>

        </div>
      </div>

      <!-- Lead Management Table -->
      <div class="card" style="padding: 0; overflow: hidden; margin-bottom: 20px;">
        ${totalCount === 0 ? `
          <div style="padding: 56px 24px; text-align: center;">
            <i class="fa-solid fa-folder-open text-muted" style="font-size: 36px; margin-bottom: 12px;"></i>
            <div style="font-weight: 700; font-size: 16px; color: var(--text-primary);">No leads found</div>
            <div class="text-muted" style="font-size: 13px; margin: 4px 0 16px 0;">
              No leads match your active filters or search criteria.
            </div>
            <div style="display: flex; gap: 10px; justify-content: center; align-items: center;">
              <button class="btn btn-primary btn-sm" id="btnEmptyAddLead" data-action="create-lead" style="background: #16a34a; border-color: #15803d; font-weight: 700;">
                <i class="fa-solid fa-user-plus"></i> Add Verified Lead Now
              </button>
              <button class="btn btn-secondary btn-sm" id="btnClearFilters">Clear Filters</button>
            </div>
          </div>
        ` : `
          <div style="overflow-x: auto;">
            <table class="data-table" style="width: 100%; border-collapse: collapse;">
              <thead>
                <tr>
                  <th style="width: 28%;">Company</th>
                  <th style="width: 22%;">Contact Person</th>
                  <th style="width: 15%;">Industry / Location</th>
                  <th style="width: 16%;">AI Qualification</th>
                  <th style="width: 19%; text-align: right;">Actions</th>
                </tr>
              </thead>
              <tbody>
                ${pageLeads.map(l => {
                  const hasPhone = Array.isArray(l.phones) && l.phones.length > 0;
                  const phoneNum = hasPhone ? l.phones[0] : null;
                  const hasEmail = Array.isArray(l.emails) && l.emails.length > 0;
                  const emailAddr = hasEmail ? l.emails[0] : null;
                  const person = (Array.isArray(l.people) && l.people.length > 0) ? l.people[0] : null;
                  const qualStatus = (l.qualification_status || l.call_status || 'unqualified').toLowerCase();
                  const qualScore = l.qualification_score;

                  return `
                    <tr class="lead-table-row">
                      <!-- Company Column -->
                      <td>
                        <div style="display: flex; align-items: flex-start; gap: 10px;">
                          <div style="width: 32px; height: 32px; border-radius: 6px; background: rgba(79, 70, 229, 0.08); color: var(--color-primary); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px; flex-shrink: 0;">
                            ${(l.company_name || 'C').charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <div style="font-weight: 700; font-size: 14px; color: var(--text-primary); cursor: pointer;" class="btn-open-lead-name" data-domain="${l.domain || l.website}">
                              ${l.company_name || 'Unnamed Company'}
                            </div>
                            <div class="font-mono text-muted" style="font-size: 11.5px;">
                              ${l.domain || l.website || 'No website domain'}
                            </div>
                          </div>
                        </div>
                      </td>

                      <!-- Contact Person Column -->
                      <td>
                        <div>
                          <div style="font-weight: 600; font-size: 13px; color: var(--text-primary);">
                            ${person && person.name ? person.name : '<span class="text-muted" style="font-weight: normal;">Unassigned contact</span>'}
                          </div>
                          ${person && person.designation ? `<div style="font-size: 11px; color: var(--text-muted);">${person.designation}</div>` : ''}
                          
                          <div style="display: flex; gap: 6px; margin-top: 4px; flex-wrap: wrap;">
                            ${phoneNum ? `
                              <span class="badge badge-neutral font-mono" style="font-size: 10.5px; padding: 2px 6px;">
                                <i class="fa-solid fa-phone" style="font-size: 9px; margin-right: 3px;"></i>${phoneNum}
                              </span>
                            ` : ''}
                            ${emailAddr ? `
                              <span class="badge badge-neutral font-mono" style="font-size: 10.5px; padding: 2px 6px;">
                                <i class="fa-solid fa-envelope" style="font-size: 9px; margin-right: 3px;"></i>${emailAddr}
                              </span>
                            ` : ''}
                          </div>
                        </div>
                      </td>

                      <!-- Industry & Location -->
                      <td>
                        <div style="font-size: 12.5px; font-weight: 600; color: var(--text-primary);">
                          ${l.industry || 'B2B Services'}
                        </div>
                        <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">
                          ${l.location || 'Location unverified'}
                        </div>
                      </td>

                      <!-- Qualification Status & Score -->
                      <td>
                        <div style="display: flex; flex-direction: column; gap: 4px; align-items: flex-start;">
                          <span class="badge ${
                            qualStatus === 'qualified' ? 'badge-success' :
                            (qualStatus === 'in_progress' || qualStatus === 'initiated' || qualStatus === 'ringing' ? 'badge-warning' :
                            (qualStatus === 'failed' || qualStatus === 'disqualified' ? 'badge-danger' : 'badge-neutral'))
                          }" style="font-size: 11px;">
                            ${qualStatus === 'qualified' ? '✓ Qualified' :
                              (qualStatus === 'in_progress' || qualStatus === 'initiated' ? '● In Progress' :
                              (qualStatus === 'failed' || qualStatus === 'disqualified' ? '✕ Disqualified' : 'Unqualified'))}
                          </span>
                          ${qualScore !== undefined && qualScore !== null && qualScore > 0 ? `
                            <div style="font-size: 11px; font-weight: 700; color: var(--color-primary);">
                              Score: ${qualScore}/100
                            </div>
                          ` : ''}
                        </div>
                      </td>

                      <!-- Actions -->
                      <td style="text-align: right;">
                        <div style="display: flex; gap: 8px; justify-content: flex-end; align-items: center;">
                          ${hasPhone ? `
                            <button class="btn btn-primary btn-sm btn-quick-qualify" data-domain="${l.domain || l.website}" title="Qualify with AI Voice Agent via Plivo">
                              <i class="fa-solid fa-phone-volume"></i>
                              <span>Qualify</span>
                            </button>
                          ` : `
                            <button class="btn btn-secondary btn-sm" disabled title="No callable phone available" style="opacity: 0.5;">
                              <i class="fa-solid fa-phone-slash"></i>
                              <span>No Phone</span>
                            </button>
                          `}
                          <button class="btn btn-secondary btn-sm btn-view-dossier" data-domain="${l.domain || l.website}" title="View Company Dossier">
                            <span>Dossier</span>
                            <i class="fa-solid fa-chevron-right" style="font-size: 10px;"></i>
                          </button>
                        </div>
                      </td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>

          <!-- Pagination Bar -->
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; border-top: 1px solid var(--border-color); background: var(--bg-surface-secondary); font-size: 12.5px;">
            <div class="text-muted">
              Showing <strong>${startIdx + 1}</strong> - <strong>${endIdx}</strong> of <strong>${totalCount}</strong> leads
            </div>
            <div style="display: flex; gap: 6px; align-items: center;">
              <button class="btn btn-secondary btn-sm" id="btnPrevPage" ${currentPage <= 1 ? 'disabled' : ''}>
                <i class="fa-solid fa-chevron-left"></i>
              </button>
              <span style="font-weight: 600; padding: 0 8px;">Page ${currentPage} of ${totalPages}</span>
              <button class="btn btn-secondary btn-sm" id="btnNextPage" ${currentPage >= totalPages ? 'disabled' : ''}>
                <i class="fa-solid fa-chevron-right"></i>
              </button>
            </div>
          </div>
        `}
      </div>
    `;

    this.attachEvents(container);
  }

  attachEvents(container) {
    const searchInput = container.querySelector('#leadSearchInput');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        window.store.searchQuery = e.target.value;
        window.store.page = 1;
        this.render(container);
      });
    }

    const catSelect = container.querySelector('#leadCategorySelect');
    if (catSelect) {
      catSelect.addEventListener('change', (e) => {
        window.store.activeCategory = e.target.value || null;
        window.store.page = 1;
        this.render(container);
      });
    }

    const qualSelect = container.querySelector('#leadQualStatusSelect');
    if (qualSelect) {
      qualSelect.addEventListener('change', (e) => {
        window.store.activeQualStatus = e.target.value || null;
        window.store.page = 1;
        this.render(container);
      });
    }

    const qualitySelect = container.querySelector('#leadQualitySelect');
    if (qualitySelect) {
      qualitySelect.addEventListener('change', (e) => {
        window.store.activeQuality = e.target.value || null;
        window.store.page = 1;
        this.render(container);
      });
    }

    const chkEmail = container.querySelector('#chkEmail');
    if (chkEmail) {
      chkEmail.addEventListener('change', (e) => {
        window.store.filterHasEmail = e.target.checked;
        window.store.page = 1;
        this.render(container);
      });
    }

    const chkPhone = container.querySelector('#chkPhone');
    if (chkPhone) {
      chkPhone.addEventListener('change', (e) => {
        window.store.filterHasPhone = e.target.checked;
        window.store.page = 1;
        this.render(container);
      });
    }

    const btnClear = container.querySelector('#btnClearFilters');
    if (btnClear) {
      btnClear.addEventListener('click', () => {
        window.store.searchQuery = '';
        window.store.activeCategory = null;
        window.store.activeQualStatus = null;
        window.store.activeQuality = null;
        window.store.filterHasEmail = false;
        window.store.filterHasPhone = false;
        window.store.page = 1;
        this.render(container);
      });
    }

    // Pagination buttons
    const btnPrev = container.querySelector('#btnPrevPage');
    if (btnPrev) {
      btnPrev.addEventListener('click', () => {
        if (window.store.page > 1) {
          window.store.page--;
          this.render(container);
        }
      });
    }

    const btnNext = container.querySelector('#btnNextPage');
    if (btnNext) {
      btnNext.addEventListener('click', () => {
        window.store.page = (window.store.page || 1) + 1;
        this.render(container);
      });
    }

    // Dossier & Lead Name click handlers
    const openLead = (domain) => {
      const lead = window.store.allLeads.find(l => l.domain === domain || l.website === domain);
      if (lead && window.app && window.app.leadDetailView) {
        window.app.leadDetailView.show(lead);
      }
    };

    container.querySelectorAll('.btn-view-dossier, .btn-open-lead-name').forEach(el => {
      el.addEventListener('click', () => {
        const domain = el.getAttribute('data-domain');
        openLead(domain);
      });
    });

    // 1-Click Quick Qualify
    container.querySelectorAll('.btn-quick-qualify').forEach(btn => {
      btn.addEventListener('click', () => {
        const domain = btn.getAttribute('data-domain');
        const lead = window.store.allLeads.find(l => l.domain === domain || l.website === domain);
        if (lead && window.app && window.app.leadDetailView) {
          window.app.leadDetailView.show(lead, { autoTriggerConfirm: true });
        }
      });
    });
  }
}

window.LeadsView = LeadsView;
