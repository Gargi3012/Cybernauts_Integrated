/**
 * Lead Intelligence — Discover Leads View
 * Team A OSINT Discovery Engine
 * Multi-criteria search input with live stage-by-stage crawling progression
 */

class DiscoverView {
  render(container) {
    const pState = window.store.pipelineState || {};
    const isRunning = pState.status === 'running';
    const isCompleted = pState.status === 'completed';
    const isError = pState.status === 'error';
    const showStatus = isRunning || isCompleted || isError;

    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h1 style="font-size: 22px; font-weight: 800; margin: 0 0 6px 0; color: var(--text-primary);">Discover New Leads</h1>
        <div style="color: var(--text-muted); font-size: 13.5px;">
          Find and extract verified B2B companies, decision-makers, and contact vectors matching your target criteria.
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 24px;">
        
        <!-- Left: Search Form & Stage Monitor -->
        <div class="card" style="padding: 28px;">
          <h2 style="font-size: 16px; font-weight: 700; margin: 0 0 16px 0; color: var(--text-primary);">Search Criteria</h2>
          
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;">
            <div>
              <label style="display: block; font-weight: 600; font-size: 13px; margin-bottom: 6px; color: var(--text-secondary);">Target Industry</label>
              <input 
                type="text" 
                id="txtIndustry" 
                class="form-input" 
                placeholder="e.g. AI SaaS, Fintech, Healthcare"
                value="AI Technology"
              />
            </div>
            <div>
              <label style="display: block; font-weight: 600; font-size: 13px; margin-bottom: 6px; color: var(--text-secondary);">Location / Geography</label>
              <input 
                type="text" 
                id="txtLocation" 
                class="form-input" 
                placeholder="e.g. India, United States, Delhi"
                value="India"
              />
            </div>
          </div>

          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px;">
            <div>
              <label style="display: block; font-weight: 600; font-size: 13px; margin-bottom: 6px; color: var(--text-secondary);">Keywords & Offerings</label>
              <input 
                type="text" 
                id="txtKeywords" 
                class="form-input" 
                placeholder="e.g. Enterprise software, Mobile apps, Cloud"
                value="Software Development"
              />
            </div>
            <div>
              <label style="display: block; font-weight: 600; font-size: 13px; margin-bottom: 6px; color: var(--text-secondary);">Company Size (Optional)</label>
              <select id="selCompanySize" class="form-input">
                <option value="">Any Size</option>
                <option value="1-50">1 - 50 Employees (Early Stage)</option>
                <option value="50-250">50 - 250 Employees (Growth)</option>
                <option value="250+">250+ Employees (Enterprise)</option>
              </select>
            </div>
          </div>

          <div style="display: flex; gap: 12px; align-items: center;">
            <button id="btnStartPipeline" class="btn btn-primary" style="padding: 10px 22px;" ${isRunning ? 'disabled' : ''}>
              <i class="fa-solid fa-wand-magic-sparkles"></i>
              <span id="btnStartPipelineText">${isRunning ? 'Discovery In Progress...' : 'Start Discovery'}</span>
            </button>
            <div id="discoverHint" style="font-size: 12px; color: var(--text-muted);">
              Runs autonomous search, web scraping, email extraction, and enrichment.
            </div>
          </div>

          <!-- Real-Time Progress Box -->
          <div id="discoverStatusBox" style="margin-top: 24px; padding: 20px; border-radius: 8px; border: 1px solid var(--border-color); background: var(--bg-surface-secondary); display: ${showStatus ? 'block' : 'none'};">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="status-indicator" style="background: ${isError ? '#ef4444' : isCompleted ? '#10b981' : '#3b82f6'};"></span>
                <span id="lblDiscoverStage" style="font-weight: 700; font-size: 14px; color: var(--text-primary);">
                  ${pState.stage || 'Ready'}
                </span>
              </div>
              <div id="lblDiscoverPct" class="font-mono" style="font-weight: 700; font-size: 14px; color: var(--color-primary);">
                ${pState.progress_pct || 0}%
              </div>
            </div>

            <!-- Progress Bar -->
            <div style="height: 6px; background: #e2e8f0; border-radius: 999px; overflow: hidden; margin-bottom: 16px;">
              <div id="barDiscoverProgress" style="height: 100%; width: ${pState.progress_pct || 0}%; background: ${isError ? '#ef4444' : 'var(--color-primary)'}; transition: width 0.3s ease;"></div>
            </div>

            <!-- Live Metrics Counter -->
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; text-align: center;">
              <div style="background: #ffffff; padding: 10px; border-radius: 6px; border: 1px solid var(--border-color);">
                <div style="font-size: 10.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Companies Found</div>
                <div id="lblFoundCount" style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin-top: 2px;">
                  ${pState.companies_found || 0}
                </div>
              </div>
              <div style="background: #ffffff; padding: 10px; border-radius: 6px; border: 1px solid var(--border-color);">
                <div style="font-size: 10.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Leads Generated</div>
                <div id="lblLeadsCount" style="font-size: 18px; font-weight: 700; color: #16a34a; margin-top: 2px;">
                  ${pState.leads_generated || 0}
                </div>
              </div>
              <div style="background: #ffffff; padding: 10px; border-radius: 6px; border: 1px solid var(--border-color);">
                <div style="font-size: 10.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Elapsed Time</div>
                <div id="lblElapsedSec" style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin-top: 2px;">
                  ${pState.elapsed_sec || 0}s
                </div>
              </div>
            </div>

            <!-- Completion Banner -->
            <div id="discoverCompletionBanner" style="display: ${(isCompleted || isError) ? 'block' : 'none'}; margin-top: 16px; padding: 14px; background: ${isError ? '#fef2f2' : (pState.leads_generated || 0) > 0 ? '#ecfdf5' : '#fefce8'}; border: 1px solid ${isError ? '#fecaca' : (pState.leads_generated || 0) > 0 ? '#a7f3d0' : '#fef08a'}; border-radius: 6px; text-align: center;">
              <div style="font-weight: 700; color: ${isError ? '#991b1b' : (pState.leads_generated || 0) > 0 ? '#065f46' : '#854d0e'}; font-size: 14px; margin-bottom: 4px;" id="lblCompletionMsg">
                ${isError ? 'Discovery failed' : (pState.leads_generated || 0) > 0 ? 'Discovery completed!' : 'No matching companies found'}
              </div>
              <div style="font-size: 12.5px; color: ${isError ? '#b91c1c' : (pState.leads_generated || 0) > 0 ? '#047857' : '#a16207'}; margin-bottom: 10px;" id="lblCompletionCount">
                ${isError ? (pState.error_message || pState.stage || 'An error occurred during discovery.') : (pState.leads_generated || 0) > 0 ? `${pState.leads_generated} leads successfully discovered and saved.` : 'No matching companies were found for these criteria. Try broader keywords or alternative locations.'}
              </div>
              <button class="btn btn-primary" id="btnViewDiscoveredLeads" style="display: ${isCompleted && (pState.leads_generated || 0) > 0 ? 'inline-flex' : 'none'};">
                <i class="fa-solid fa-address-book"></i>
                <span>View Discovered Leads</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Right: Pipeline Architecture Info -->
        <div style="display: flex; flex-direction: column; gap: 16px;">
          <div class="card" style="padding: 20px;">
            <h3 style="font-size: 14px; font-weight: 700; margin: 0 0 12px 0;">Discovery Stages</h3>
            <div style="display: flex; flex-direction: column; gap: 12px; font-size: 12.5px;">
              <div style="display: flex; gap: 10px;">
                <span class="badge badge-info" style="align-self: flex-start;">P1</span>
                <div>
                  <strong>Target Search Querying</strong>
                  <div class="text-muted" style="font-size: 11.5px;">Synthesizes high-intent search operators across Google & Playwright.</div>
                </div>
              </div>
              <div style="display: flex; gap: 10px;">
                <span class="badge badge-info" style="align-self: flex-start;">P2</span>
                <div>
                  <strong>Multi-Worker Web Scraping</strong>
                  <div class="text-muted" style="font-size: 11.5px;">Crawls homepage, contact, about, and team pages concurrently.</div>
                </div>
              </div>
              <div style="display: flex; gap: 10px;">
                <span class="badge badge-info" style="align-self: flex-start;">P3</span>
                <div>
                  <strong>Entity Extraction & Verification</strong>
                  <div class="text-muted" style="font-size: 11.5px;">Extracts decision-makers, phones, tech stack, and verifies emails.</div>
                </div>
              </div>
              <div style="display: flex; gap: 10px;">
                <span class="badge badge-info" style="align-self: flex-start;">P4</span>
                <div>
                  <strong>Canonical Database Persistence</strong>
                  <div class="text-muted" style="font-size: 11.5px;">Persists normalized records into SQLite ready for AI qualification.</div>
                </div>
              </div>
            </div>
          </div>
        </div>

      </div>
    `;

    this.attachEvents(container);

    // Sync latest status from server on mount
    if (window.api && window.api.getPipelineStatus) {
      window.api.getPipelineStatus().then(status => {
        if (status && status.status !== 'idle') {
          window.store.setPipelineState(status);
          this.updateUIWithStatus(container, status);
          if (status.status === 'running') {
            this.pollProgress(container);
          }
        }
      }).catch(err => console.warn('Pipeline status check:', err));
    }
  }

  attachEvents(container) {
    const btnStart = container.querySelector('#btnStartPipeline');
    const txtIndustry = container.querySelector('#txtIndustry');
    const txtLocation = container.querySelector('#txtLocation');
    const txtKeywords = container.querySelector('#txtKeywords');
    const statusBox = container.querySelector('#discoverStatusBox');

    if (btnStart) {
      btnStart.addEventListener('click', async () => {
        const ind = (txtIndustry ? txtIndustry.value.trim() : '');
        const loc = (txtLocation ? txtLocation.value.trim() : '');
        const kw = (txtKeywords ? txtKeywords.value.trim() : '');

        const parts = [ind, loc, kw].filter(Boolean);
        const query = parts.length > 0 ? parts.join(', ') : 'AI Technology companies';

        try {
          btnStart.disabled = true;
          const btnText = container.querySelector('#btnStartPipelineText');
          if (btnText) btnText.innerText = 'Starting Discovery...';
          if (statusBox) statusBox.style.display = 'block';

          await window.api.searchLeads(query);
          window.store.setPipelineState({ status: 'running', keyword: query, progress_pct: 5, stage: 'Searching targets' });
          this.pollProgress(container);
        } catch (err) {
          alert('Failed to start discovery: ' + (err.message || err));
          btnStart.disabled = false;
          const btnText = container.querySelector('#btnStartPipelineText');
          if (btnText) btnText.innerText = 'Start Discovery';
        }
      });
    }

    const btnViewLeads = container.querySelector('#btnViewDiscoveredLeads');
    if (btnViewLeads) {
      btnViewLeads.addEventListener('click', () => {
        window.location.hash = 'leads';
      });
    }
  }

  pollProgress(container) {
    const lblStage = container.querySelector('#lblDiscoverStage');
    const lblPct = container.querySelector('#lblDiscoverPct');
    const barProgress = container.querySelector('#barDiscoverProgress');
    const lblFound = container.querySelector('#lblFoundCount');
    const lblLeads = container.querySelector('#lblLeadsCount');
    const lblElapsed = container.querySelector('#lblElapsedSec');
    const btnStart = container.querySelector('#btnStartPipeline');
    const btnText = container.querySelector('#btnStartPipelineText');
    const completionBanner = container.querySelector('#discoverCompletionBanner');
    const lblCompletionMsg = container.querySelector('#lblCompletionMsg');
    const lblCompletionCount = container.querySelector('#lblCompletionCount');

    const interval = setInterval(async () => {
      try {
        const status = await window.api.getPipelineStatus();
        window.store.setPipelineState(status);

        if (lblStage) lblStage.innerText = status.stage || 'Processing...';
        if (lblPct) lblPct.innerText = `${status.progress_pct || 0}%`;
        if (barProgress) barProgress.style.width = `${status.progress_pct || 0}%`;
        if (lblFound) lblFound.innerText = status.companies_found || 0;
        if (lblLeads) lblLeads.innerText = status.leads_generated || 0;
        if (lblElapsed) lblElapsed.innerText = `${status.elapsed_sec || 0}s`;

        if (status.status === 'completed' || status.status === 'error') {
          clearInterval(interval);
          if (btnStart) btnStart.disabled = false;
          if (btnText) btnText.innerText = 'Start Discovery';

          if (status.status === 'completed') {
            // Refresh leads in background
            const leadsRes = await window.api.getLeads({ limit: 500 });
            if (leadsRes && leadsRes.leads) {
              window.store.setLeads(leadsRes.leads);
            }

            if (completionBanner) {
              completionBanner.style.display = 'block';
              const btnView = completionBanner.querySelector('#btnViewDiscoveredLeads');

              if ((status.leads_generated || 0) > 0) {
                completionBanner.style.background = '#ecfdf5';
                completionBanner.style.borderColor = '#a7f3d0';
                if (lblCompletionMsg) {
                  lblCompletionMsg.style.color = '#065f46';
                  lblCompletionMsg.innerText = `Discovery completed!`;
                }
                if (lblCompletionCount) {
                  lblCompletionCount.style.color = '#047857';
                  lblCompletionCount.innerText = `${status.leads_generated} leads successfully discovered and saved.`;
                }
                if (btnView) {
                  btnView.style.display = 'inline-flex';
                  btnView.onclick = () => {
                    window.location.hash = 'leads';
                  };
                }
              } else {
                // Genuine zero results
                completionBanner.style.background = '#fefce8';
                completionBanner.style.borderColor = '#fef08a';
                if (lblCompletionMsg) {
                  lblCompletionMsg.style.color = '#854d0e';
                  lblCompletionMsg.innerText = `No matching companies found`;
                }
                if (lblCompletionCount) {
                  lblCompletionCount.style.color = '#a16207';
                  lblCompletionCount.innerText = `No matching companies were found for these criteria. Try broader keywords or alternative locations.`;
                }
                if (btnView) btnView.style.display = 'none';
              }
            }
          } else if (status.status === 'error') {
            if (completionBanner) {
              completionBanner.style.display = 'block';
              completionBanner.style.background = '#fef2f2';
              completionBanner.style.borderColor = '#fecaca';
              if (lblCompletionMsg) {
                lblCompletionMsg.style.color = '#991b1b';
                lblCompletionMsg.innerText = `Discovery failed`;
              }
              if (lblCompletionCount) {
                lblCompletionCount.style.color = '#b91c1c';
                lblCompletionCount.innerText = status.error_message || status.stage || 'An error occurred during discovery. Please check server logs and try again.';
              }
              const btnView = completionBanner.querySelector('#btnViewDiscoveredLeads');
              if (btnView) btnView.style.display = 'none';
            }
          }
        }
      } catch (err) {
        console.warn('Progress poll notice:', err);
      }
    }, 1500);
  }

  updateUIWithStatus(container, status) {
    if (!container || !status) return;
    const statusBox = container.querySelector('#discoverStatusBox');
    const lblStage = container.querySelector('#lblDiscoverStage');
    const lblPct = container.querySelector('#lblDiscoverPct');
    const barProgress = container.querySelector('#barDiscoverProgress');
    const lblFound = container.querySelector('#lblFoundCount');
    const lblLeads = container.querySelector('#lblLeadsCount');
    const lblElapsed = container.querySelector('#lblElapsedSec');
    const completionBanner = container.querySelector('#discoverCompletionBanner');
    const lblCompletionMsg = container.querySelector('#lblCompletionMsg');
    const lblCompletionCount = container.querySelector('#lblCompletionCount');
    const btnView = container.querySelector('#btnViewDiscoveredLeads');

    if (statusBox) statusBox.style.display = 'block';
    if (lblStage) lblStage.innerText = status.stage || 'Ready';
    if (lblPct) lblPct.innerText = `${status.progress_pct || 0}%`;
    if (barProgress) barProgress.style.width = `${status.progress_pct || 0}%`;
    if (lblFound) lblFound.innerText = status.companies_found || 0;
    if (lblLeads) lblLeads.innerText = status.leads_generated || 0;
    if (lblElapsed) lblElapsed.innerText = `${status.elapsed_sec || 0}s`;

    if (status.status === 'completed') {
      if (completionBanner) {
        completionBanner.style.display = 'block';
        if ((status.leads_generated || 0) > 0) {
          completionBanner.style.background = '#ecfdf5';
          completionBanner.style.borderColor = '#a7f3d0';
          if (lblCompletionMsg) {
            lblCompletionMsg.style.color = '#065f46';
            lblCompletionMsg.innerText = `Discovery completed!`;
          }
          if (lblCompletionCount) {
            lblCompletionCount.style.color = '#047857';
            lblCompletionCount.innerText = `${status.leads_generated} leads successfully discovered and saved.`;
          }
          if (btnView) {
            btnView.style.display = 'inline-flex';
            btnView.onclick = () => { window.location.hash = 'leads'; };
          }
        } else {
          completionBanner.style.background = '#fefce8';
          completionBanner.style.borderColor = '#fef08a';
          if (lblCompletionMsg) {
            lblCompletionMsg.style.color = '#854d0e';
            lblCompletionMsg.innerText = `No matching companies found`;
          }
          if (lblCompletionCount) {
            lblCompletionCount.style.color = '#a16207';
            lblCompletionCount.innerText = `No matching companies were found for these criteria. Try broader keywords or alternative locations.`;
          }
          if (btnView) btnView.style.display = 'none';
        }
      }
    } else if (status.status === 'error') {
      if (completionBanner) {
        completionBanner.style.display = 'block';
        completionBanner.style.background = '#fef2f2';
        completionBanner.style.borderColor = '#fecaca';
        if (lblCompletionMsg) {
          lblCompletionMsg.style.color = '#991b1b';
          lblCompletionMsg.innerText = `Discovery failed`;
        }
        if (lblCompletionCount) {
          lblCompletionCount.style.color = '#b91c1c';
          lblCompletionCount.innerText = status.error_message || status.stage || 'An error occurred during discovery.';
        }
        if (btnView) btnView.style.display = 'none';
      }
    }
  }
}

window.DiscoverView = DiscoverView;
