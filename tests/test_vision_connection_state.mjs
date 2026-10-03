import assert from "node:assert/strict";
import test from "node:test";

import {
  VISION_CONNECTION_STORAGE_KEY,
  connectionForProvider,
  defaultVisionConnection,
  forgetVisionConnection,
  loadVisionConnection,
  normalizeVisionConnection,
  normalizeVisionModels,
  saveVisionConnection,
} from "../web/vision_connection_state.mjs";

function storage(initial = {}, { fail = false } = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) { if (fail) throw new Error("storage unavailable"); return values.get(key) ?? null; },
    setItem(key, value) { if (fail) throw new Error("storage unavailable"); values.set(key, String(value)); },
    removeItem(key) { if (fail) throw new Error("storage unavailable"); values.delete(key); },
    values,
  };
}

test("the default connection is immediately useful for local Ollama", () => {
  assert.deepEqual(defaultVisionConnection(), {
    provider: "ollama",
    apiEndpoint: "http://127.0.0.1:11434/v1",
    apiKey: "",
    apiModel: "llava",
    rememberApiKey: true,
  });
});

test("provider changes replace endpoint/model while retaining the key preference", () => {
  assert.deepEqual(connectionForProvider("openai", {
    provider: "ollama",
    apiEndpoint: "http://127.0.0.1:11434/v1",
    apiKey: "secret",
    apiModel: "llava",
    rememberApiKey: false,
  }), {
    provider: "openai",
    apiEndpoint: "https://api.openai.com/v1",
    apiKey: "secret",
    apiModel: "gpt-4o-mini",
    rememberApiKey: false,
  });
});

test("saved connections round-trip and can omit or forget the secret", () => {
  const state = storage();
  const connection = normalizeVisionConnection({
    provider: "gemini",
    apiEndpoint: "https://generativelanguage.googleapis.com/v1beta/openai",
    apiKey: "secret",
    apiModel: "gemini-vision",
    rememberApiKey: true,
  });
  assert.equal(saveVisionConnection(connection, state), true);
  assert.equal(loadVisionConnection(state).apiKey, "secret");

  assert.equal(saveVisionConnection({ ...connection, rememberApiKey: false }, state), true);
  assert.equal(JSON.parse(state.values.get(VISION_CONNECTION_STORAGE_KEY)).apiKey, "");
  assert.equal(loadVisionConnection(state).apiKey, "");

  assert.equal(forgetVisionConnection(state), true);
  assert.equal(state.values.has(VISION_CONNECTION_STORAGE_KEY), false);
});

test("malformed or unavailable storage falls back without throwing", () => {
  const malformed = storage({ [VISION_CONNECTION_STORAGE_KEY]: "{not-json" });
  assert.deepEqual(loadVisionConnection(malformed), defaultVisionConnection());
  assert.deepEqual(loadVisionConnection(storage({}, { fail: true })), defaultVisionConnection());
  assert.equal(saveVisionConnection(defaultVisionConnection(), storage({}, { fail: true })), false);
});

test("model options preserve the active model and remove duplicates", () => {
  assert.deepEqual(normalizeVisionModels(["zeta", "alpha", "zeta", ""], "saved-model"), [
    "saved-model", "zeta", "alpha",
  ]);
});
