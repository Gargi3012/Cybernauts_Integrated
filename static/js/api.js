/**
 * Flowiz Unified API Client
 * Manages REST API calls for Lead Intelligence and AI Voice Agent
 * No hardcoded domains; uses window.location.origin relative paths
 */

const API_BASE = "";

async function fetchJSON(url, options = {}) {
  const headers = options.headers || {};
  const token = localStorage.getItem("jwt_token");
  if (token && !headers["Authorization"]) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  
  options.headers = headers;

  // Enforce a sensible client-side abort timeout (30 seconds for long API calls)
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), options.timeoutMs || 30000);
  options.signal = controller.signal;

  try {
    const res = await fetch(url, options);
    clearTimeout(timeoutId);
    
    // Check for HTTP 401 Unauthorized
    if (res.status === 401 && !url.includes('/api/login')) {
      localStorage.removeItem("jwt_token");
    }

    const contentType = res.headers.get("content-type") || "";
    let data;
    if (contentType.includes("application/json")) {
      data = await res.json();
    } else {
      const text = await res.text();
      data = { message: text };
    }

    if (!res.ok) {
      if (res.status === 401 && (data.detail === "Token has expired" || data.detail === "Invalid authentication token")) {
        localStorage.removeItem("jwt_token");
        const btnText = document.getElementById('btnHeaderActionText');
        if (btnText) btnText.innerText = "Admin Auth";
        const authOverlay = document.getElementById('auth-modal-overlay');
        if (authOverlay) authOverlay.classList.remove('hidden');
        throw new Error("Admin session expired. Please sign in again (Username: admin, Password: admin123).");
      }
      throw new Error(data.detail || data.error || data.message || `HTTP ${res.status}`);
    }
    return data;
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      throw new Error(`Request timed out for endpoint: ${url}`);
    }
    console.error(`[API Client Error] ${url}:`, err);
    throw err;
  }
}

const api = {
  // --- Team A: Lead Intelligence APIs ---
  async searchLeads(keyword) {
    return fetchJSON(`/api/search?keyword=${encodeURIComponent(keyword)}`, { method: "POST" });
  },

  async getPipelineStatus() {
    return fetchJSON("/api/status");
  },

  async getLeads(params = {}) {
    const query = new URLSearchParams();
    if (params.category) query.append("category", params.category);
    if (params.keyword) query.append("keyword", params.keyword);
    if (params.domain) query.append("domain", params.domain);
    if (params.industry) query.append("industry", params.industry);
    if (params.limit) query.append("limit", params.limit);
    if (params.offset) query.append("offset", params.offset);

    const queryString = query.toString();
    return fetchJSON(`/api/leads${queryString ? `?${queryString}` : ""}`);
  },

  async getAllLeads() {
    return fetchJSON("/api/leads/all");
  },

  async createLead(leadData) {
    return fetchJSON("/api/leads", {
      method: "POST",
      body: leadData
    });
  },

  async getCategories() {
    return fetchJSON("/api/categories");
  },

  // --- Team A → Team B Dispatch Bridge ---
  async dispatchLeadQualification(identifier, payload = {}) {
    return fetchJSON(`/api/leads/${encodeURIComponent(identifier)}/dispatch-call`, {
      method: "POST",
      body: payload
    });
  },

  // --- Team B: Voice Agent & Telephony APIs ---
  async login(username, password) {
    const res = await fetchJSON("/api/login", {
      method: "POST",
      body: { username, password }
    });
    if (res.token) {
      localStorage.setItem("jwt_token", res.token);
    }
    return res;
  },

  async register(username, password) {
    return fetchJSON("/api/register", {
      method: "POST",
      body: { username, password }
    });
  },

  async joinLiveKit() {
    let token = localStorage.getItem("jwt_token");
    if (!token) {
      try {
        const loginRes = await this.login("admin", "admin123");
        token = loginRes.token;
      } catch (e) {
        console.warn("Auto-login notice for LiveKit:", e);
      }
    }
    return fetchJSON("/api/livekit/join", { method: "POST" });
  },

  async triggerOutboundCall(phoneNumber, extra = {}) {
    let token = localStorage.getItem("jwt_token");
    if (!token) {
      try {
        const loginRes = await this.login("admin", "admin123");
        token = loginRes.token;
      } catch (e) {
        console.warn("Auto-login notice for outbound telephony:", e);
      }
    }

    try {
      return await fetchJSON("/api/plivo/outbound", {
        method: "POST",
        body: { phoneNumber, ...extra }
      });
    } catch (err) {
      // If token expired or rejected, retry login once
      if ((err.message || "").includes("Not authenticated") || (err.message || "").includes("HTTP 401") || (err.message || "").includes("HTTP 403")) {
        try {
          const loginRes = await this.login("admin", "admin123");
          if (loginRes.token) {
            return await fetchJSON("/api/plivo/outbound", {
              method: "POST",
              body: { phoneNumber, ...extra }
            });
          }
        } catch (retryErr) {
          throw err;
        }
      }
      throw err;
    }
  },

  async hangupCall(callId) {
    return fetchJSON("/api/telephony/hangup", {
      method: "POST",
      body: { call_id: callId }
    });
  },

  async getCallHistory() {
    return fetchJSON("/api/call-history");
  },

  async getRecordings(params = {}) {
    const query = new URLSearchParams(params).toString();
    return fetchJSON(`/api/recordings${query ? '?' + query : ''}`);
  },

  async deleteRecording(recordingId) {
    return fetchJSON(`/api/recordings/${recordingId}`, {
      method: "DELETE"
    });
  },

  async uploadRecording(formData) {
    const response = await fetch("/api/recordings/upload", {
      method: "POST",
      body: formData
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to upload call recording");
    }
    return response.json();
  },

  async getHealth() {
    return fetchJSON("/health");
  }
};

window.api = api;
