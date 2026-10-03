export const VISION_CONNECTION_STORAGE_KEY = "masterPromptLibrary.v2.visionConnection.v1";

export const VISION_PROVIDERS = Object.freeze([
  Object.freeze({
    id: "ollama",
    label: "Ollama (local)",
    endpoint: "http://127.0.0.1:11434/v1",
    defaultModel: "llava",
    keyRequired: false,
  }),
  Object.freeze({
    id: "openai",
    label: "OpenAI",
    endpoint: "https://api.openai.com/v1",
    defaultModel: "gpt-4o-mini",
    keyRequired: true,
  }),
  Object.freeze({
    id: "gemini",
    label: "Google Gemini",
    endpoint: "https://generativelanguage.googleapis.com/v1beta/openai",
    defaultModel: "",
    keyRequired: true,
  }),
  Object.freeze({
    id: "custom",
    label: "OpenAI-compatible",
    endpoint: "",
    defaultModel: "",
    keyRequired: false,
  }),
]);

const PROVIDER_IDS = new Set(VISION_PROVIDERS.map((provider) => provider.id));

function string(value) {
  return typeof value === "string" ? value.trim() : "";
}

export function visionProvider(providerId) {
  return VISION_PROVIDERS.find((provider) => provider.id === providerId)
    || VISION_PROVIDERS.find((provider) => provider.id === "custom");
}

export function defaultVisionConnection(providerId = "ollama") {
  const provider = visionProvider(providerId);
  return {
    provider: provider.id,
    apiEndpoint: provider.endpoint,
    apiKey: "",
    apiModel: provider.defaultModel,
    rememberApiKey: true,
  };
}

export function normalizeVisionConnection(value) {
  const source = value && typeof value === "object" ? value : {};
  const providerId = PROVIDER_IDS.has(source.provider) ? source.provider : "ollama";
  const defaults = defaultVisionConnection(providerId);
  return {
    provider: providerId,
    apiEndpoint: string(source.apiEndpoint) || defaults.apiEndpoint,
    apiKey: string(source.apiKey),
    apiModel: string(source.apiModel) || defaults.apiModel,
    rememberApiKey: source.rememberApiKey !== false,
  };
}

export function connectionForProvider(providerId, current = {}) {
  const provider = visionProvider(providerId);
  const source = normalizeVisionConnection(current);
  return {
    provider: provider.id,
    apiEndpoint: provider.endpoint || (provider.id === "custom" ? source.apiEndpoint : ""),
    apiKey: source.apiKey,
    apiModel: provider.defaultModel,
    rememberApiKey: source.rememberApiKey,
  };
}

export function loadVisionConnection(storage = globalThis?.localStorage) {
  try {
    const raw = storage?.getItem?.(VISION_CONNECTION_STORAGE_KEY);
    return normalizeVisionConnection(raw ? JSON.parse(raw) : null);
  } catch {
    return defaultVisionConnection();
  }
}

export function saveVisionConnection(connection, storage = globalThis?.localStorage) {
  const normalized = normalizeVisionConnection(connection);
  const payload = {
    ...normalized,
    apiKey: normalized.rememberApiKey ? normalized.apiKey : "",
  };
  try {
    storage?.setItem?.(VISION_CONNECTION_STORAGE_KEY, JSON.stringify(payload));
    return true;
  } catch {
    return false;
  }
}

export function forgetVisionConnection(storage = globalThis?.localStorage) {
  try {
    storage?.removeItem?.(VISION_CONNECTION_STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

export function normalizeVisionModels(models, currentModel = "") {
  const values = [];
  const seen = new Set();
  for (const candidate of [currentModel, ...(Array.isArray(models) ? models : [])]) {
    const model = string(candidate);
    if (!model || seen.has(model)) continue;
    seen.add(model);
    values.push(model);
  }
  return values;
}
