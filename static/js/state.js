/**
 * Flowiz Integrated Platform — Reactive Application State Manager
 * Preserves deterministic traceability:
 * Lead (lead_id) -> Dispatch (dispatch_id) -> Session (session_id) -> Telephony (call_uuid) -> Qualification -> Same Lead
 */

class CybernautsState {
  constructor() {
    this.currentView = 'overview';
    this.allLeads = [];
    this.categories = {};
    this.selectedLead = null;
    this.selectedLeadTab = 'overview';
    this.searchQuery = '';
    
    // Filtering, Sorting & Pagination
    this.activeCategory = null;
    this.activeQuality = null;
    this.activeQualStatus = null;
    this.sortBy = 'name'; // 'name', 'quality', 'score', 'recent'
    this.sortDir = 'asc';
    this.filterHasEmail = false;
    this.filterHasPhone = false;
    this.page = 1;
    this.pageSize = 15;

    // Live Scraping Pipeline Tracking (Team A)
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
      callMode: 'telephony', // 'telephony' (Plivo) or 'livekit' (WebRTC)
      roomName: '',
      transcripts: [],
      latencyMs: 0,
      language: 'English',
      statusMessage: 'Ready for input',
      speakerState: 'idle', // 'idle', 'ai_speaking', 'user_speaking', 'thinking'
      callStartedAt: null,
      callDurationSec: 0
    };

    // Active Lead Qualification Call Tracking
    this.activeCall = null;

    // AI Agent Personas (Shreya, Ritu, Ratan, Manan)
    this.selectedPersona = 'shreya';
    this.personas = [
      {
        id: 'shreya',
        name: 'Shreya',
        gender: 'female',
        voice: 'shreya',
        model: 'bulbul:v3',
        role: 'Friendly Sales & Success',
        tone: 'Warm & Conversational',
        accent: 'Natural Hinglish',
        avatar: '👩',
        greeting_en: 'Hello, this is Shreya from Flowiz and Cybernauts. How can I help you today?',
        greeting_hi: 'नमस्ते, मैं Flowiz से Shreya बोल रही हूँ। मैं आपकी क्या मदद कर सकती हूँ?',
        sample_text: 'Hi, main Flowiz se Shreya bol rahi hoon. Hum aapki sales team ke calls ko automate karne me help karte hain.',
        audio_sample: '/static/audio/shreya_sample.wav'
      },
      {
        id: 'ritu',
        name: 'Ritu',
        gender: 'female',
        voice: 'ritu',
        model: 'bulbul:v3',
        role: 'Client Onboarding & Operations',
        tone: 'Calm & Supportive',
        accent: 'Polite English / Hindi',
        avatar: '👩‍💼',
        greeting_en: 'Hello, this is Ritu from Flowiz and Cybernauts. How may I assist you today?',
        greeting_hi: 'नमस्ते, मैं Flowiz से Ritu बोल रही हूँ। मैं आपकी क्या सहायता कर सकती हूँ?',
        sample_text: 'Hello, main Flowiz se Ritu bol rahi hoon. Aapka platform onboarding process smooth aur simple banana hamari priority hai.',
        audio_sample: '/static/audio/ritu_sample.wav'
      },
      {
        id: 'ratan',
        name: 'Ratan',
        gender: 'male',
        voice: 'ratan',
        model: 'bulbul:v3',
        role: 'Enterprise Solutions Consultant',
        tone: 'Corporate & Authoritative',
        accent: 'Corporate Hinglish',
        avatar: '👨',
        greeting_en: 'Hello, this is Ratan from Flowiz and Cybernauts. How can I help you today?',
        greeting_hi: 'नमस्ते, मैं Flowiz से Ratan बोल रहा हूँ। मैं आपकी क्या सहायता कर सकता हूँ?',
        sample_text: 'Hi, main Flowiz se Ratan bol raha hoon. Hum enterprise businesses ke outbound lead operations ko automate karte hain.',
        audio_sample: '/static/audio/ratan_sample.wav'
      },
      {
        id: 'manan',
        name: 'Manan',
        gender: 'male',
        voice: 'manan',
        model: 'bulbul:v3',
        role: 'Tech Automation & Product Advisor',
        tone: 'Energetic & Modern',
        accent: 'Tech Hinglish',
        avatar: '👨‍💻',
        greeting_en: 'Hey there, this is Manan from Flowiz and Cybernauts. How are you doing today?',
        greeting_hi: 'नमस्ते, मैं Flowiz से Manan बोल रहा हूँ। आज मैं आपकी क्या सहायता कर सकता हूँ?',
        sample_text: 'Hey! Main Flowiz se Manan bol raha hoon. Real-time voice AI pipelines aur automated qualification hamara core expertise hai.',
        audio_sample: '/static/audio/manan_sample.wav'
      }
    ];

