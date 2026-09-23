/**
 * Cybernauts Integrated Platform — Reactive Application State Manager
 */

class CybernautsState {
  constructor() {
    this.currentView = 'overview';
    this.allLeads = [];
    this.categories = {};
    this.selectedLead = null;
    this.selectedLeadTab = 'overview';
    this.searchQuery = '';
    
    // Filtering & Pagination
    this.activeCategory = null;
    this.activeQuality = null;
    this.filterHasEmail = false;
    this.filterHasPhone = false;
    this.filterHasSocial = false;
    this.page = 1;
    this.pageSize = 25;

    // Live Pipeline Tracking (Team A)
    this.pipelineState = {
      status: 'idle',
      stage: 'Ready',
      stage_code: 'IDLE',
      keyword: '',
      progress_pct: 0,
      companies_found: 0,
      leads_generated: 0,
      elapsed_sec: 0,
    };

    // Voice Agent State (Team B)
    this.voiceState = {
      isCallActive: false,
      callMode: 'livekit',
      roomName: '',
      transcripts: [],
      latencyMs: 0,
      language: 'English',
      statusMessage: 'Ready for input'
    };

    this.listeners = new Map();
  }

  subscribe(key, callback) {
    if (!this.listeners.has(key)) {
      this.listeners.set(key, new Set());
    }
    this.listeners.get(key).add(callback);
    return () => this.listeners.get(key).delete(callback);
  }

  notify(key, data) {
    if (this.listeners.has(key)) {
      this.listeners.get(key).forEach(cb => cb(data));
    }
  }

  setView(viewName) {
    if (this.currentView === viewName) return;
    this.currentView = viewName;
    this.notify('viewChange', viewName);
  }

  setLeads(leads) {
    this.allLeads = leads || [];
    this.notify('leadsUpdated', this.allLeads);
  }

  setCategories(cats) {
    this.categories = cats || {};
    this.notify('categoriesUpdated', this.categories);
  }

  setSelectedLead(lead, tab = 'overview') {
    this.selectedLead = lead;
    this.selectedLeadTab = tab;
    this.notify('selectedLeadChanged', { lead, tab });
  }

  setSelectedLeadTab(tab) {
    this.selectedLeadTab = tab;
    this.notify('selectedLeadTabChanged', tab);
  }

  setPipelineState(state) {
    this.pipelineState = { ...this.pipelineState, ...state };
    this.notify('pipelineStateChanged', this.pipelineState);
  }

  setVoiceState(state) {
    this.voiceState = { ...this.voiceState, ...state };
    this.notify('voiceStateChanged', this.voiceState);
  }

  addTranscript(role, text) {
    this.voiceState.transcripts.push({ role, text, timestamp: new Date().toLocaleTimeString() });
    this.notify('transcriptsUpdated', this.voiceState.transcripts);
  }

  getFilteredLeads() {
    let list = this.allLeads;

    if (this.searchQuery && this.searchQuery.trim()) {
      const q = this.searchQuery.toLowerCase().trim();
      list = list.filter(l => 
        (l.company_name && l.company_name.toLowerCase().includes(q)) ||
        (l.domain && l.domain.toLowerCase().includes(q)) ||
        (l.industry && l.industry.toLowerCase().includes(q)) ||
        (l.keyword && l.keyword.toLowerCase().includes(q)) ||
        (l.location && l.location.toLowerCase().includes(q))
      );
    }

    if (this.activeCategory) {
      const cat = this.activeCategory.toLowerCase();
      list = list.filter(l => 
        (l.industry || l.company_type || 'Unknown').toLowerCase() === cat
      );
    }

    if (this.activeQuality) {
      list = list.filter(l => (l.lead_quality || 'Low').toLowerCase() === this.activeQuality.toLowerCase());
    }

    if (this.filterHasEmail) {
      list = list.filter(l => Array.isArray(l.emails) && l.emails.length > 0);
    }

    if (this.filterHasPhone) {
      list = list.filter(l => Array.isArray(l.phones) && l.phones.length > 0);
    }

    return list;
  }
}

window.store = new CybernautsState();
