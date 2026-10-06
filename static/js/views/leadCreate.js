/**
 * Lead Intelligence — CRM Verified Lead Creation Modal
 * Allows adding verified prospects with company intelligence, decision-maker contacts,
 * and direct telephony routing stored in canonical flowiz_leads.
 */

class LeadCreateModal {
  constructor() {
    this.isOpen = false;
  }

  show(initialData = {}) {
    const modalContainer = document.getElementById('modalContainer');
    if (!modalContainer) return;

    this.isOpen = true;
    modalContainer.innerHTML = `
      <div class="modal-backdrop" id="crmModalBackdrop" style="position: fixed; inset: 0; background: rgba(15, 23, 42, 0.55); backdrop-filter: blur(5px); z-index: 100; display: flex; align-items: center; justify-content: center; padding: 20px;">
        <div class="card" style="width: 780px; max-width: 95vw; max-height: 90vh; display: flex; flex-direction: column; padding: 0; background: #ffffff; border-radius: 12px; box-shadow: var(--shadow-xl); border: 1px solid var(--border-color); overflow: hidden; animation: fadeInScale 0.2s ease-out;">
          
          <!-- Modal Header -->
          <div style="padding: 20px 24px; border-bottom: 1px solid var(--border-color); background: linear-gradient(180deg, #faf5ff 0%, #ffffff 100%); display: flex; justify-content: space-between; align-items: flex-start;">
            <div>
              <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                <span class="badge badge-success" style="font-size: 11px; padding: 3px 8px; font-weight: 700;">
                  <i class="fa-solid fa-shield-check" style="margin-right: 4px;"></i>Verified Ingestion
                </span>
                <span class="badge badge-neutral" style="font-size: 11px;">Canonical flowiz_leads</span>
              </div>
              <h2 style="margin: 0; font-size: 19px; font-weight: 800; color: var(--text-primary);">
                <i class="fa-solid fa-building-circle-check" style="color: #6b21a8; margin-right: 6px;"></i>
                Add Verified Lead to CRM
              </h2>
              <div style="font-size: 12.5px; color: var(--text-muted); margin-top: 2px;">
                Persist a fully verified company prospect with callable contact information for instant AI voice outreach.
              </div>
            </div>
            <button id="btnCloseCreateLeadModal" class="btn btn-secondary btn-sm" style="padding: 6px 12px; font-size: 13px;" title="Close">✕</button>
          </div>

          <!-- Modal Scrollable Body -->
          <div style="padding: 24px; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 20px;">
            
            <form id="frmCreateLead" autocomplete="off" onsubmit="return false;">
              
              <!-- SECTION 1: Company Intelligence -->
              <div style="margin-bottom: 22px;">
                <div style="font-size: 13px; font-weight: 800; color: #581c87; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 12px; display: flex; align-items: center; gap: 6px;">
                  <i class="fa-solid fa-building"></i>
                  <span>1. Company Intelligence & Domain</span>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 12px;">
                  <div>
                    <label for="crmCompany" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      Company Name *
                    </label>
                    <input 
                      type="text" 
                      id="crmCompany" 
                      class="form-input" 
                      placeholder="e.g. Apex Global Logistics" 
                      value="${initialData.company_name || ''}" 
                      required 
                      style="font-size: 13.5px;"
                    />
                  </div>

                  <div>
                    <label for="crmWebsite" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      Website URL or Domain *
                    </label>
                    <input 
                      type="text" 
                      id="crmWebsite" 
                      class="form-input font-mono" 
                      placeholder="e.g. https://apexlogistics.io" 
                      value="${initialData.website || initialData.domain || ''}" 
                      required 
                      style="font-size: 13px;"
                    />
                  </div>
                </div>

                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 12px;">
                  <div>
                    <label for="crmIndustry" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      Industry / Sector
                    </label>
                    <input 
                      type="text" 
                      id="crmIndustry" 
                      class="form-input" 
                      list="crmIndustrySuggestions" 
                      placeholder="e.g. Supply Chain & Logistics" 
                      value="${initialData.industry || 'B2B Services'}"
                    />
                    <datalist id="crmIndustrySuggestions">
                      <option value="AI & Automation">
                      <option value="SaaS & Software">
                      <option value="Supply Chain & Logistics">
                      <option value="Healthcare & Pharma">
                      <option value="Financial Services">
                      <option value="Real Estate & Infrastructure">
                      <option value="Management Consulting">
                      <option value="Manufacturing & Industrial">
                      <option value="E-Commerce & Retail">
                      <option value="B2B Services">
                    </datalist>
                  </div>

                  <div>
                    <label for="crmLocation" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      Location / Headquarters
                    </label>
                    <input 
                      type="text" 
                      id="crmLocation" 
                      class="form-input" 
                      placeholder="e.g. Gurugram, Haryana" 
                      value="${initialData.location || 'India'}"
                    />
                  </div>

                  <div>
                    <label for="crmEmployees" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      Company Size
                    </label>
                    <select id="crmEmployees" class="form-input" style="font-size: 13px;">
                      <option value="1-10">1-10 employees</option>
                      <option value="11-50" selected>11-50 employees</option>
                      <option value="51-200">51-200 employees</option>
                      <option value="201-500">201-500 employees</option>
                      <option value="500+">500+ enterprise</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label for="crmDescription" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                    Company Summary / Context for AI Voice Agent
                  </label>
                  <textarea 
                    id="crmDescription" 
                    class="form-input" 
                    rows="2" 
                    placeholder="Briefly describe what this company does, their primary product/service, and business focus..." 
                    style="font-size: 12.5px; resize: vertical;"
                  >${initialData.description || ''}</textarea>
                </div>
              </div>

              <!-- SECTION 2: Decision Maker & Contacts -->
              <div style="margin-bottom: 22px; padding: 16px; background: var(--bg-surface-secondary); border-radius: 8px; border: 1px solid var(--border-color);">
                <div style="font-size: 13px; font-weight: 800; color: #581c87; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 12px; display: flex; align-items: center; gap: 6px;">
                  <i class="fa-solid fa-user-tie"></i>
                  <span>2. Key Decision Maker & Telecom Details</span>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 12px;">
                  <div>
                    <label for="crmContactName" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      Primary Contact Name
                    </label>
                    <input 
                      type="text" 
                      id="crmContactName" 
                      class="form-input" 
                      placeholder="e.g. Vikram Malhotra" 
                      value="${initialData.contact_name || ''}"
                    />
                  </div>

                  <div>
                    <label for="crmContactRole" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      Job Title / Role
                    </label>
                    <input 
                      type="text" 
                      id="crmContactRole" 
                      class="form-input" 
                      placeholder="e.g. Head of Operations / VP Sales" 
                      value="${initialData.contact_role || 'Director / Head'}"
                    />
                  </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 12px;">
                  <div>
                    <label for="crmPhone" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      <i class="fa-solid fa-phone" style="color: #16a34a; margin-right: 4px;"></i> Direct Phone (E.164) *
                    </label>
                    <input 
                      type="text" 
                      id="crmPhone" 
                      class="form-input font-mono" 
                      placeholder="e.g. +917082968702" 
                      value="${initialData.phone || initialData.phones?.[0] || '+917082968702'}" 
                      required 
                      style="font-size: 13.5px;"
                    />
                    <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">
                      Plivo PSTN compatible E.164 format (e.g. +91XXXXXXXXXX)
                    </div>
                  </div>

                  <div>
                    <label for="crmEmail" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      <i class="fa-solid fa-envelope" style="color: #6b21a8; margin-right: 4px;"></i> Work Email
                    </label>
                    <input 
                      type="email" 
                      id="crmEmail" 
                      class="form-input" 
                      placeholder="e.g. contact@apexlogistics.io" 
                      value="${initialData.email || initialData.emails?.[0] || ''}"
                    />
                  </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
                  <div>
                    <label for="crmLinkedIn" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      <i class="fa-brands fa-linkedin" style="color: #0284c7; margin-right: 4px;"></i> LinkedIn Profile
                    </label>
                    <input 
                      type="text" 
                      id="crmLinkedIn" 
                      class="form-input" 
                      placeholder="e.g. https://linkedin.com/in/prospect" 
                      value="${initialData.linkedin || ''}"
                    />
                  </div>

                  <div>
                    <label for="crmTechStack" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      Tech Stack (Optional)
                    </label>
                    <input 
                      type="text" 
                      id="crmTechStack" 
                      class="form-input" 
                      placeholder="e.g. Salesforce, SAP, AWS, React" 
                      value="${initialData.tech_stack?.join(', ') || ''}"
                    />
                  </div>
                </div>
              </div>

              <!-- SECTION 3: CRM Quality & AI Instructions -->
              <div>
                <div style="font-size: 13px; font-weight: 800; color: #581c87; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 12px; display: flex; align-items: center; gap: 6px;">
                  <i class="fa-solid fa-sliders"></i>
                  <span>3. CRM Quality Tier & Outbound Guidance</span>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 12px;">
                  <div>
                    <label for="crmLeadQuality" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      Lead Quality Tier
                    </label>
                    <select id="crmLeadQuality" class="form-input" style="font-size: 13px;">
                      <option value="Verified" selected>✓ Verified Lead (Recommended)</option>
                      <option value="High">★ High Quality</option>
                      <option value="Medium">● Standard / Medium</option>
                    </select>
                  </div>

                  <div>
                    <label for="crmLeadScore" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                      Initial CRM Score (0-100)
                    </label>
                    <input 
                      type="number" 
                      id="crmLeadScore" 
                      class="form-input font-mono" 
                      min="0" 
                      max="100" 
                      value="95" 
                      style="font-size: 13.5px;"
                    />
                  </div>
                </div>

                <div>
                  <label for="crmCustomScript" style="font-size: 12px; font-weight: 700; color: var(--text-primary); display: block; margin-bottom: 4px;">
                    Custom Call Prompt / Discussion Topics (Optional)
                  </label>
                  <textarea 
                    id="crmCustomScript" 
                    class="form-input" 
                    rows="2" 
                    placeholder="Special instructions for AI when calling this customer (e.g. Introduce as Sara from Flowiz. Ask about current lead response times and explore their interest in automated voice agent qualification.)." 
                    style="font-size: 12.5px; resize: vertical;"
                  ></textarea>
                </div>
              </div>

              <!-- Inline Error/Status Notice -->
              <div id="crmSubmitNotice" style="display: none; margin-top: 14px; padding: 10px 14px; border-radius: 6px; font-size: 12.5px;"></div>

            </form>

          </div>

          <!-- Modal Footer Actions -->
          <div style="padding: 16px 24px; border-top: 1px solid var(--border-color); background: #f8fafc; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
            <div style="font-size: 12px; color: var(--text-muted);">
              Data is synced immediately to <code class="font-mono" style="font-size: 11px;">flowiz_leads</code> SQLite and UI state.
            </div>

            <div style="display: flex; gap: 10px; align-items: center;">
              <button type="button" id="btnCancelCreateLead" class="btn btn-secondary">
                Cancel
              </button>

              <button type="button" id="btnSubmitCreateLead" class="btn btn-primary" style="background: #16a34a; border-color: #15803d; font-weight: 700;">
                <i class="fa-solid fa-check" style="margin-right: 6px;"></i>
                <span>Save Verified Lead</span>
              </button>

              <button type="button" id="btnSubmitAndCallLead" class="btn btn-primary" style="background: #6b21a8; border-color: #581c87; font-weight: 700;">
                <i class="fa-solid fa-phone-volume" style="margin-right: 6px;"></i>
                <span>Save & Dial Now</span>
              </button>
            </div>
          </div>

        </div>
      </div>
    `;

    this.attachEvents(modalContainer);
  }

