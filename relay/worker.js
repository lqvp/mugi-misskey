// Cloudflare Worker: Misskey -> Devin automation relay.
// 1. POST /         : Misskey webhook -> Devin automation (moves X-Misskey-Hook-Secret to X-Webhook-Secret).
// 2. Durable Object : keeps the bot account's streaming connection open and forwards notification
//    types the webhook cannot deliver (reaction) to the same automation.
//    POST /stream/setup {"token": "...", "hookSecret"?: "...", "sinceId"?: "..."} stores the token
//    after checking it belongs to BOT_USERNAME. GET /stream/status shows state without secrets.
// Settings come from wrangler.toml [vars]: DEVIN_WEBHOOK_URL, MISSKEY_ORIGIN, BOT_USERNAME, MISSKEY_WEBHOOK_ID.
// Bump CODE_VERSION on every deploy: a Durable Object holding an outbound WebSocket keeps running old code otherwise.
const CODE_VERSION = "1";
const STREAM_TYPES = ["reaction"];
const UA = "misskey-devin-relay/1.0";
const ALARM_MS = 30_000;

function config(env) {
  for (const k of ["DEVIN_WEBHOOK_URL", "MISSKEY_ORIGIN", "BOT_USERNAME"]) {
    if (!env?.[k]) throw new Error(`missing var ${k}`);
  }
  return {
    devinUrl: env.DEVIN_WEBHOOK_URL,
    misskey: env.MISSKEY_ORIGIN.replace(/\/$/, ""),
    botUsername: env.BOT_USERNAME,
    webhookId: env.MISSKEY_WEBHOOK_ID,
  };
}

async function forwardToDevin(cfg, secret, body) {
  const res = await fetch(cfg.devinUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json", "User-Agent": UA, "X-Webhook-Secret": secret },
    body,
  });
  return res;
}

