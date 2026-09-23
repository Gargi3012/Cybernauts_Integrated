/**
 * Lead Intelligence — All Leads View
 * Clean Light Theme SaaS Table & Grid View with native tel:+<number> links
 */

class LeadsView {
  render(container) {
    const leads = window.store.getFilteredLeads();
    const categories = Object.keys(window.store.categories);

    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 20px; font-weight: 800; margin: 0 0 6px 0;">All Verified Leads</h2>
        <div style="color: var(--flowiz-text-muted); font-size: 13px;">
          Browse and filter scraped B2B company intelligence. Click phone numbers to dial using your device's native phone app.
        </div>
      </div>

      <!-- Filter Controls -->
      <div class="card" style="margin-bottom: 24px; padding: 16px 20px;">
        <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
          <input 
            type="text" 
            id="leadSearchInput" 
            class="form-input" 
            placeholder="Search by company, domain, or industry..." 
            value="${window.store.searchQuery || ''}" 
            style="max-width: 320px;"
          />
          <select id="leadCategorySelect" class="form-input" style="max-width: 200px;">
            <option value="">All Industries (${window.store.allLeads.length})</option>
            ${categories.map(c => `<option value="${c}" ${window.store.activeCategory === c ? 'selected' : ''}>${c} (${window.store.categories[c]})</option>`).join('')}
          </select>
          <div style="margin-left: auto; display: flex; gap: 12px; font-size: 13px;">
            <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
              <input type="checkbox" id="chkEmail" ${window.store.filterHasEmail ? 'checked' : ''} />
              <span>Email Available</span>
            </label>
            <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
              <input type="checkbox" id="chkPhone" ${window.store.filterHasPhone ? 'checked' : ''} />
              <span>Phone Available</span>
            </label>
          </div>
        </div>
      </div>

      <!-- Leads Grid / List -->
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 20px;">
        ${leads.length === 0 ? `
          <div class="card" style="grid-column: 1 / -1; text-align: center; padding: 48px;">
            <i class="fa-solid fa-folder-open text-muted" style="font-size: 32px; margin-bottom: 12px;"></i>
            <div style="font-weight: 600; font-size: 15px;">No leads match your active filters</div>
            <div class="text-muted" style="font-size: 13px; margin-top: 4px;">Try searching for another keyword or clearing search filters.</div>
          </div>
        ` : leads.map(l => `
          <div class="card" style="display: flex; flex-direction: column; justify-content: space-between;">
            <div>
              <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                <div>
                  <div style="font-weight: 700; font-size: 16px; color: var(--flowiz-text-primary);">${l.company_name || 'Unknown Entity'}</div>
                  <div class="font-mono text-muted" style="font-size: 12px;">${l.domain || l.website || 'N/A'}</div>
                </div>
                <span class="badge badge-success">${l.lead_quality || 'High'}</span>
              </div>

              <div style="margin-bottom: 12px; font-size: 13px; color: var(--flowiz-text-secondary); line-height: 1.4;">
                ${(l.description || 'No description available for this lead.').slice(0, 110)}...
              </div>

              <!-- Contact Vectors -->
              <div style="display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px;">
                ${Array.isArray(l.emails) && l.emails.length > 0 ? `
                  <div style="font-size: 12px; color: var(--flowiz-text-secondary); display: flex; align-items: center; gap: 6px;">
                    <i class="fa-solid fa-envelope text-accent"></i>
                    <span>${l.emails[0]}</span>
                  </div>
                ` : ''}

                <!-- Native Device Phone Dialer Link (tel: protocol) -->
                ${Array.isArray(l.phones) && l.phones.length > 0 ? `
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <a href="tel:${l.phones[0]}" class="btn-phone-dialer" title="Click to dial using your device native phone app">
                      <i class="fa-solid fa-phone"></i>
                      <span>Call ${l.phones[0]}</span>
                    </a>
                  </div>
                ` : `
                  <div style="font-size: 12px; color: var(--flowiz-text-muted);">No direct phone number scraped</div>
                `}
              </div>
            </div>

            <div style="display: flex; justify-content: space-between; align-items: center; pt-3; border-top: 1px solid var(--flowiz-border); padding-top: 12px;">
              <span class="badge badge-info">${l.industry || 'B2B'}</span>
              <button class="btn btn-secondary btn-sm btn-view-detail" data-domain="${l.domain}">
                <span>View Details</span>
                <i class="fa-solid fa-chevron-right" style="font-size: 10px;"></i>
              </button>
            </div>
          </div>
        `).join('')}
      </div>
    `;

    this.attachEvents(container);
  }

  attachEvents(container) {
    const searchInput = container.querySelector('#leadSearchInput');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        window.store.searchQuery = e.target.value;
        this.render(container);
      });
    }

    const catSelect = container.querySelector('#leadCategorySelect');
    if (catSelect) {
      catSelect.addEventListener('change', (e) => {
        window.store.activeCategory = e.target.value || null;
        this.render(container);
      });
    }

    const chkEmail = container.querySelector('#chkEmail');
    if (chkEmail) {
      chkEmail.addEventListener('change', (e) => {
        window.store.filterHasEmail = e.target.checked;
        this.render(container);
      });
    }

    const chkPhone = container.querySelector('#chkPhone');
    if (chkPhone) {
      chkPhone.addEventListener('change', (e) => {
        window.store.filterHasPhone = e.target.checked;
        this.render(container);
      });
    }

    container.querySelectorAll('.btn-view-detail').forEach(btn => {
      btn.addEventListener('click', () => {
        const domain = btn.getAttribute('data-domain');
        const lead = window.store.allLeads.find(l => l.domain === domain);
        if (lead && window.app && window.app.leadDetailView) {
          window.app.leadDetailView.show(lead);
        }
      });
    });
  }
}

window.LeadsView = LeadsView;
