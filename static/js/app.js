/**
 * Flowiz Unified SPA Router & App Controller
 */

class CybernautsApp {
  constructor() {
    this.views = {
      overview: new OverviewView(),
      discover: new DiscoverView(),
      leads: new LeadsView(),
      pipeline: new PipelineView(),
      analytics: new AnalyticsView(),
      liveAgent: new LiveAgentView(),
      callHistory: new CallHistoryView(),
      settings: new SettingsView()
    };
    this.leadDetailView = new LeadDetailView();
  }

  init() {
    this.setupNavigation();
    this.setupGlobalEvents();
    this.setupAuthHandlers();
    this.loadInitialData();
    
    // Hash Routing
    window.addEventListener('hashchange', () => this.handleRoute());
    this.handleRoute();
  }

  setupNavigation() {
    // Sidebar toggle
    const btnToggle = document.getElementById('btnToggleSidebar');
    const sidebar = document.getElementById('appSidebar');
    if (btnToggle && sidebar) {
      btnToggle.addEventListener('click', () => {
        sidebar.classList.toggle('collapsed');
      });
    }

    // Nav link click events
    document.querySelectorAll('.sidebar-link').forEach(link => {
      link.addEventListener('click', (e) => {
        const view = link.getAttribute('data-view');
        if (view) {
          window.location.hash = view;
        }
      });
    });
  }

  setupGlobalEvents() {
    // Global search input in topbar
    const globalSearch = document.getElementById('globalSearchInput');
    if (globalSearch) {
      globalSearch.addEventListener('input', (e) => {
        window.store.searchQuery = e.target.value;
        if (window.store.currentView !== 'leads') {
          window.location.hash = 'leads';
        } else if (this.views.leads) {
          this.views.leads.render(document.getElementById('viewContainer'));
        }
      });
    }

    // Modal close events
    const modalContainer = document.getElementById('modalContainer');
    if (modalContainer) {
      modalContainer.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-backdrop')) {
          modalContainer.innerHTML = '';
        }
      });
    }
  }

  setupAuthHandlers() {
    const btnHeaderAction = document.getElementById('btnHeaderAction');
    const authOverlay = document.getElementById('auth-overlay');
    const btnCloseAuth = document.getElementById('btn-close-auth');
    const btnLoginSubmit = document.getElementById('btn-login-submit');

    const updateAuthUI = () => {
      const token = localStorage.getItem("jwt_token");
      const btnText = document.getElementById('btnHeaderActionText');
      const btnIcon = btnHeaderAction ? btnHeaderAction.querySelector('i') : null;

      if (token) {
        if (btnText) btnText.innerText = "Admin Authenticated";
        if (btnIcon) btnIcon.className = "fa-solid fa-user-check text-accent";
        if (btnHeaderAction) {
          btnHeaderAction.classList.remove('btn-primary');
          btnHeaderAction.classList.add('btn-secondary');
          btnHeaderAction.title = "Click to Log Out";
        }
      } else {
        if (btnText) btnText.innerText = "Admin Auth";
        if (btnIcon) btnIcon.className = "fa-solid fa-user-lock";
        if (btnHeaderAction) {
          btnHeaderAction.classList.remove('btn-secondary');
          btnHeaderAction.classList.add('btn-primary');
          btnHeaderAction.title = "Click to Sign In";
        }
      }
    };

    if (btnHeaderAction) {
      btnHeaderAction.addEventListener('click', () => {
        const token = localStorage.getItem("jwt_token");
        if (token) {
          if (confirm("Log out of Admin Voice session?")) {
            localStorage.removeItem("jwt_token");
            updateAuthUI();
            if (window.store.currentView === 'liveAgent' && this.views.liveAgent) {
              this.views.liveAgent.render(document.getElementById('viewContainer'));
            }
          }
        } else if (authOverlay) {
          authOverlay.classList.remove('hidden');
        }
      });
    }

    if (btnCloseAuth && authOverlay) {
      btnCloseAuth.addEventListener('click', () => {
        authOverlay.classList.add('hidden');
      });
    }

    if (authOverlay) {
      authOverlay.addEventListener('click', (e) => {
        if (e.target === authOverlay) {
          authOverlay.classList.add('hidden');
        }
      });
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && authOverlay && !authOverlay.classList.contains('hidden')) {
        authOverlay.classList.add('hidden');
      }
    });

    if (btnLoginSubmit && authOverlay) {
      btnLoginSubmit.addEventListener('click', async () => {
        const usernameInput = document.getElementById('auth-username');
        const passwordInput = document.getElementById('auth-password');
        const username = usernameInput ? usernameInput.value : '';
        const password = passwordInput ? passwordInput.value : '';

        if (!username || !password) {
          alert("Please enter both username and password.");
          return;
        }

        try {
          btnLoginSubmit.disabled = true;
          btnLoginSubmit.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>Signing In...</span>';

          const res = await window.api.login(username, password);
          if (res.token) {
            authOverlay.classList.add('hidden');
            updateAuthUI();
            if (passwordInput) passwordInput.value = '';
            if (window.store.currentView === 'liveAgent' && this.views.liveAgent) {
              this.views.liveAgent.render(document.getElementById('viewContainer'));
            }
          }
        } catch (err) {
          alert("Login Failed: " + (err.message || err));
        } finally {
          btnLoginSubmit.disabled = false;
          btnLoginSubmit.innerHTML = '<span>Sign In</span>';
        }
      });
    }

    // Initialize Auth UI state on page load
    updateAuthUI();
  }

  async loadInitialData() {
    try {
      const [leadsRes, catsRes] = await Promise.all([
        window.api.getLeads({ limit: 500 }),
        window.api.getCategories()
      ]);

      if (leadsRes && leadsRes.leads) {
        window.store.setLeads(leadsRes.leads);
        const countBadge = document.getElementById('sidebarLeadCount');
        if (countBadge) countBadge.innerText = leadsRes.leads.length;
      }

      if (catsRes && catsRes.categories) {
        window.store.setCategories(catsRes.categories);
      }
    } catch (err) {
      console.warn("Initial data load notice:", err);
    }
  }

  handleRoute() {
    const hash = window.location.hash.replace('#', '') || 'overview';
    const targetView = this.views[hash] ? hash : 'overview';
    window.store.currentView = targetView;

    // Update Sidebar Active state
    document.querySelectorAll('.sidebar-link').forEach(link => {
      if (link.getAttribute('data-view') === targetView) {
        link.classList.add('active');
      } else {
        link.classList.remove('active');
      }
    });

    // Update Breadcrumb text
    const breadcrumb = document.getElementById('currentBreadcrumb');
    if (breadcrumb) {
      const titleMap = {
        overview: 'Overview',
        discover: 'Discover Leads',
        leads: 'All Leads',
        pipeline: 'Pipeline Monitor',
        analytics: 'Analytics',
        liveAgent: 'Live AI Voice Agent',
        callHistory: 'Voice Call History',
        settings: 'Settings'
      };
      breadcrumb.innerText = titleMap[targetView] || targetView;
    }

    // Render View
    const container = document.getElementById('viewContainer');
    if (container && this.views[targetView]) {
      this.views[targetView].render(container);
    }
  }
}

// Global View Classes Registration (Placeholders that render clean UI)
document.addEventListener('DOMContentLoaded', () => {
  window.app = new CybernautsApp();
  window.app.init();
});