async function misskeyApi(cfg, endpoint, token, params = {}) {
  const res = await fetch(`${cfg.misskey}/api/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "User-Agent": UA, Authorization: `Bearer ${token}` },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error(`misskey ${endpoint} ${res.status}`);
  return res.status === 204 ? null : res.json();
}

export class MisskeyStream {
  constructor(state, env) {
    this.state = state;
    this.cfg = config(env);
    this.ws = null;
    this.connectedAt = null;
    this.lastEventAt = null;
    this.lastError = null;
  }

  async fetch(request) {
    const want = request.headers.get("X-Code-Version");
    if (want && want !== CODE_VERSION) {
      this.closeSocket();
      this.state.abort("code updated");
    }
    const url = new URL(request.url);
    if (url.pathname === "/stream/setup" && request.method === "POST") {
      let token, sinceId, hookSecret;
      try {
        ({ token, sinceId, hookSecret } = await request.json());
      } catch {
        return new Response("invalid json", { status: 400 });
      }
      if (typeof token !== "string" || token === "") return new Response("missing token", { status: 400 });
      let me;
      try {
        me = await misskeyApi(this.cfg, "i", token);
      } catch {
        return new Response("invalid token", { status: 401 });
      }
      if (me.username !== this.cfg.botUsername || me.host != null) return new Response("token is not BOT_USERNAME", { status: 403 });
      if (typeof hookSecret !== "string" || hookSecret === "") {
        if (!this.cfg.webhookId) return new Response("missing hookSecret", { status: 400 });
        hookSecret = (await misskeyApi(this.cfg, "i/webhooks/show", token, { webhookId: this.cfg.webhookId })).secret;
      }
      await this.state.storage.put({ token, hookSecret, userId: me.id });
      if (typeof sinceId === "string") await this.state.storage.put("lastId", sinceId);
      this.closeSocket();
      await this.ensureConnected();
      return Response.json(await this.status());
    }
    if (url.pathname === "/stream/status") {
      await this.ensureConnected();
      return Response.json(await this.status());
    }
    if (url.pathname === "/stream/tick") {
      await this.ensureConnected();
      return new Response("ok");
    }
    return new Response("not found", { status: 404 });
  }

  async alarm() {
    await this.ensureConnected();
    const token = await this.state.storage.get("token");
    if (token && this.ws) {
      try {
        await this.catchUp(token);
      } catch (e) {
        this.lastError = String(e);
      }
    }
  }

  async status() {
    const lastId = await this.state.storage.get("lastId");
    return {
      configured: (await this.state.storage.get("token")) != null,
      connected: this.ws != null,
      connectedAt: this.connectedAt,
      lastEventAt: this.lastEventAt,
      lastId: lastId ?? null,
      lastError: this.lastError,
      lastForward: this.lastForward ?? null,
      lastCatchUp: this.lastCatchUp ?? null,
      version: CODE_VERSION,
    };
  }

  closeSocket() {
    if (this.ws) {
      try {
        this.ws.close(1000, "reconnect");
      } catch {}
    }
    this.ws = null;
  }

  async ensureConnected() {
    if ((await this.state.storage.getAlarm()) == null) await this.state.storage.setAlarm(Date.now() + ALARM_MS);
    const token = await this.state.storage.get("token");
    if (!token || this.ws) return;
    try {
      const res = await fetch(`${this.cfg.misskey}/streaming`, {
        headers: { Upgrade: "websocket", "User-Agent": UA, Authorization: `Bearer ${token}` },
      });
      const ws = res.webSocket;
      if (!ws) throw new Error(`streaming upgrade failed ${res.status}`);
      ws.accept();
      this.ws = ws;
      this.connectedAt = new Date().toISOString();
      this.lastError = null;
      ws.addEventListener("message", (ev) => this.state.waitUntil(this.onMessage(ev.data)));
      const drop = (why) => {
        if (this.ws === ws) {
          this.ws = null;
          this.lastError = why;
        }
      };
      ws.addEventListener("close", (ev) => drop(`closed ${ev.code}`));
      ws.addEventListener("error", () => drop("error"));
      ws.send(JSON.stringify({ type: "connect", body: { channel: "main", id: "main" } }));
    } catch (e) {
      this.ws = null;
      this.lastError = String(e);
      return;
    }
    try {
      await this.catchUp(token);
    } catch (e) {
      this.lastError = String(e);
    }
  }

  async catchUp(token) {
    const lastId = await this.state.storage.get("lastId");
    if (lastId == null) {
      const latest = await misskeyApi(this.cfg, "i/notifications", token, { limit: 1, markAsRead: false });
      await this.state.storage.put("lastId", latest[0]?.id ?? "0");
      return;
    }
    const missed = await misskeyApi(this.cfg, "i/notifications", token, {
      limit: 50,
      sinceId: lastId,
      includeTypes: STREAM_TYPES,
      markAsRead: false,
    });
    this.lastCatchUp = { at: new Date().toISOString(), sinceId: lastId, found: missed.map((n) => n.id) };
    for (const n of missed.sort((a, b) => (a.id < b.id ? -1 : 1))) await this.handle(n);
  }

  async onMessage(data) {
    let msg;
    try {
      msg = JSON.parse(data);
    } catch {
      return;
    }
    this.lastEventAt = new Date().toISOString();
    if (msg.type === "channel" && msg.body?.id === "main" && msg.body.type === "notification") {
      await this.handle(msg.body.body);
    }
  }

  async handle(n) {
    if (!n || !STREAM_TYPES.includes(n.type)) return;
    const lastId = await this.state.storage.get("lastId");
    if (lastId != null && n.id <= lastId) return;
    const stored = await this.state.storage.get(["hookSecret", "userId"]);
    const hookSecret = stored.get("hookSecret");
    const userId = stored.get("userId");
    const payload = {
      server: this.cfg.misskey,
      hookId: "stream",
      userId,
      eventId: n.id,
      createdAt: Date.parse(n.createdAt),
      type: n.type,
      body: {
        user: n.user && { id: n.user.id, username: n.user.username, host: n.user.host, name: n.user.name, isBot: n.user.isBot === true },
        reaction: n.reaction,
        note: n.note && { id: n.note.id, text: n.note.text, cw: n.note.cw, userId: n.note.userId, createdAt: n.note.createdAt },
      },
    };
    const res = await forwardToDevin(this.cfg, hookSecret, JSON.stringify(payload));
    const detail = res.ok ? undefined : (await res.text()).slice(0, 300);
    this.lastForward = { at: new Date().toISOString(), id: n.id, devinStatus: res.status, detail };
    console.log(JSON.stringify({ via: "stream", type: n.type, id: n.id, devinStatus: res.status, detail }));
    if (!res.ok) throw new Error(`devin ${res.status}`);
    await this.state.storage.put("lastId", n.id);
  }
}

function streamStub(env) {
  const stub = env.STREAM.get(env.STREAM.idFromName("main"));
  return {
    fetch: (input) => {
      const req = new Request(input);
      req.headers.set("X-Code-Version", CODE_VERSION);
      return stub.fetch(req);
    },
  };
}

export default {
  async fetch(request, env) {
    const cfg = config(env);
    const url = new URL(request.url);
    if (url.pathname.startsWith("/stream/")) return streamStub(env).fetch(request);
    if (request.method !== "POST") return new Response("method not allowed", { status: 405 });
    const secret = request.headers.get("X-Misskey-Hook-Secret");
    if (!secret) return new Response("missing secret", { status: 401 });
    const body = await request.text();
    let payload;
    try {
      payload = JSON.parse(body);
    } catch {
      return new Response("invalid json", { status: 400 });
    }
    if (payload.server !== cfg.misskey) return new Response("unknown server", { status: 403 });
    const res = await forwardToDevin(cfg, secret, body);
    console.log(JSON.stringify({ type: payload.type, hookId: payload.hookId, devinStatus: res.status }));
    return new Response(await res.text(), { status: res.status });
  },

  async scheduled(_event, env, ctx) {
    ctx.waitUntil(streamStub(env).fetch("https://stream/stream/tick"));
  },
};
