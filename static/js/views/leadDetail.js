/**
 * Lead Intelligence — Lead Detail Dossier & Qualification Dispatch View
 * Team A → Team B Core Integration Bridge
 * Features:
 * 1. Rich Company, Contact & Technology dossier
 * 2. Pre-Call Confirmation Dialog with real lead context
 * 3. End-to-End Traceability (lead_id -> dispatch_id -> session_id -> call_uuid)
 * 4. Real-time call progress & live Qualification Result write-back
 */

class LeadDetailView {
  show(lead, options = {}) {
    const modalContainer = document.getElementById('modalContainer');
    if (!modalContainer || !lead) return;

    window.store.setSelectedLead(lead);

    const hasPhones = Array.isArray(lead.phones) && lead.phones.length > 0;
    const primaryPhone = hasPhones ? lead.phones[0] : (Array.isArray(lead.verified_phones) && lead.verified_phones.length > 0 ? lead.verified_phones[0] : null);
    const hasEmails = Array.isArray(lead.emails) && lead.emails.length > 0;
    const primaryContact = (Array.isArray(lead.people) && lead.people.length > 0) ? lead.people[0] : null;

    const qualStatus = (lead.qualification_status || lead.call_status || 'unqualified').toLowerCase();
    const qualScore = lead.qualification_score;

    modalContainer.innerHTML = `
      <div class="modal-backdrop" id="drawerBackdrop" style="position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); backdrop-filter: blur(4px); z-index: 90; display: flex; justify-content: flex-end;">
        <div class="drawer" style="width: 580px; max-width: 90vw; background: #ffffff; height: 100vh; overflow-y: auto; padding: 32px; box-shadow: var(--shadow-lg); border-left: 1px solid var(--border-color); display: flex; flex-direction: column;">
          
          <!-- Drawer Header -->
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid var(--border-color);">
            <div>
              <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 8px;">
                <span class="badge ${lead.lead_quality === 'High' ? 'badge-success' : 'badge-neutral'}">
                  ${lead.lead_quality || 'Verified'} Lead
                </span>
                <span class="badge badge-info">${lead.industry || 'B2B'}</span>
              </div>
              <h2 style="margin: 0 0 4px 0; font-size: 22px; font-weight: 800; color: var(--text-primary);">${lead.company_name || 'Lead Dossier'}</h2>
              <div class="font-mono text-muted" style="font-size: 13px;">
                <i class="fa-solid fa-globe" style="margin-right: 4px;"></i>${lead.domain || lead.website || 'No domain'}
              </div>
            </div>
            <button id="btnCloseDrawer" class="btn btn-secondary btn-sm" style="padding: 6px 12px; font-size: 14px;" title="Close Dossier">✕</button>
          </div>

          <div style="flex: 1; display: flex; flex-direction: column; gap: 20px;">
            
            <!-- AI QUALIFICATION HERO CTA & STATUS (TEAM A -> TEAM B) -->
            <div class="card" style="padding: 20px; border: 1px solid rgba(99, 102, 241, 0.3); background: linear-gradient(180deg, #f5f3ff 0%, #ffffff 100%);">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div style="font-weight: 700; font-size: 13px; text-transform: uppercase; color: #5b21b6; display: flex; align-items: center; gap: 8px;">
                  <i class="fa-solid fa-robot"></i> AI Voice Agent Qualification
                </div>
                <span class="badge ${
                  qualStatus === 'qualified' ? 'badge-success' :
                  (qualStatus === 'in_progress' || qualStatus === 'initiated' || qualStatus === 'ringing' ? 'badge-warning' :
                  (qualStatus === 'failed' || qualStatus === 'disqualified' ? 'badge-danger' : 'badge-neutral'))
                }" id="detailQualBadge">
                  ${qualStatus === 'qualified' ? '✓ Qualified' :
                    (qualStatus === 'in_progress' || qualStatus === 'initiated' ? '● In Progress' :
                    (qualStatus === 'failed' || qualStatus === 'disqualified' ? '✕ Disqualified' : 'Unqualified'))}
                </span>
              </div>

              <!-- Dispatch Notice Box -->
              <div id="detailDispatchNotice" style="display: none; margin-bottom: 12px; font-size: 12.5px; padding: 10px 12px; border-radius: 6px; line-height: 1.4;"></div>

              <!-- Qualification CTA Button -->
              ${primaryPhone ? `
                <div style="display: flex; flex-direction: column; gap: 8px;">
                  <button id="btnOpenCallConfirm" class="btn btn-primary" style="width: 100%; justify-content: center; gap: 10px; background: #6b21a8; border-color: #581c87; padding: 12px;">
                    <i class="fa-solid fa-phone-volume"></i>
                    <span>Qualify with AI Voice Agent (Plivo)</span>
                  </button>
                  <div style="font-size: 11.5px; color: var(--text-muted); text-align: center;">
                    Dials <strong>${primaryPhone}</strong> with personalized prospect context via Plivo
                  </div>
                </div>
              ` : `
                <div style="padding: 12px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; color: #991b1b; font-size: 12px; display: flex; align-items: center; gap: 8px;">
                  <i class="fa-solid fa-circle-exclamation"></i>
                  <span>Cannot trigger automated call: No callable phone recorded for this prospect.</span>
                </div>
              `}

              <!-- Traceability Panel (when active call exists) -->
              <div id="detailTraceabilityPanel" style="margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(99, 102, 241, 0.2); font-size: 11.5px; color: var(--text-muted); ${lead.session_id || (window.store.activeCall && window.store.activeCall.lead_id === (lead.domain || lead.website)) ? 'display: block;' : 'display: none;'}">
                <div style="font-weight: 700; color: #4338ca; margin-bottom: 6px; text-transform: uppercase; font-size: 10px; letter-spacing: 0.05em;">
                  Telecom Traceability
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;" class="font-mono">
                  <div><strong>Lead ID:</strong> <span id="traceLeadId">${lead.domain || lead.website}</span></div>
                  <div><strong>Session ID:</strong> <span id="traceSessionId">${lead.session_id || '—'}</span></div>
                  <div><strong>Provider:</strong> <span>Plivo PSTN</span></div>
                  <div><strong>Call UUID:</strong> <span id="traceCallId">${lead.provider_call_id || '—'}</span></div>
                </div>
                <div style="margin-top: 10px;">
                  <a href="#liveAgent" class="btn btn-secondary btn-sm" style="width: 100%; justify-content: center; font-size: 11px;">
                    <i class="fa-solid fa-headset"></i> View Live Agent Console
                  </a>
                </div>
              </div>
            </div>

            <!-- Qualification Result Dossier (if qualified or evaluated) -->
            ${(lead.conversation_summary || (qualScore !== undefined && qualScore !== null && qualScore > 0)) ? `
              <div class="card" style="padding: 18px; border: 1px solid #bbf7d0; background: #f0fdf4;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                  <div style="font-weight: 700; font-size: 13px; color: #166534; text-transform: uppercase;">
                    <i class="fa-solid fa-clipboard-check"></i> Qualification Result
                  </div>
                  ${qualScore ? `<span class="badge badge-success" style="font-size: 12px;">Score: ${qualScore}/100</span>` : ''}
                </div>

                <div style="font-size: 12.5px; color: #14532d; line-height: 1.5; margin-bottom: 10px;">
                  <strong>AI Conversation Summary:</strong>
                  <div style="margin-top: 4px; background: #ffffff; padding: 10px; border-radius: 6px; border: 1px solid #dcfce7;">
                    ${lead.conversation_summary}
                  </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 11.5px; color: #166534;">
                  <div><strong>Interest Level:</strong> ${lead.interest_level || 'Moderate'}</div>
                  <div><strong>Budget:</strong> ${lead.budget || 'Not specified'}</div>
                  <div><strong>Timeline:</strong> ${lead.timeline || 'Standard'}</div>
                  <div><strong>Pain Points:</strong> ${lead.pain_points || 'Neutral'}</div>
                </div>
              </div>
            ` : ''}

            <!-- Contact Vectors -->
            <div class="card" style="padding: 18px;">
              <div style="font-weight: 700; font-size: 12px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 12px;">
                Verified Contacts
              </div>

              <!-- Primary Person -->
              ${primaryContact ? `
                <div style="margin-bottom: 12px; padding: 10px; background: var(--bg-surface-secondary); border-radius: 6px;">
                  <div style="font-weight: 700; font-size: 13.5px; color: var(--text-primary);">${primaryContact.name}</div>
                  <div style="font-size: 12px; color: var(--text-muted);">${primaryContact.designation || 'Decision Maker'}</div>
                </div>
              ` : ''}

              <!-- Phone Numbers -->
              <div style="margin-bottom: 12px;">
                <div style="font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px;">Phone Numbers:</div>
                ${hasPhones ? lead.phones.map(p => `
                  <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 6px;">
                    <a href="tel:${p}" class="btn-phone-dialer" title="Dial using native device phone app">
                      <i class="fa-solid fa-phone"></i>
                      <span>Call ${p}</span>
                    </a>
                  </div>
                `).join('') : '<div style="font-size: 12px; color: var(--text-muted);">No phone recorded</div>'}
              </div>

              <!-- Emails -->
              <div>
                <div style="font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px;">Emails:</div>
                ${hasEmails ? lead.emails.map(e => `
                  <div class="font-mono" style="font-size: 12.5px; color: var(--text-primary); display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                    <i class="fa-solid fa-envelope text-accent"></i> ${e}
                  </div>
                `).join('') : '<div style="font-size: 12px; color: var(--text-muted);">No email recorded</div>'}
              </div>
            </div>

            <!-- Company Overview -->
            <div class="card" style="padding: 18px;">
              <div style="font-weight: 700; font-size: 12px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 8px;">
                Company Dossier
              </div>
              <div style="font-size: 13px; color: var(--text-secondary); line-height: 1.5;">
                ${lead.description || 'No long-form description available for this lead.'}
              </div>
              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 14px; font-size: 12px; color: var(--text-muted);">
                <div><strong>Industry:</strong> ${lead.industry || 'B2B'}</div>
                <div><strong>Location:</strong> ${lead.location || 'Unknown'}</div>
                <div><strong>Company Type:</strong> ${lead.company_type || 'Private'}</div>
                <div><strong>Source:</strong> <span>OSINT Crawl</span></div>
              </div>
            </div>

            <!-- Tech Stack Detection -->
            <div class="card" style="padding: 18px;">
              <div style="font-weight: 700; font-size: 12px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 10px;">
                Detected Tech Stack
              </div>
              <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                ${Array.isArray(lead.tech_stack) && lead.tech_stack.length > 0 ? lead.tech_stack.map(t => `
                  <span class="badge badge-info">${t}</span>
                `).join('') : '<div style="font-size: 12px; color: var(--text-muted);">No tech stack detected</div>'}
              </div>
            </div>

          </div>

        </div>
      </div>

      <!-- Pre-Call Confirmation Modal Container -->
      <div id="callConfirmModalContainer"></div>
    `;

    this.attachEvents(modalContainer, lead);

    if (options.autoTriggerConfirm && primaryPhone) {
      this.showCallConfirmation(modalContainer, lead, primaryPhone, primaryContact);
    }
  }

