/**
 * Lead Intelligence — Discover Leads View
 * Team A OSINT Discovery Engine
 * Multi-criteria search input with live stage-by-stage crawling progression
 */

class DiscoverView {
  render(container) {
    const isRunning = window.store.pipelineState && window.store.pipelineState.status === 'running';

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
          <div id="discoverStatusBox" style="margin-top: 24px; padding: 20px; border-radius: 8px; border: 1px solid var(--border-color); background: var(--bg-surface-secondary); display: ${isRunning ? 'block' : 'none'};">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span class="status-indicator" style="background: #3b82f6;"></span>
                <span id="lblDiscoverStage" style="font-weight: 700; font-size: 14px; color: var(--text-primary);">
                  ${window.store.pipelineState.stage || 'Initializing search...'}
                </span>
              </div>
              <div id="lblDiscoverPct" class="font-mono" style="font-weight: 700; font-size: 14px; color: var(--color-primary);">
                ${window.store.pipelineState.progress_pct || 0}%
              </div>
            </div>

            <!-- Progress Bar -->
            <div style="height: 6px; background: #e2e8f0; border-radius: 999px; overflow: hidden; margin-bottom: 16px;">
              <div id="barDiscoverProgress" style="height: 100%; width: ${window.store.pipelineState.progress_pct || 0}%; background: var(--color-primary); transition: width 0.3s ease;"></div>
            </div>

            <!-- Live Metrics Counter -->
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; text-align: center;">
              <div style="background: #ffffff; padding: 10px; border-radius: 6px; border: 1px solid var(--border-color);">
                <div style="font-size: 10.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Companies Found</div>
                <div id="lblFoundCount" style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin-top: 2px;">
                  ${window.store.pipelineState.companies_found || 0}
                </div>
              </div>
              <div style="background: #ffffff; padding: 10px; border-radius: 6px; border: 1px solid var(--border-color);">
                <div style="font-size: 10.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Leads Generated</div>
                <div id="lblLeadsCount" style="font-size: 18px; font-weight: 700; color: #16a34a; margin-top: 2px;">
                  ${window.store.pipelineState.leads_generated || 0}
                </div>
              </div>
              <div style="background: #ffffff; padding: 10px; border-radius: 6px; border: 1px solid var(--border-color);">
                <div style="font-size: 10.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">Elapsed Time</div>
                <div id="lblElapsedSec" style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin-top: 2px;">
                  ${window.store.pipelineState.elapsed_sec || 0}s
                </div>
              </div>
            </div>

            <!-- Completion Banner -->
            <div id="discoverCompletionBanner" style="display: none; margin-top: 16px; padding: 14px; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 6px; text-align: center;">
              <div style="font-weight: 700; color: #065f46; font-size: 14px; margin-bottom: 4px;" id="lblCompletionMsg">
                Discovery completed!
              </div>
              <div style="font-size: 12.5px; color: #047857; margin-bottom: 10px;" id="lblCompletionCount">
                New leads have been enriched and normalized into the canonical repository.
              </div>
              <button class="btn btn-primary" id="btnViewDiscoveredLeads">
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

    if (isRunning) {
      this.pollProgress(container);
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
              if (lblCompletionMsg) {
                lblCompletionMsg.innerText = `Discovery completed!`;
              }
              if (lblCompletionCount) {
                lblCompletionCount.innerText = `${status.leads_generated || 0} leads successfully discovered and saved.`;
              }
              const btnView = completionBanner.querySelector('#btnViewDiscoveredLeads');
              if (btnView) {
                btnView.onclick = () => {
                  window.location.hash = 'leads';
                };
              }
            }
          }
        }
      } catch (err) {
        console.warn('Progress poll notice:', err);
      }
    }, 1500);
  }
}

window.DiscoverView = DiscoverView;
