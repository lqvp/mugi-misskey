import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import worker, { MisskeyStream } from "../worker.js";

const env = {
  DEVIN_WEBHOOK_URL: "https://devin.example.com/hook",
  MISSKEY_ORIGIN: "https://misskey.example.com",
  BOT_USERNAME: "examplebot",
};

let calls;
let devinStatus;
const realFetch = globalThis.fetch;

beforeEach(() => {
  calls = [];
  devinStatus = 200;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response("ok", { status: devinStatus });
  };
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const hook = (init) => worker.fetch(new Request("https://relay.example.com/", init), env);

test("rejects non-POST", async () => {
  assert.equal((await hook({ method: "GET" })).status, 405);
});

test("rejects missing secret", async () => {
  assert.equal((await hook({ method: "POST", body: "{}" })).status, 401);
});

test("rejects invalid json", async () => {
  const res = await hook({ method: "POST", headers: { "X-Misskey-Hook-Secret": "s" }, body: "{" });
  assert.equal(res.status, 400);
});

test("rejects other servers", async () => {
  const body = JSON.stringify({ server: "https://evil.example.com" });
  const res = await hook({ method: "POST", headers: { "X-Misskey-Hook-Secret": "s" }, body });
  assert.equal(res.status, 403);
  assert.equal(calls.length, 0);
});

test("forwards with the secret moved to X-Webhook-Secret", async () => {
  const body = JSON.stringify({ server: env.MISSKEY_ORIGIN, type: "mention" });
  const res = await hook({ method: "POST", headers: { "X-Misskey-Hook-Secret": "s3cret" }, body });
  assert.equal(res.status, 200);
  assert.equal(calls[0].url, env.DEVIN_WEBHOOK_URL);
  assert.equal(calls[0].init.headers["X-Webhook-Secret"], "s3cret");
  assert.equal(calls[0].init.body, body);
});

test("passes Devin's error status through", async () => {
  devinStatus = 401;
  const body = JSON.stringify({ server: env.MISSKEY_ORIGIN });
  const res = await hook({ method: "POST", headers: { "X-Misskey-Hook-Secret": "bad" }, body });
  assert.equal(res.status, 401);
});

test("fails loudly when a var is missing", async () => {
  await assert.rejects(worker.fetch(new Request("https://relay.example.com/"), {}), /missing var/);
});

function fakeState(initial) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    storage: {
      async get(k) {
        return Array.isArray(k) ? new Map(k.map((x) => [x, data.get(x)])) : data.get(k);
      },
      async put(k, v) {
        if (typeof k === "object") for (const [a, b] of Object.entries(k)) data.set(a, b);
        else data.set(k, v);
      },
    },
  };
}

const reaction = (id) => ({
  id,
  type: "reaction",
  createdAt: "2026-01-01T00:00:00.000Z",
  reaction: ":star:",
  user: { id: "u1", username: "alice", host: null, name: "Alice", isBot: false },
  note: { id: "n1", text: "hi", cw: null, userId: "me", createdAt: "2026-01-01T00:00:00.000Z" },
});

test("stream forwards a new reaction and advances the cursor", async () => {
  const state = fakeState({ hookSecret: "hs", userId: "me", lastId: "a" });
  await new MisskeyStream(state, env).handle(reaction("b"));
  const sent = JSON.parse(calls[0].init.body);
  assert.equal(calls[0].init.headers["X-Webhook-Secret"], "hs");
  assert.equal(sent.type, "reaction");
  assert.equal(sent.hookId, "stream");
  assert.equal(sent.body.user.isBot, false);
  assert.equal(state.data.get("lastId"), "b");
});

test("stream skips old ids and other types", async () => {
  const stream = new MisskeyStream(fakeState({ hookSecret: "hs", lastId: "m" }), env);
  await stream.handle(reaction("a"));
  await stream.handle({ ...reaction("z"), type: "follow" });
  assert.equal(calls.length, 0);
});

test("stream keeps the cursor when Devin rejects", async () => {
  devinStatus = 500;
  const state = fakeState({ hookSecret: "hs", lastId: "a" });
  await assert.rejects(new MisskeyStream(state, env).handle(reaction("b")), /devin 500/);
  assert.equal(state.data.get("lastId"), "a");
});
