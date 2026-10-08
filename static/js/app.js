/**
 * Flowiz Unified SPA Router & App Controller
 * Orchestrates views, state subscriptions, routing, and live event syncing
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
      recordings: new RecordingsView(),
      settings: new SettingsView()
    };
    this.leadDetailView = new LeadDetailView();
    this.leadCreateModal = new LeadCreateModal();
  }

  init() {
    this.setupNavigation();
    this.setupGlobalEvents();
    this.setupAuthHandlers();
    this.setupStateSubscriptions();
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

    // Global listener for CRM "Add Verified Lead" actions across views
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action="create-lead"], #btnOpenCreateLeadModal, #btnOverviewAddLead');
      if (btn) {
        e.preventDefault();
        if (this.leadCreateModal) {
          this.leadCreateModal.show();
        }
      }
    });
  }

  setupStateSubscriptions() {
    // Keep sidebar lead count synchronized
    window.store.subscribe('leadsUpdated', (leads) => {
      const countBadge = document.getElementById('sidebarLeadCount');
      if (countBadge) {
        countBadge.innerText = (leads && Array.isArray(leads)) ? leads.length : 0;
      }

      // Re-render active view if relevant
      const current = window.store.currentView;
      const container = document.getElementById('viewContainer');
      if (container && (current === 'overview' || current === 'pipeline' || current === 'leads')) {
        this.views[current].render(container);
      }
    });

    // Update topbar status pill if an active call starts
    window.store.subscribe('activeCallChanged', (activeCall) => {
      const topbarPill = document.getElementById('topbarStatusPill');
      if (topbarPill) {
        if (activeCall && activeCall.call_status !== 'completed') {
          topbarPill.innerHTML = `
            <span class="status-indicator" style="background: #eab308;"></span>
            <span>Call in Progress: ${activeCall.company_name || 'Prospect'}</span>
          `;
          topbarPill.className = 'status-pill status-warning';
        } else {
          topbarPill.innerHTML = `
            <span class="status-indicator"></span>
            <span>All Systems Operational</span>
          `;
          topbarPill.className = 'status-pill';
        }
      }
    });
  }

  setupAuthHandlers() {
    const btnHeaderAction = document.getElementById('btnHeaderAction');
    const authOverlay = document.getElementById('auth-overlay');
    const btnCloseAuth = document.getElementById('btn-close-auth');
    const btnLoginSubmit = document.getElementById('btn-login-submit');

    const isTokenExpired = (tok) => {
      if (!tok) return true;
      try {
        const payload = JSON.parse(atob(tok.split('.')[1]));
        return (payload.exp * 1000) < Date.now();
      } catch (e) {
        return true;
      }
    };

    let authMode = 'login'; // 'login' or 'signup'

    const titleEl = document.getElementById('auth-modal-title');
    const subtitleEl = document.getElementById('auth-modal-subtitle');
    const tabLogin = document.getElementById('tabAuthLogin');
    const tabSignup = document.getElementById('tabAuthSignup');
    const confirmGroup = document.getElementById('auth-confirm-group');
    const submitText = document.getElementById('auth-submit-text');
    const submitIcon = document.getElementById('auth-submit-icon');
    const togglePrompt = document.getElementById('auth-toggle-prompt');
    const btnToggleMode = document.getElementById('btn-auth-toggle-mode');
    const noticeEl = document.getElementById('auth-status-notice');

    const showNotice = (msg, isError = false) => {
      if (!noticeEl) return;
      noticeEl.style.display = 'block';
      noticeEl.style.background = isError ? '#fef2f2' : '#ecfdf5';
      noticeEl.style.color = isError ? '#991b1b' : '#065f46';
      noticeEl.style.border = `1px solid ${isError ? '#fecaca' : '#a7f3d0'}`;
      noticeEl.innerHTML = `<i class="fa-solid ${isError ? 'fa-circle-exclamation' : 'fa-circle-check'}" style="margin-right: 6px;"></i>${msg}`;
    };

    const clearNotice = () => {
      if (noticeEl) {
        noticeEl.style.display = 'none';
        noticeEl.innerHTML = '';
      }
    };

    const setAuthMode = (mode) => {
      authMode = mode;
      clearNotice();
      const usernameInput = document.getElementById('auth-username');
      const passwordInput = document.getElementById('auth-password');
      const confirmInput = document.getElementById('auth-confirm-password');

      if (mode === 'signup') {
        if (tabSignup) tabSignup.classList.add('active');
        if (tabLogin) tabLogin.classList.remove('active');
        if (titleEl) titleEl.textContent = 'Create Administrator Account';
        if (subtitleEl) subtitleEl.textContent = 'Register credentials to access Flowiz AI Voice & Telephony controls';
        if (confirmGroup) confirmGroup.style.display = 'block';
        if (submitText) submitText.textContent = 'Sign Up & Login';
        if (submitIcon) submitIcon.className = 'fa-solid fa-user-plus';
        if (togglePrompt) togglePrompt.textContent = 'Already have an account?';
        if (btnToggleMode) btnToggleMode.textContent = 'Sign In here';
        if (usernameInput && usernameInput.value === 'admin') usernameInput.value = '';
      } else {
        if (tabLogin) tabLogin.classList.add('active');
        if (tabSignup) tabSignup.classList.remove('active');
        if (titleEl) titleEl.textContent = 'Admin Authentication';
        if (subtitleEl) subtitleEl.textContent = 'Sign in to unlock Flowiz AI Voice & Telephony controls';
        if (confirmGroup) confirmGroup.style.display = 'none';
        if (submitText) submitText.textContent = 'Sign In';
        if (submitIcon) submitIcon.className = 'fa-solid fa-right-to-bracket';
        if (togglePrompt) togglePrompt.textContent = "Don't have an account?";
        if (btnToggleMode) btnToggleMode.textContent = 'Sign Up now';
        if (usernameInput && !usernameInput.value) usernameInput.value = 'admin';
      }
      if (passwordInput) passwordInput.value = '';
      if (confirmInput) confirmInput.value = '';
    };

    if (tabLogin) tabLogin.addEventListener('click', () => setAuthMode('login'));
    if (tabSignup) tabSignup.addEventListener('click', () => setAuthMode('signup'));
    if (btnToggleMode) btnToggleMode.addEventListener('click', () => setAuthMode(authMode === 'login' ? 'signup' : 'login'));

    const updateAuthUI = () => {
      let token = localStorage.getItem("jwt_token");
      if (token && isTokenExpired(token)) {
        localStorage.removeItem("jwt_token");
        token = null;
      }
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
        if (btnText) btnText.innerText = "Sign In / Sign Up";
        if (btnIcon) btnIcon.className = "fa-solid fa-user-lock";
        if (btnHeaderAction) {
          btnHeaderAction.classList.remove('btn-secondary');
          btnHeaderAction.classList.add('btn-primary');
          btnHeaderAction.title = "Click to Sign In or Sign Up";
        }
      }
    };

    if (btnHeaderAction) {
      btnHeaderAction.addEventListener('click', () => {
        const token = localStorage.getItem("jwt_token");
        if (token) {
          if (confirm("Log out of Admin session?")) {
            localStorage.removeItem("jwt_token");
            updateAuthUI();
            if (window.store.currentView === 'liveAgent' && this.views.liveAgent) {
              this.views.liveAgent.render(document.getElementById('viewContainer'));
            }
          }
        } else if (authOverlay) {
          clearNotice();
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

    const handleAuthSubmit = async () => {
      clearNotice();
      const usernameInput = document.getElementById('auth-username');
      const passwordInput = document.getElementById('auth-password');
      const confirmInput = document.getElementById('auth-confirm-password');

      const username = usernameInput ? usernameInput.value.trim() : '';
      const password = passwordInput ? passwordInput.value : '';
      const confirmPassword = confirmInput ? confirmInput.value : '';

      if (!username || !password) {
        showNotice("Please fill out both username and password.", true);
        return;
      }

      if (authMode === 'signup') {
        if (username.length < 3) {
          showNotice("Username must be at least 3 characters long.", true);
          return;
        }
        if (password.length < 6) {
          showNotice("Password must be at least 6 characters long.", true);
          return;
        }
        if (password !== confirmPassword) {
          showNotice("Passwords do not match. Please re-enter.", true);
          return;
        }

        try {
          if (btnLoginSubmit) {
            btnLoginSubmit.disabled = true;
            btnLoginSubmit.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>Creating Account...</span>';
          }

          const regRes = await window.api.register(username, password);
          if (regRes && (regRes.status === 'success' || regRes.message)) {
            showNotice("✓ Account created! Signing in automatically...", false);

            // Auto-login with the newly created account
            const loginRes = await window.api.login(username, password);
            if (loginRes && loginRes.token) {
              setTimeout(() => {
                authOverlay.classList.add('hidden');
                updateAuthUI();
                if (passwordInput) passwordInput.value = '';
                if (confirmInput) confirmInput.value = '';
                if (window.store.currentView === 'liveAgent' && this.views.liveAgent) {
                  this.views.liveAgent.render(document.getElementById('viewContainer'));
                }
              }, 600);
            } else {
              setAuthMode('login');
              showNotice("Account registered! Please sign in with your password.", false);
            }
          } else {
            throw new Error(regRes?.detail || "Registration failed.");
          }
        } catch (err) {
          showNotice("Sign Up Error: " + (err.message || err), true);
        } finally {
          if (btnLoginSubmit) {
            btnLoginSubmit.disabled = false;
            btnLoginSubmit.innerHTML = `<i class="fa-solid ${authMode === 'signup' ? 'fa-user-plus' : 'fa-right-to-bracket'}"></i><span>${authMode === 'signup' ? 'Sign Up & Login' : 'Sign In'}</span>`;
          }
        }
      } else {
        // Sign In mode
        try {
          if (btnLoginSubmit) {
            btnLoginSubmit.disabled = true;
            btnLoginSubmit.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>Signing In...</span>';
          }

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
          showNotice("Login Failed: " + (err.message || err), true);
        } finally {
          if (btnLoginSubmit) {
            btnLoginSubmit.disabled = false;
            btnLoginSubmit.innerHTML = '<i class="fa-solid fa-right-to-bracket"></i><span>Sign In</span>';
          }
        }
      }
    };

    if (btnLoginSubmit) {
      btnLoginSubmit.addEventListener('click', handleAuthSubmit);
    }

    const authForm = document.getElementById('auth-form');
    if (authForm) {
      authForm.addEventListener('submit', (e) => {
        e.preventDefault();
        handleAuthSubmit();
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

      this.updateRecordingCount();
    } catch (err) {
      console.warn("Initial data load notice:", err);
    }
  }

  async updateRecordingCount() {
    try {
      const recRes = await window.api.getRecordings({ limit: 1 });
      if (recRes && recRes.count !== undefined) {
        const badge = document.getElementById('sidebarRecordingCount');
        if (badge) badge.innerText = recRes.count;
      }
    } catch (_) {}
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
        overview: 'System Overview',
        discover: 'Discover Leads',
        leads: 'All Leads Directory',
        pipeline: 'Qualification Pipeline',
        analytics: 'Analytics',
        liveAgent: 'Live AI Voice Agent',
        callHistory: 'Call History & Transcripts',
        recordings: 'Call Recordings & Audio Archive',
        settings: 'Diagnostics & Settings'
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

document.addEventListener('DOMContentLoaded', () => {
  window.app = new CybernautsApp();
  window.app.init();
});
