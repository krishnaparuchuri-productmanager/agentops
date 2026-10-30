// AgentOps — API config
// Deployed: the API is served by the same Cloudflare Worker as this page (worker/index.ts), under /api.
// Opened from disk (file://): fall back to the local Python backend on localhost:8000.
window.AGENTOPS_API = window.location.protocol === "file:"
  ? "http://localhost:8000"
  : window.location.origin + "/api";
