// API access shared by all modules.
//
// Paths are relative ("api/...") so the same build works served from the
// root (local server) and from a subpath (ahmednassem.com/projects/theline/app/).
//
// Bring-your-own-key: when the server has no stored keys (hosted), the
// visitor's keys live in localStorage and ride along as headers on every
// request :  used transiently by the server, never stored there.
//
// Two LLM keys can be stored (claude + chatgpt/openai-compatible); the one
// set most recently is active, falling back to whichever exists.

const LS = {
  claude: "line-key-claude",
  openai: "line-key-openai",
  eleven: "line-key-eleven",
  active: "line-llm-active",
  model: "line-llm-model",
  url: "line-llm-url",
};

// one-time migration from the earlier single-key layout
if (localStorage.getItem("line-key-llm") && !localStorage.getItem(LS.claude)) {
  localStorage.setItem(LS.claude, localStorage.getItem("line-key-llm"));
  localStorage.removeItem("line-key-llm");
}

export const DEFAULT_MODEL = { claude: "claude-sonnet-4-6", openai: "gpt-4o" };

export function getLocal(name) {
  return localStorage.getItem(LS[name]) || "";
}

export function setLocal(name, value) {
  localStorage.setItem(LS[name], value);
}

export function setLocalKey(provider, key) {
  localStorage.setItem(LS[provider], key);
  localStorage.setItem(LS.active, provider); // last saved wins
}

export function clearLocalKeys() {
  for (const n of ["claude", "openai", "eleven", "active"]) localStorage.removeItem(LS[n]);
}

// which LLM the requests should use right now (null when no key at all)
export function activeLlm() {
  const claude = getLocal("claude");
  const openai = getLocal("openai");
  let provider = getLocal("active") || (claude ? "claude" : "openai");
  if (provider === "claude" && !claude) provider = "openai";
  if (provider === "openai" && !openai) provider = "claude";
  const key = provider === "claude" ? claude : openai;
  if (!key) return null;
  return {
    provider,
    key,
    model: getLocal("model") || DEFAULT_MODEL[provider],
    base_url: getLocal("url") || "https://api.openai.com/v1",
  };
}

export function hasLocalLlmKey() {
  return !!activeLlm();
}

export function apiHeaders(extra = {}) {
  const h = { ...extra };
  const llm = activeLlm();
  if (llm) {
    h["x-llm-key"] = llm.key;
    h["x-llm-provider"] = llm.provider;
    h["x-llm-model"] = llm.model;
    if (llm.provider === "openai") h["x-llm-base-url"] = llm.base_url;
  }
  const eleven = getLocal("eleven");
  if (eleven) h["x-eleven-key"] = eleven;
  return h;
}

export function apiFetch(path, options = {}) {
  return fetch(path, { ...options, headers: apiHeaders(options.headers || {}) });
}

export function maskKey(v) {
  if (!v) return "";
  if (v.length <= 12) return v.slice(0, 2) + "..." + v.slice(-2);
  return v.slice(0, 7) + "..." + v.slice(-4);
}
