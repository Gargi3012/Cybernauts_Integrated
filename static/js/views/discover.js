/**
 * Lead Intelligence — Discover Leads View
 */

class DiscoverView {
  render(container) {
    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 20px; font-weight: 800; margin: 0 0 6px 0;">Discover & Extract Leads</h2>
        <div style="color: var(--flowiz-text-muted); font-size: 13px;">
          Trigger real-time OSINT crawling across search engines and directory providers.
        </div>
      </div>

      <div class="card" style="padding: 32px; max-width: 680px; margin-bottom: 28px;">
        <div style="margin-bottom: 20px;">
          <label style="display: block; font-weight: 700; font-size: 14px; margin-bottom: 8px;">Target Industry or Keyword</label>
          <input 
            type="text" 
            id="txtDiscoverKeyword" 
            class="form-input" 
            placeholder="e.g. Fintech startups in San Francisco, AI SaaS companies..." 
            style="font-size: 15px; padding: 12px 16px;"
          />
        </div>

        <button id="btnStartPipeline" class="btn btn-primary" style="padding: 12px 24px; font-size: 14px;">
          <i class="fa-solid fa-play"></i>
          <span>Start Mining Pipeline</span>
        </button>

        <div id="discoverStatusBox" class="card" style="margin-top: 24px; padding: 16px; background: #f8fafc; display: none;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div id="lblDiscoverStage" style="font-weight: 700; font-size: 13px; color: var(--flowiz-text-primary);">Initializing search...</div>
            <div id="lblDiscoverPct" class="font-mono text-accent" style="font-weight: 700; font-size: 13px;">0%</div>
          </div>
          <div style="height: 6px; background: #e2e8f0; border-radius: var(--radius-pill); overflow: hidden;">
            <div id="barDiscoverProgress" style="height: 100%; width: 0%; background: var(--flowiz-primary-purple); transition: width 0.3s ease;"></div>
          </div>
        </div>
      </div>
    `;

    this.attachEvents(container);
  }

  attachEvents(container) {
    const btnStart = container.querySelector('#btnStartPipeline');
    const txtKeyword = container.querySelector('#txtDiscoverKeyword');
    const statusBox = container.querySelector('#discoverStatusBox');
    const lblStage = container.querySelector('#lblDiscoverStage');
    const lblPct = container.querySelector('#lblDiscoverPct');
    const barProgress = container.querySelector('#barDiscoverProgress');

    if (btnStart && txtKeyword) {
      btnStart.addEventListener('click', async () => {
        const kw = txtKeyword.value.trim();
        if (!kw) {
          alert("Please enter a target keyword or industry.");
          return;
        }

        try {
          btnStart.disabled = true;
          statusBox.style.display = 'block';
          await window.api.searchLeads(kw);

          // Poll pipeline status
          const interval = setInterval(async () => {
            try {
              const status = await window.api.getPipelineStatus();
              lblStage.innerText = status.stage || "Processing...";
              lblPct.innerText = `${status.progress_pct || 0}%`;
              barProgress.style.width = `${status.progress_pct || 0}%`;

              if (status.status === 'completed' || status.status === 'error') {
                clearInterval(interval);
                btnStart.disabled = false;
                if (status.status === 'completed') {
                  alert(`Pipeline Completed! Generated ${status.leads_generated || 0} rich lead cards.`);
                  window.location.hash = 'leads';
                }
              }
            } catch (err) {
              clearInterval(interval);
              btnStart.disabled = false;
            }
          }, 1500);

        } catch (err) {
          alert("Failed to trigger pipeline: " + (err.message || err));
          btnStart.disabled = false;
        }
      });
    }
  }
}

window.DiscoverView = DiscoverView;