    this.listeners = new Map();
  }

  setPersona(personaId) {
    if (!personaId) return;
    const exists = this.personas.some(p => p.id === personaId);
    this.selectedPersona = exists ? personaId : 'shreya';
    this.notify('persona', this.selectedPersona);
  }

  getSelectedPersona() {
    return this.personas.find(p => p.id === this.selectedPersona) || this.personas[0];
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
      this.listeners.get(key).forEach(cb => {
        try {
          cb(data);
        } catch (err) {
          console.error(`[State Notification Error for '${key}']`, err);
        }
      });
    }
  }

  setView(viewName) {
    if (this.currentView === viewName) return;
    this.currentView = viewName;
    this.notify('viewChange', viewName);
  }

  setLeads(leads) {
    this.allLeads = Array.isArray(leads) ? leads : [];
    this.notify('leadsUpdated', this.allLeads);
  }

  addLead(lead) {
    if (!lead) return;
    const domain = lead.domain || lead.website;
    const existingIndex = this.allLeads.findIndex(l => 
      (domain && (l.domain === domain || l.website === domain)) || 
      (lead.id && l.id === lead.id)
    );

    if (existingIndex !== -1) {
      this.allLeads[existingIndex] = { ...this.allLeads[existingIndex], ...lead };
    } else {
      this.allLeads.unshift(lead);
    }

    const cat = lead.industry || 'B2B Services';
    if (cat) {
      this.categories[cat] = (this.categories[cat] || 0) + 1;
    }

    this.notify('leadsUpdated', this.allLeads);
    this.notify('categoriesUpdated', this.categories);
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

  setActiveCall(callData) {
    this.activeCall = callData;
    this.notify('activeCallChanged', this.activeCall);
  }

  updateActiveCall(partial) {
    if (!this.activeCall) {
      this.activeCall = partial;
    } else {
      this.activeCall = { ...this.activeCall, ...partial };
    }
    this.notify('activeCallChanged', this.activeCall);
  }

  clearActiveCall() {
    this.activeCall = null;
    this.notify('activeCallChanged', null);
  }

  updateLeadQualification(leadId, qualificationData) {
    if (!leadId || !qualificationData) return;

    // Find and update in allLeads
    const index = this.allLeads.findIndex(l => 
      l.domain === leadId || 
      l.website === leadId || 
      String(l.id) === String(leadId)
    );

    if (index !== -1) {
      const existing = this.allLeads[index];
      const updated = {
        ...existing,
        qualification_status: qualificationData.qualification_status || existing.qualification_status,
        qualification_score: qualificationData.qualification_score !== undefined ? qualificationData.qualification_score : existing.qualification_score,
        call_status: qualificationData.call_status || 'completed',
        interest_level: qualificationData.interest_level || existing.interest_level,
        pain_points: qualificationData.pain_points || existing.pain_points,
        budget: qualificationData.budget || existing.budget,
        timeline: qualificationData.timeline || existing.timeline,
        conversation_summary: qualificationData.conversation_summary || existing.conversation_summary,
        last_contacted_at: new Date().toISOString(),
        provider_call_id: qualificationData.provider_call_id || existing.provider_call_id,
        session_id: qualificationData.session_id || existing.session_id
      };

      this.allLeads[index] = updated;

      // Update selectedLead if it matches
      if (this.selectedLead && (
        this.selectedLead.domain === leadId || 
        this.selectedLead.website === leadId || 
        String(this.selectedLead.id) === String(leadId)
      )) {
        this.selectedLead = updated;
        this.notify('selectedLeadChanged', { lead: updated, tab: this.selectedLeadTab });
      }

      this.notify('leadsUpdated', this.allLeads);
    }
  }

  addTranscript(role, text, metadata = {}) {
    this.voiceState.transcripts.push({
      role, // 'agent', 'user', 'system'
      text,
      timestamp: new Date().toLocaleTimeString(),
      language: metadata.language || null,
      emotion: metadata.emotion || null,
      latencyMs: metadata.latencyMs || null
    });
    this.notify('transcriptsUpdated', this.voiceState.transcripts);
  }

  clearTranscripts() {
    this.voiceState.transcripts = [];
    this.notify('transcriptsUpdated', []);
  }

  getFilteredLeads() {
    let list = [...this.allLeads];

    if (this.searchQuery && this.searchQuery.trim()) {
      const q = this.searchQuery.toLowerCase().trim();
      list = list.filter(l => 
        (l.company_name && l.company_name.toLowerCase().includes(q)) ||
        (l.domain && l.domain.toLowerCase().includes(q)) ||
        (l.website && l.website.toLowerCase().includes(q)) ||
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

    if (this.activeQualStatus) {
      list = list.filter(l => {
        const status = (l.qualification_status || l.call_status || 'unqualified').toLowerCase();
        return status === this.activeQualStatus.toLowerCase();
      });
    }

    if (this.filterHasEmail) {
      list = list.filter(l => Array.isArray(l.emails) && l.emails.length > 0);
    }

    if (this.filterHasPhone) {
      list = list.filter(l => Array.isArray(l.phones) && l.phones.length > 0);
    }

    // Sorting
    list.sort((a, b) => {
      let valA, valB;
      if (this.sortBy === 'name') {
        valA = (a.company_name || '').toLowerCase();
        valB = (b.company_name || '').toLowerCase();
      } else if (this.sortBy === 'score') {
        valA = a.qualification_score || 0;
        valB = b.qualification_score || 0;
      } else if (this.sortBy === 'quality') {
        const order = { 'high': 3, 'medium': 2, 'low': 1 };
        valA = order[(a.lead_quality || '').toLowerCase()] || 0;
        valB = order[(b.lead_quality || '').toLowerCase()] || 0;
      } else {
        valA = a.company_name || '';
        valB = b.company_name || '';
      }

      if (valA < valB) return this.sortDir === 'asc' ? -1 : 1;
      if (valA > valB) return this.sortDir === 'asc' ? 1 : -1;
      return 0;
    });

    return list;
  }
}

window.store = new CybernautsState();