  attachEvents(modalContainer, lead) {
    const btnClose = modalContainer.querySelector('#btnCloseDrawer');
    if (btnClose) {
      btnClose.addEventListener('click', () => {
        modalContainer.innerHTML = '';
      });
    }

    const backdrop = modalContainer.querySelector('#drawerBackdrop');
    if (backdrop) {
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) {
          modalContainer.innerHTML = '';
        }
      });
    }

    const btnOpenConfirm = modalContainer.querySelector('#btnOpenCallConfirm');
    if (btnOpenConfirm) {
      btnOpenConfirm.addEventListener('click', () => {
        const phone = Array.isArray(lead.phones) && lead.phones.length > 0 ? lead.phones[0] : null;
        const person = (Array.isArray(lead.people) && lead.people.length > 0) ? lead.people[0] : null;
        if (!phone) {
          alert('No callable phone number recorded.');
          return;
        }
        this.showCallConfirmation(modalContainer, lead, phone, person);
      });
    }
  }

  showCallConfirmation(modalContainer, lead, phone, person) {
    const confirmContainer = modalContainer.querySelector('#callConfirmModalContainer');
    if (!confirmContainer) return;

    confirmContainer.innerHTML = `
      <div class="modal-backdrop" id="confirmBackdrop" style="position: fixed; inset: 0; background: rgba(15, 23, 42, 0.6); backdrop-filter: blur(4px); z-index: 100; display: flex; align-items: center; justify-content: center; padding: 20px;">
        <div class="card" style="width: 480px; max-width: 100%; padding: 28px; box-shadow: var(--shadow-xl); border: 1px solid var(--border-color); background: #ffffff;">
          
          <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px;">
            <div style="width: 40px; height: 40px; border-radius: 8px; background: rgba(107, 33, 168, 0.1); color: #6b21a8; display: flex; align-items: center; justify-content: center; font-size: 18px;">
              <i class="fa-solid fa-phone-volume"></i>
            </div>
            <div>
              <h3 style="margin: 0; font-size: 17px; font-weight: 800; color: var(--text-primary);">Start AI Qualification Call?</h3>
              <div style="font-size: 12px; color: var(--text-muted);">Outbound telecom qualification via Plivo</div>
            </div>
          </div>

          <div style="background: var(--bg-surface-secondary); padding: 14px; border-radius: 8px; border: 1px solid var(--border-color); margin-bottom: 16px; font-size: 13px;">
            <div style="margin-bottom: 6px;"><strong>Company:</strong> ${lead.company_name || 'Prospect'}</div>
            <div style="margin-bottom: 6px;"><strong>Contact:</strong> ${person && person.name ? person.name : 'Primary Representative'}</div>
            <div style="margin-bottom: 6px;"><strong>Phone:</strong> <span class="font-mono" style="font-weight: 700; color: #4338ca;">${phone}</span></div>
            <div><strong>Industry:</strong> ${lead.industry || 'B2B'}</div>
          </div>

          <!-- Call-Specific AI Agent Prompt / Call Script (Optional) -->
          <div style="margin-bottom: 16px;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
              <label for="callPromptInput" style="font-size: 12.5px; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-scroll" style="color: #6b21a8;"></i>
                <span>Call Script & Instructions (Optional)</span>
              </label>
              <div style="display: flex; align-items: center; gap: 8px;">
                <span id="callPromptCharCount" style="font-size: 11px; color: var(--text-muted); font-family: monospace;">0 / 2500</span>
                <button type="button" id="btnClearPrompt" class="btn btn-sm btn-ghost" style="padding: 2px 6px; font-size: 11px; color: var(--text-muted);" title="Clear custom script">Clear</button>
              </div>
            </div>
            
            <div style="margin-bottom: 6px;">
              <select id="callPromptTemplate" class="form-control" style="font-size: 12px; padding: 5px 8px; border-radius: 6px; width: 100%; border: 1px solid var(--border-color); background: #ffffff;">
                <option value="">-- Choose Script Template (Optional) --</option>
                <option value="b2b_discovery">Standard B2B Discovery & Qualification</option>
                <option value="ai_automation">AI Voice Automation Pitch</option>
                <option value="executive_followup">Executive Follow-Up & Availability Check</option>
              </select>
            </div>

            <textarea id="callPromptInput" maxlength="2500" rows="4" class="form-control" style="width: 100%; font-size: 12.5px; line-height: 1.4; padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border-color); resize: vertical; font-family: inherit;" placeholder="Enter custom call instructions or script for the AI agent (e.g., Introduce yourself as Sara from Flowiz. Inquire about their current outbound lead qualification process and biggest bottlenecks. If interested, propose a 15-minute product walkthrough. Be warm and concise.)."></textarea>

            <div style="font-size: 11px; color: var(--text-muted); line-height: 1.35; margin-top: 5px; display: flex; align-items: flex-start; gap: 5px;">
              <i class="fa-solid fa-shield-halved" style="color: #6b21a8; margin-top: 2px;"></i>
              <span><strong>Call Scoped:</strong> Applies to this call only. Core safety, phone validation, and call completion controls remain active.</span>
            </div>
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 10px;">
            <button class="btn btn-secondary" id="btnCancelConfirm">Cancel</button>
            <button class="btn btn-primary" id="btnExecuteDispatch" style="background: #6b21a8; border-color: #581c87;">
              <i class="fa-solid fa-phone"></i>
              <span>Confirm & Start Call</span>
            </button>
          </div>

        </div>
      </div>
    `;

    // Templates Definition
    const SCRIPT_TEMPLATES = {
      b2b_discovery: "Introduce yourself as Sara from Flowiz and Cybernauts. Personalize the conversation with the prospect's company and industry. Ask how they currently handle lead qualification and customer follow-ups. Inquire about their biggest operational bottlenecks. If they show interest, briefly explain our automated workflows and ask if they are open to a brief follow-up discussion. Do not be pushy.",
      ai_automation: "This call is for introducing our Voice AI Telephony agents to automate outbound customer reach and qualification. Ask the prospect if their sales team currently faces high call volume or manual dialer delays. Explain how our voice agents achieve zero-latency natural conversations in English and Hindi. If interested, ask for the best contact person and timeline for a live demonstration.",
      executive_followup: "Follow up with the prospect regarding our previous discussion on enterprise automation. Inquire if they have reviewed our technical capabilities and if they have any specific questions regarding integration or pricing. If they are ready, offer to schedule a technical alignment call with our engineering leads."
    };

    const promptTextarea = confirmContainer.querySelector('#callPromptInput');
    const charCountEl = confirmContainer.querySelector('#callPromptCharCount');
    const templateSelect = confirmContainer.querySelector('#callPromptTemplate');
    const btnClearPrompt = confirmContainer.querySelector('#btnClearPrompt');

    if (promptTextarea && charCountEl) {
      promptTextarea.addEventListener('input', () => {
        charCountEl.textContent = `${promptTextarea.value.length} / 2500`;
      });
    }

    if (templateSelect && promptTextarea) {
      templateSelect.addEventListener('change', () => {
        const selected = templateSelect.value;
        if (selected && SCRIPT_TEMPLATES[selected]) {
          promptTextarea.value = SCRIPT_TEMPLATES[selected];
          if (charCountEl) charCountEl.textContent = `${promptTextarea.value.length} / 2500`;
        }
      });
    }

    if (btnClearPrompt && promptTextarea) {
      btnClearPrompt.addEventListener('click', () => {
        promptTextarea.value = '';
        if (templateSelect) templateSelect.value = '';
        if (charCountEl) charCountEl.textContent = '0 / 2500';
      });
    }

    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        confirmContainer.innerHTML = '';
        document.removeEventListener('keydown', handleEscape);
      }
    };
    document.addEventListener('keydown', handleEscape);

    const btnCancel = confirmContainer.querySelector('#btnCancelConfirm');
    if (btnCancel) {
      btnCancel.addEventListener('click', () => {
        confirmContainer.innerHTML = '';
        document.removeEventListener('keydown', handleEscape);
      });
    }

    const btnExecute = confirmContainer.querySelector('#btnExecuteDispatch');
    if (btnExecute) {
      btnExecute.addEventListener('click', async () => {
        document.removeEventListener('keydown', handleEscape);
        const customPrompt = promptTextarea ? promptTextarea.value.trim() : '';
        confirmContainer.innerHTML = '';
        await this.executeDispatch(modalContainer, lead, phone, customPrompt ? { call_prompt: customPrompt } : {});
      });
    }
  }

  async executeDispatch(modalContainer, lead, phone, promptData = {}) {
    const qualNotice = modalContainer.querySelector('#detailDispatchNotice');
    const qualBadge = modalContainer.querySelector('#detailQualBadge');
    const tracePanel = modalContainer.querySelector('#detailTraceabilityPanel');
    const traceSessionId = modalContainer.querySelector('#traceSessionId');
    const traceCallId = modalContainer.querySelector('#traceCallId');

    try {
      if (qualNotice) {
        qualNotice.style.display = 'block';
        qualNotice.style.background = '#e0e7ff';
        qualNotice.style.color = '#3730a3';
        qualNotice.innerHTML = `
          <div style="display: flex; align-items: center; gap: 8px;">
            <i class="fa-solid fa-circle-notch fa-spin"></i>
            <span>Initiating Plivo outbound call to <strong>${phone}</strong>...</span>
          </div>
        `;
      }

      const identifier = lead.domain || lead.website || lead.id;
      const dispatchPayload = { phoneNumber: phone, force: true, ...promptData };
      const res = await window.api.dispatchLeadQualification(identifier, dispatchPayload);

      if (res && (res.status === 'success' || res.status === 'in_progress')) {
        const dispatchId = res.dispatch_id || '';
        const sessionId = res.session_id || '';
        const callUuid = res.provider_call_id || '';

        // Update activeCall in state
        window.store.setActiveCall({
          lead_id: lead.domain || lead.website,
          dispatch_id: dispatchId,
          session_id: sessionId,
          call_uuid: callUuid,
          company_name: lead.company_name,
          phone: phone,
          call_status: 'initiated',
          started_at: new Date().toISOString(),
          has_custom_prompt: Boolean(promptData.call_prompt),
          prompt_len: (promptData.call_prompt || '').length,
        });

        // Update Lead status locally
        window.store.updateLeadQualification(lead.domain || lead.website, {
          call_status: 'initiated',
          qualification_status: 'in_progress',
          provider_call_id: callUuid,
          session_id: sessionId
        });

        if (qualNotice) {
          qualNotice.style.background = '#dcfce7';
          qualNotice.style.color = '#15803d';
          qualNotice.innerHTML = `
            <strong>Call Initiated!</strong> Dialing ${phone} via Plivo.<br>
            <span class="font-mono" style="font-size: 11px;">Call ID: ${callUuid}</span>
          `;
        }

        if (qualBadge) {
          qualBadge.className = 'badge badge-warning';
          qualBadge.innerText = '● In Progress';
        }

        if (tracePanel) {
          tracePanel.style.display = 'block';
          if (traceSessionId) traceSessionId.innerText = sessionId || '—';
          if (traceCallId) traceCallId.innerText = callUuid || '—';
        }
      }
    } catch (err) {
      if (qualNotice) {
        qualNotice.style.display = 'block';
        qualNotice.style.background = '#fee2e2';
        qualNotice.style.color = '#b91c1c';
        qualNotice.innerHTML = `
          <strong>Call Dispatch Failed:</strong> ${err.message || err}
        `;
      }
    }
  }
}

window.LeadDetailView = LeadDetailView;
