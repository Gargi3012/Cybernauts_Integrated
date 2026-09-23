/**
 * Lead Intelligence — Analytics View
 */

class AnalyticsView {
  render(container) {
    const categories = window.store.categories || {};
    const catKeys = Object.keys(categories);

    container.innerHTML = `
      <div style="margin-bottom: 24px;">
        <h2 style="font-size: 20px; font-weight: 700; margin: 0 0 6px 0;">Dataset Analytics</h2>
        <div style="color: var(--text-muted); font-size: 13.5px;">
          Distribution of mined lead records grouped by industry.
        </div>
      </div>

      <div class="card" style="padding: 24px;">
        <h3 style="margin: 0 0 16px 0; font-size: 15px; font-weight: 600;">Industry Lead Distribution</h3>
        <div style="display: flex; flex-direction: column; gap: 14px;">
          ${catKeys.length === 0 ? `
            <div class="text-muted" style="font-size: 13.5px;">No industry analytics available. Mine new leads to view breakdown.</div>
          ` : catKeys.map(cat => `
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 13px; font-weight: 500; margin-bottom: 6px;">
                <span>${cat}</span>
                <span class="font-mono text-muted">${categories[cat]} leads</span>
              </div>
              <div style="height: 8px; background: var(--bg-surface-muted); border-radius: var(--radius-pill); overflow: hidden;">
                <div style="height: 100%; width: ${Math.min(100, (categories[cat] / (window.store.allLeads.length || 1)) * 100)}%; background: var(--accent-primary);"></div>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }
}

window.AnalyticsView = AnalyticsView;
