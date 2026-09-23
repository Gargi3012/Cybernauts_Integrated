/**
 * Lead Intelligence — Pipeline Monitor View
 */

class PipelineView {
  render(container) {
    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 20px; font-weight: 700; margin: 0 0 6px 0;">Pipeline Execution Monitor</h2>
        <div style="color: var(--text-muted); font-size: 13.5px;">
          Live multi-stage status tracking of web crawling workers and candidate ranking.
        </div>
      </div>

      <div class="card" style="padding: 24px; margin-bottom: 24px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
          <div>
            <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); text-transform: uppercase;">ACTIVE PIPELINE STAGE</div>
            <div id="lblPipelineStageText" style="font-size: 18px; font-weight: 700; color: var(--text-primary); margin-top: 4px;">Ready</div>
          </div>
          <span id="badgePipelineStatus" class="badge badge-info">IDLE</span>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-top: 20px;">
          <div style="background: var(--bg-surface-secondary); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
            <div style="font-size: 11px; font-weight: 700; color: var(--text-muted);">COMPANIES DISCOVERED</div>
            <div id="valFoundCount" style="font-size: 20px; font-weight: 700; margin-top: 4px;">0</div>
          </div>
          <div style="background: var(--bg-surface-secondary); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
            <div style="font-size: 11px; font-weight: 700; color: var(--text-muted);">LEADS GENERATED</div>
            <div id="valLeadsCount" style="font-size: 20px; font-weight: 700; margin-top: 4px;">0</div>
          </div>
          <div style="background: var(--bg-surface-secondary); padding: 14px; border-radius: var(--radius-sm); border: 1px solid var(--border-color);">
            <div style="font-size: 11px; font-weight: 700; color: var(--text-muted);">ELAPSED TIME</div>
            <div id="valElapsedSec" style="font-size: 20px; font-weight: 700; margin-top: 4px;">0s</div>
          </div>
        </div>
      </div>
    `;

    this.pollStatus(container);
  }

  async pollStatus(container) {
    try {
      const status = await window.api.getPipelineStatus();
      const lblStage = container.querySelector('#lblPipelineStageText');
      const badge = container.querySelector('#badgePipelineStatus');
      const valFound = container.querySelector('#valFoundCount');
      const valLeads = container.querySelector('#valLeadsCount');
      const valElapsed = container.querySelector('#valElapsedSec');

      if (lblStage) lblStage.innerText = status.stage || "Ready";
      if (badge) badge.innerText = (status.status || "IDLE").toUpperCase();
      if (valFound) valFound.innerText = status.companies_found || 0;
      if (valLeads) valLeads.innerText = status.leads_generated || 0;
      if (valElapsed) valElapsed.innerText = `${status.elapsed_sec || 0}s`;
    } catch (e) {
      console.warn("Pipeline status poll notice:", e);
    }
  }
}

window.PipelineView = PipelineView;
