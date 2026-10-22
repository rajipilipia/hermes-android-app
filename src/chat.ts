import {
  JsonRpcGatewayClient,
  type ConnectionState,
} from "./upstream/json-rpc-gateway";
import type {
  RpcMethods,
  SessionListRow,
  TranscriptMessage,
} from "./upstream/gateway-contract.generated";
import type { GatewayEvent } from "./upstream/gateway-events";
import { gatewayUrl } from "./security";
import { pcAuth, type PcAuth } from "./pc-auth";
export interface Message {
  role: string;
  text: string;
  rowId?: number | null;
}
export interface ChatState {
  status: string;
  connected: boolean;
  syncing: boolean;
  sessions: SessionListRow[];
  messages: Message[];
  runtimeId: string;
  storedId: string;
  title: string;
  busy: boolean;
  error: string;
  uncertain: boolean;
  draft: string;
}
export class ChatController {
  state: ChatState = {
    status: "offline",
    connected: false,
    syncing: false,
    sessions: [],
    messages: [],
    runtimeId: "",
    storedId: "",
    title: "New conversation",
    busy: false,
    error: "",
    uncertain: false,
    draft: "",
  };
  private listeners = new Set<() => void>();
  private url = "";
  private token = "";
  private pc: PcAuth | null = null;
  private active = false;
  private generation = 0;
  private selection = 0;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private attempts = 0;
  constructor(
    private client = new JsonRpcGatewayClient(),
    private retryMs = 1000,
  ) {
    this.client.onAny((e) => this.event(e));
    this.client.onState((s) => this.transportState(s));
  }
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };
  snapshot = () => this.state;
  private set(patch: Partial<ChatState>) {
    this.state = { ...this.state, ...patch };
    for (const fn of this.listeners) fn();
  }
  private call<K extends keyof RpcMethods>(
    method: K,
    params: RpcMethods[K]["params"],
  ): Promise<RpcMethods[K]["result"]> {
    return this.client.request(method, params as Record<string, unknown>);
  }
  private messages(rows: TranscriptMessage[]): Message[] {
    return rows
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({
        role: m.role,
        text: typeof m.text === "string" ? m.text : "",
        rowId: m.row_id,
      }));
  }
  private transportState(s: ConnectionState) {
    if (!this.active || (s !== "closed" && s !== "error")) return;
    this.set({
      connected: false,
      status: "reconnecting",
      syncing: false,
      uncertain: this.state.uncertain || this.state.busy,
      error: this.state.busy
        ? "Connection lost. Delivery is uncertain; prompts are never automatically resent."
        : "Connection lost. Reconnecting…",
    });
    this.schedule();
  }
  private schedule() {
    if (!this.active || this.retryTimer !== undefined) return;
    const delay = Math.min(
        this.retryMs * 2 ** Math.min(this.attempts++, 4),
        15000,
      ),
      gen = this.generation;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      void this.reconnect(gen);
    }, delay);
  }
  private async reconnect(gen: number) {
    if (!this.active || gen !== this.generation) return;
    try {
      await this.dial(gen);
      if (gen !== this.generation) return;
      if (this.state.runtimeId)
        await this.client.sessionReplayBarrier(this.state.runtimeId);
      await this.refresh();
      if (gen !== this.generation) return;
      if (this.state.storedId) await this.open(this.state.storedId);
      if (gen !== this.generation) return;
      this.attempts = 0;
      this.set({
        connected: true,
        status: "connected",
        error: this.state.uncertain
          ? "Reconnected. History refreshed. The interrupted prompt was not resent. Review before sending again."
          : "",
      });
    } catch (error) {
      if (gen !== this.generation) return;
      if (error instanceof Error && error.name === "PcSignInRequired") {
        this.disconnect();
        this.set({ error: "Sign in to this PC again. Your native login has expired." });
        return;
      }
      this.set({ connected: false, status: "reconnecting" });
      this.schedule();
    }
  }
  private streamIndex = -1;
  private hydration: { sid: string | null; events: GatewayEvent[] } | null = null;
  private event(e: GatewayEvent) {
    if (this.hydration && (this.hydration.sid === null || this.hydration.sid === e.session_id)) {
      this.hydration.events.push(e);
      return;
    }
    if (e.session_id !== this.state.runtimeId || this.state.syncing) return;
    const rows = [...this.state.messages];
    if (e.type === "message.start") {
      this.streamIndex = -1;
      this.set({ busy: true });
    }
    if (e.type === "message.delta") {
      const text = (e as GatewayEvent<"message.delta">).payload?.text ?? "";
      if (this.streamIndex < 0) {
        this.streamIndex = rows.length;
        rows.push({ role: "assistant", text: "" });
      }
      rows[this.streamIndex] = {
        ...rows[this.streamIndex],
        text: rows[this.streamIndex].text + text,
      };
      this.set({ messages: rows, busy: true });
    }
    if (e.type === "message.complete") {
      const p = (e as GatewayEvent<"message.complete">).payload;
      if (typeof p?.text === "string" && p.text) {
        if (this.streamIndex < 0)
          rows.push({ role: "assistant", text: p.text });
        else
          rows[this.streamIndex] = { ...rows[this.streamIndex], text: p.text };
      }
      this.streamIndex = -1;
      this.set({
        messages: rows,
        busy: false,
        error: p?.error ? "The turn failed: " + this.clean(p.error) : "",
        uncertain: false,
      });
    }
    if (e.type === "error") {
      this.streamIndex = -1;
      this.set({ busy: false, error: "Hermes reported a session error." });
    }
  }
  private clean(text: string) {
    return this.token ? text.split(this.token).join("[redacted]") : text;
  }
  setDraft(draft: string) {
    this.set({ draft });
  }
  async create() {
    const selection = ++this.selection,
      gen = this.generation;
    this.hydration = null;
    this.set({ syncing: true, error: "" });
    try {
      const r = await this.call("session.create", {
        source: "android-prototype",
        close_on_disconnect: false,
        hidden: false,
      });
      if (selection !== this.selection || gen !== this.generation) return;
      this.streamIndex = -1;
      this.set({
        runtimeId: r.session_id,
        storedId: r.stored_session_id,
        messages: this.messages(r.messages),
        title: "New conversation",
        busy: false,
        syncing: false,
        uncertain: false,
      });
    } catch (error) {
      if (selection !== this.selection || gen !== this.generation) return;
      this.set({
        syncing: false,
        error: "Could not create session. No prompt was sent.",
      });
      throw error;
    }
  }
  async send(text: string) {
    if (
      !text.trim() ||
      !this.state.connected ||
      this.state.syncing ||
      this.state.busy ||
      !this.state.runtimeId
    )
      throw new Error("Connect and open an idle conversation first.");
    const sid = this.state.runtimeId,
      gen = this.generation;
    this.streamIndex = -1;
    this.set({
      busy: true,
      error: "",
      draft: "",
      messages: [...this.state.messages, { role: "user", text }],
    });
    try {
      await this.call("prompt.submit", {
        session_id: sid,
        text,
        surface: "android-prototype",
      });
    } catch {
      if (gen !== this.generation || sid !== this.state.runtimeId) return;
      this.set({
        busy: false,
        uncertain: true,
        error:
          "Delivery is uncertain. This prompt will NOT be resent. Check session history before sending it again.",
      });
    }
  }
  async connectPc(auth: PcAuth = pcAuth) {
    return this.connect("wss://gateway.example.com/api/ws", "", false, auth);
  }
  private connectionStage = "secure socket";
  private async dial(gen: number) {
    this.connectionStage = this.pc ? "connection ticket" : "secure socket";
    const url = this.pc ? "wss://gateway.example.com/api/ws?ticket=" + encodeURIComponent(await this.pc.ticket()) : this.url;
    this.connectionStage = "secure socket";
    if (gen !== this.generation || !this.active) throw new Error("Connection cancelled.");
    await this.client.connect(url);
  }
  async connect(endpoint: string, token: string, debug = false, pc: PcAuth | null = null) {
    const url = gatewayUrl(endpoint, token, debug);
    this.disconnect();
    this.active = true;
    this.pc = pc;
    this.url = url;
    this.token = token;
    const gen = ++this.generation;
    this.set({
      status: "connecting",
      error: "",
      sessions: [],
      messages: [],
      runtimeId: "",
      storedId: "",
      busy: false,
      uncertain: false,
    });
    try {
      this.connectionStage = "PC sign-in";
      if (pc) await pc.signIn();
      await this.dial(gen);
      if (gen !== this.generation) return;
      this.connectionStage = "loading conversations";
      await this.refresh();
      if (gen !== this.generation) return;
      this.set({ connected: true, status: "connected" });
    } catch (error) {
      if (gen !== this.generation) return;
      const stage = this.connectionStage;
      const status = error instanceof Error ? error.message.match(/Gateway HTTP (\d{3})/)?.[1] : undefined;
      this.disconnect();
      this.set({ error: `Connection failed during ${stage}${status ? ` (Gateway HTTP ${status})` : ""}. Try connecting again.` });
      throw new Error(this.state.error);
    }
  }
  async refresh() {
    const gen = this.generation;
    const result = await this.call("session.list", {
      limit: 100,
      include_hidden: false,
    });
    if (this.active && gen === this.generation)
      this.set({ sessions: result.sessions });
  }
  async open(id: string) {
    const selection = ++this.selection,
      gen = this.generation;
    const buffered = { sid: null as string | null, events: [] as GatewayEvent[] };
    this.hydration = buffered;
    this.set({ syncing: true, error: "" });
    try {
      const result = await this.call("session.resume", {
        session_id: id,
        source: "android-prototype",
        inline_images: false,
        close_on_disconnect: false,
      });
      if (selection !== this.selection || gen !== this.generation) return;
      buffered.sid = result.session_id;
      buffered.events = buffered.events.filter(e => e.session_id === result.session_id);
      const history = await this.call("session.history", {
        session_id: result.session_id,
      });
      if (selection !== this.selection || gen !== this.generation) return;
      const rows = this.messages(history.messages),
        inflight = result.inflight;
      const completionIndex = buffered.events.reduce(
        (index, e, i) => (e.type === "message.complete" ? i : index),
        -1,
      );
      const complete =
        completionIndex >= 0
          ? (
              buffered.events[
                completionIndex
              ] as GatewayEvent<"message.complete">
            ).payload
          : undefined;
      const alreadyDurable =
        typeof complete?.text === "string" &&
        rows.at(-1)?.role === "assistant" &&
        rows.at(-1)?.text === complete.text;
      this.streamIndex = -1;
      if (result.running && inflight && !alreadyDurable) {
        if (
          inflight.user &&
          !(rows.at(-1)?.role === "user" && rows.at(-1)?.text === inflight.user)
        )
          rows.push({ role: "user", text: inflight.user });
        if (inflight.assistant) {
          this.streamIndex = rows.length;
          rows.push({ role: "assistant", text: inflight.assistant });
        }
      }
      this.set({
        runtimeId: result.session_id,
        storedId: result.stored_session_id || id,
        messages: rows,
        title:
          this.state.sessions.find((s) => s.id === id)?.title || "Conversation",
        busy: result.running === true && !alreadyDurable,
        syncing: false,
      });
      if (this.hydration === buffered) this.hydration = null;
      for (const event of alreadyDurable
        ? buffered.events.slice(completionIndex + 1)
        : buffered.events)
        this.event(event);
    } catch (error) {
      if (selection !== this.selection || gen !== this.generation) return;
      this.hydration = null;
      this.set({ syncing: false, error: "Unable to open this session." });
      throw error;
    }
  }
  async signOut() {
    const auth = this.pc;
    this.disconnect();
    await auth?.signOut();
  }
  disconnect() {
    this.active = false;
    this.pc = null;
    this.generation++;
    this.selection++;
    if (this.retryTimer !== undefined) clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
    this.attempts = 0;
    this.client.close();
    this.url = "";
    this.token = "";
    this.hydration = null;
    this.streamIndex = -1;
    this.set({
      connected: false,
      status: "offline",
      syncing: false,
      messages: [],
      sessions: [],
      runtimeId: "",
      storedId: "",
      draft: "",
      busy: false,
      uncertain: false,
      error: "",
      title: "New conversation",
    });
  }
}