  attachEvents(modalContainer) {
    const btnClose = modalContainer.querySelector('#btnCloseCreateLeadModal');
    const btnCancel = modalContainer.querySelector('#btnCancelCreateLead');
    const backdrop = modalContainer.querySelector('#crmModalBackdrop');

    const closeHandler = () => {
      this.isOpen = false;
      modalContainer.innerHTML = '';
    };

    if (btnClose) btnClose.addEventListener('click', closeHandler);
    if (btnCancel) btnCancel.addEventListener('click', closeHandler);
    if (backdrop) {
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) closeHandler();
      });
    }

    const btnSubmit = modalContainer.querySelector('#btnSubmitCreateLead');
    const btnSubmitAndCall = modalContainer.querySelector('#btnSubmitAndCallLead');

    if (btnSubmit) {
      btnSubmit.addEventListener('click', () => this.handleSave(modalContainer, false));
    }
    if (btnSubmitAndCall) {
      btnSubmitAndCall.addEventListener('click', () => this.handleSave(modalContainer, true));
    }
  }

  async handleSave(modalContainer, andCall = false) {
    const notice = modalContainer.querySelector('#crmSubmitNotice');
    const showNotice = (msg, isError = false) => {
      if (!notice) return;
      notice.style.display = 'block';
      notice.style.background = isError ? '#fef2f2' : '#ecfdf5';
      notice.style.color = isError ? '#991b1b' : '#065f46';
      notice.style.border = `1px solid ${isError ? '#fecaca' : '#a7f3d0'}`;
      notice.innerHTML = `<i class="fa-solid ${isError ? 'fa-triangle-exclamation' : 'fa-circle-check'}" style="margin-right: 6px;"></i>${msg}`;
    };

    const company = modalContainer.querySelector('#crmCompany')?.value.trim();
    const website = modalContainer.querySelector('#crmWebsite')?.value.trim();
    const phone = modalContainer.querySelector('#crmPhone')?.value.trim();

    if (!company) {
      showNotice('Please enter a Company Name.', true);
      modalContainer.querySelector('#crmCompany')?.focus();
      return;
    }

    if (!website) {
      showNotice('Please enter a Website URL or Domain name.', true);
      modalContainer.querySelector('#crmWebsite')?.focus();
      return;
    }

    if (!phone) {
      showNotice('Please provide a callable phone number in E.164 format (+91XXXXXXXXXX).', true);
      modalContainer.querySelector('#crmPhone')?.focus();
      return;
    }

    const industry = modalContainer.querySelector('#crmIndustry')?.value.trim() || 'B2B Services';
    const location = modalContainer.querySelector('#crmLocation')?.value.trim() || 'India';
    const employees = modalContainer.querySelector('#crmEmployees')?.value || '11-50';
    const description = modalContainer.querySelector('#crmDescription')?.value.trim() || '';
    const contactName = modalContainer.querySelector('#crmContactName')?.value.trim() || '';
    const contactRole = modalContainer.querySelector('#crmContactRole')?.value.trim() || '';
    const contactEmail = modalContainer.querySelector('#crmEmail')?.value.trim() || '';
    const contactLinkedIn = modalContainer.querySelector('#crmLinkedIn')?.value.trim() || '';
    const techStackRaw = modalContainer.querySelector('#crmTechStack')?.value.trim() || '';
    const leadQuality = modalContainer.querySelector('#crmLeadQuality')?.value || 'Verified';
    const leadScore = parseInt(modalContainer.querySelector('#crmLeadScore')?.value || '95', 10);
    const customScript = modalContainer.querySelector('#crmCustomScript')?.value.trim() || '';

    const techStack = techStackRaw ? techStackRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
    const phones = [phone];
    const emails = contactEmail ? [contactEmail] : [];

    const payload = {
      company_name: company,
      website: website,
      industry: industry,
      location: location,
      employees: employees,
      description: description,
      contact_name: contactName,
      contact_role: contactRole,
      contact_email: contactEmail,
      contact_phone: phone,
      contact_linkedin: contactLinkedIn,
      phones: phones,
      emails: emails,
      lead_quality: leadQuality,
      lead_score: isNaN(leadScore) ? 90 : leadScore,
      tech_stack: techStack,
      notes: customScript,
      keyword: 'crm_manual'
    };

    const btnSubmit = modalContainer.querySelector('#btnSubmitCreateLead');
    const btnSubmitAndCall = modalContainer.querySelector('#btnSubmitAndCallLead');

    try {
      if (btnSubmit) btnSubmit.disabled = true;
      if (btnSubmitAndCall) btnSubmitAndCall.disabled = true;
      showNotice('Saving and verifying lead in database...', false);

      const res = await window.api.createLead(payload);
      if (!res || res.status !== 'success' || !res.lead) {
        throw new Error(res?.detail || res?.message || 'Server rejected lead creation.');
      }

      const createdLead = res.lead;

      // Reactively inject into frontend state
      window.store.addLead(createdLead);

      showNotice(`✓ "${createdLead.company_name}" successfully saved and verified!`, false);

      setTimeout(() => {
        modalContainer.innerHTML = '';
        this.isOpen = false;

        if (andCall) {
          // Open Live Voice Agent Console with this lead pre-selected
          window.location.hash = 'liveAgent';
          setTimeout(() => {
            const txtPhone = document.querySelector('#txtManualPhone');
            const txtCustName = document.querySelector('#txtCustomerName');
            const txtCustCtx = document.querySelector('#txtCustomerContext');
            const txtPrompt = document.querySelector('#txtCallPrompt');
            if (txtPhone) txtPhone.value = phone;
            if (txtCustName) txtCustName.value = createdLead.company_name;
            if (txtCustCtx) txtCustCtx.value = createdLead.description || `${createdLead.industry} prospect`;
            if (txtPrompt && customScript) txtPrompt.value = customScript;
          }, 200);
        } else {
          // Open the Lead Dossier view for the new lead
          if (window.app && window.app.leadDetailView) {
            window.app.leadDetailView.show(createdLead);
          }
        }
      }, 700);

    } catch (err) {
      showNotice(`Error saving lead: ${err.message || err}`, true);
      if (btnSubmit) btnSubmit.disabled = false;
      if (btnSubmitAndCall) btnSubmitAndCall.disabled = false;
    }
  }
}

window.LeadCreateModal = LeadCreateModal;
