/**
 * Cybernauts Unified API Client
 * Manages REST API calls for Lead Intelligence and AI Voice Agent
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

  try {
    const res = await fetch(url, options);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || data.error || `HTTP ${res.status}`);
    }
    return data;
  } catch (err) {
    console.error(`[API Error] ${url}:`, err);
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

  async getCategories() {
    return fetchJSON("/api/categories");
  },

  // --- Team B: Voice Agent & Auth APIs ---
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
    return fetchJSON("/api/livekit/join", { method: "POST" });
  },

  async triggerOutboundCall(phoneNumber) {
    return fetchJSON("/api/twilio/outbound", {
      method: "POST",
      body: { phoneNumber }
    });
  },

  async getCallHistory() {
    return fetchJSON("/api/call-history");
  }
};

window.api = api;
