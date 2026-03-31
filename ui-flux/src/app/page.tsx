"use client";

import { useEffect, useMemo, useState } from "react";
import ArcGrid from "@/components/ArcGrid";
import type { FluxRunDetail, FluxRunStartRequest, FluxRunSummary, FluxSessionDetail, FluxSessionSummary, FluxSessionType } from "@/lib/types";

const SESSION_TYPES: FluxSessionType[] = ["solver", "modeler", "bootstrapper"];
type MobileSection = "runs" | "state" | "sessions" | "detail";

function usePolling<T>(url: string | null, intervalMs: number, fallback: T): T {
  const [value, setValue] = useState<T>(fallback);
  useEffect(() => {
    if (!url) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const load = async () => {
      try {
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) return;
        const next = await response.json() as T;
        if (!stopped) setValue(next);
      } finally {
        if (!stopped) timer = setTimeout(load, intervalMs);
      }
    };
    void load();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs, url]);
  return value;
}

function RunList({
  runs,
  activeRunId,
  onSelect,
}: {
  runs: FluxRunSummary[];
  activeRunId: string | null;
  onSelect: (runId: string) => void;
}) {
  return (
    <>
      {runs.map((run) => (
        <button
          key={run.runId}
          onClick={() => onSelect(run.runId)}
          className={`w-full rounded-2xl border p-3 text-left ${activeRunId === run.runId ? "border-[var(--accent)] bg-white/8" : "border-white/8 bg-black/15 hover:bg-white/6"}`}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate font-mono text-sm text-[var(--foreground)]">{run.runId}</div>
              <div className="mt-1 text-xs text-[var(--muted)]">{run.gameId ?? "unknown game"}</div>
            </div>
            <div className={`rounded-full px-2 py-1 text-[10px] uppercase tracking-[0.16em] ${run.liveStatus === "running" ? "bg-emerald-500/15 text-emerald-300" : run.liveStatus === "stale" ? "bg-amber-500/15 text-amber-300" : "bg-white/10 text-white/60"}`}>{run.liveStatus}</div>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-[10px] uppercase tracking-[0.12em] text-white/45">
            {SESSION_TYPES.map((sessionType) => (
              <div key={sessionType} className="rounded-lg bg-black/20 px-2 py-1">
                <div>{sessionType}</div>
                <div className="mt-1 text-white/70">{run.active[sessionType].status}</div>
              </div>
            ))}
          </div>
        </button>
      ))}
    </>
  );
}

function StateView({
  detail,
  currentFrame,
  liveFrameIndex,
  followLive,
  setFollowLive,
  setManualFrameIndex,
  controlRun,
}: {
  detail: FluxRunDetail;
  currentFrame: FluxRunDetail["frames"][number] | null;
  liveFrameIndex: number;
  followLive: boolean;
  setFollowLive: (value: boolean) => void;
  setManualFrameIndex: (value: number) => void;
  controlRun: (action: "stop" | "continue") => Promise<void>;
}) {
  return (
    <div className="space-y-4">
      <section className="rounded-[24px] border border-white/10 bg-[var(--panel-alt)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-[var(--accent)]">Current Game State</div>
            <div className="mt-2 text-sm text-[var(--muted)]">
              Attempt {detail.currentAttemptId ?? "n/a"} · Level {detail.currentLevel ?? "?"} · {String(detail.currentState?.state ?? "unknown")}
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={() => void controlRun("continue")} className="rounded-xl border border-white/10 px-3 py-2 text-sm text-white/80">Continue</button>
            <button onClick={() => void controlRun("stop")} className="rounded-xl border border-[var(--danger)]/35 bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">Stop</button>
          </div>
        </div>
        <div className="mt-4 rounded-[20px] border border-white/10 bg-black/20 p-3">
          {currentFrame ? (
            <div className="flex min-h-[300px] items-center justify-center">
              <ArcGrid grid={currentFrame.grid} cellSize={5} />
            </div>
          ) : (
            <div className="flex min-h-[300px] items-center justify-center text-sm text-[var(--muted)]">No frame data yet</div>
          )}
        </div>
        <div className="mt-4">
          <input
            type="range"
            min={0}
            max={Math.max(0, detail.frames.length - 1)}
            value={liveFrameIndex}
            onChange={(event) => {
              setFollowLive(false);
              setManualFrameIndex(Number(event.target.value));
            }}
            className="w-full"
          />
          <div className="mt-2 flex items-center justify-between text-xs text-[var(--muted)]">
            <span>{detail.frames[liveFrameIndex]?.label ?? "n/a"}</span>
            <button
              onClick={() => {
                setFollowLive(true);
                setManualFrameIndex(Math.max(0, detail.frames.length - 1));
              }}
              className="rounded-lg border border-white/10 px-2 py-1 text-white/75"
            >
              {followLive ? "Following" : "Follow Current"}
            </button>
          </div>
        </div>
      </section>
      <section className="rounded-[24px] border border-white/10 bg-[var(--panel)] p-4">
        <div className="mb-3 text-xs uppercase tracking-[0.18em] text-white/45">Action Log</div>
        <div className="space-y-2">
          {detail.actions.map((action) => (
            <div key={`${action.turnDir}:${action.step}`} className="rounded-xl border border-white/8 bg-black/20 p-3">
              <div className="font-mono text-sm text-white">{action.actionLabel}</div>
              <div className="mt-1 text-xs text-[var(--muted)]">step {action.step} · changed {action.changedPixels} px</div>
              <div className="mt-2 text-[11px] text-white/55">{action.stateBefore} → {action.stateAfter}</div>
            </div>
          ))}
        </div>
      </section>
      <section className="rounded-[24px] border border-white/10 bg-[var(--panel)] p-4">
        <div className="mb-3 text-xs uppercase tracking-[0.18em] text-[var(--accent-2)]">Session Status</div>
        <div className="grid gap-3 md:grid-cols-3">
          {SESSION_TYPES.map((sessionType) => (
            <div key={sessionType} className="rounded-2xl border border-white/10 bg-white/4 p-4">
              <div className="text-sm font-semibold capitalize">{sessionType}</div>
              <div className="mt-2 text-2xl font-semibold text-white">{detail.active[sessionType].status}</div>
              <div className="mt-2 text-xs text-[var(--muted)]">queue {detail.queues[sessionType].length}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function SessionsView({
  detail,
  activeSessionKey,
  onSelect,
}: {
  detail: FluxRunDetail;
  activeSessionKey: string | null;
  onSelect: (sessionKey: string) => void;
}) {
  return (
    <div className="space-y-4">
      {SESSION_TYPES.map((sessionType) => (
        <section key={sessionType} className="rounded-[24px] border border-white/10 bg-[var(--panel)] p-4">
          <div className="mb-3 text-xs uppercase tracking-[0.16em] text-white/40">{sessionType}</div>
          <div className="space-y-2">
            {(detail.sessionHistory[sessionType] ?? []).map((session) => {
              const key = `${session.sessionType}:${session.sessionId}`;
              return (
                <button
                  key={key}
                  onClick={() => onSelect(key)}
                  className={`w-full rounded-xl border p-3 text-left ${activeSessionKey === key ? "border-[var(--accent)] bg-white/8" : "border-white/8 bg-black/15"}`}
                >
                  <div className="font-mono text-xs text-white">{session.sessionId}</div>
                  <div className="mt-1 text-[11px] text-[var(--muted)]">{session.provider ?? "?"} · {session.model ?? "?"}</div>
                  <div className="mt-2 text-[10px] uppercase tracking-[0.14em] text-white/55">{session.status}</div>
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

function SessionDetailView({ sessionDetail }: { sessionDetail: FluxSessionDetail }) {
  return (
    <div className="space-y-4">
      <section className="rounded-[24px] border border-white/10 bg-[var(--panel)] p-4">
        <div className="font-mono text-sm text-white">{sessionDetail.session?.sessionId}</div>
        <div className="mt-2 text-xs text-[var(--muted)]">{sessionDetail.session?.provider} · {sessionDetail.session?.model}</div>
      </section>
      <section className="rounded-[24px] border border-white/10 bg-[var(--panel)] p-4">
        <div className="mb-3 text-xs uppercase tracking-[0.16em] text-white/45">Messages</div>
        <div className="space-y-3">
          {sessionDetail.messages.map((message, index) => (
            <div key={index} className="rounded-xl border border-white/8 bg-white/4 p-3">
              <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--accent)]">{String(message.kind ?? "message")}</div>
              <pre className="mt-2 whitespace-pre-wrap break-words font-mono text-xs text-white/85">{typeof message.text === "string" ? message.text : JSON.stringify(message, null, 2)}</pre>
            </div>
          ))}
        </div>
      </section>
      <section className="rounded-[24px] border border-white/10 bg-[var(--panel)] p-4">
        <div className="mb-3 text-xs uppercase tracking-[0.16em] text-white/45">Tool Calls</div>
        <div className="space-y-3">
          {sessionDetail.toolEvents.map((event, index) => (
            <div key={index} className="rounded-xl border border-white/8 bg-white/4 p-3">
              <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--accent-2)]">{event.kind}</div>
              <div className="mt-1 text-xs text-white/90">{event.title}</div>
              {event.text ? <pre className="mt-2 whitespace-pre-wrap break-words font-mono text-[11px] text-white/70">{event.text}</pre> : null}
            </div>
          ))}
        </div>
      </section>
      <section className="rounded-[24px] border border-white/10 bg-[var(--panel)] p-4">
        <div className="mb-3 text-xs uppercase tracking-[0.16em] text-white/45">Prompt Inputs</div>
        <div className="space-y-3">
          {sessionDetail.prompts.map((prompt) => (
            <div key={prompt.fileName} className="rounded-xl border border-white/8 bg-white/4 p-3">
              <div className="font-mono text-xs text-white">{prompt.fileName}</div>
              <pre className="mt-2 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-white/70">{JSON.stringify(prompt.payload, null, 2)}</pre>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function Home() {
  const runsPayload = usePolling<{ runs: FluxRunSummary[] }>("/api/runs", 3000, { runs: [] });
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [followLive, setFollowLive] = useState(true);
  const [manualFrameIndex, setManualFrameIndex] = useState(0);
  const [selectedSessionKey, setSelectedSessionKey] = useState<string | null>(null);
  const [mobileSection, setMobileSection] = useState<MobileSection>("runs");
  const [form, setForm] = useState<FluxRunStartRequest>({
    gameId: "ls20",
    provider: "claude",
    operationMode: "OFFLINE",
    sessionName: "flux-ui",
  });
  const activeRunId = selectedRunId ?? runsPayload.runs[0]?.runId ?? null;

  const detail = usePolling<FluxRunDetail | null>(
    activeRunId ? `/api/runs/${activeRunId}` : null,
    2500,
    null,
  );

  const allSessions = useMemo(() => {
    if (!detail) return [] as FluxSessionSummary[];
    return SESSION_TYPES.flatMap((sessionType) => detail.sessionHistory[sessionType] ?? []);
  }, [detail]);

  const activeSessionKey = useMemo(() => {
    if (!detail) return null;
    if (selectedSessionKey && allSessions.some((session) => `${session.sessionType}:${session.sessionId}` === selectedSessionKey)) {
      return selectedSessionKey;
    }
    return SESSION_TYPES
      .map((sessionType) => detail.active[sessionType].sessionId ? `${sessionType}:${detail.active[sessionType].sessionId}` : null)
      .find(Boolean)
      ?? (allSessions[0] ? `${allSessions[0].sessionType}:${allSessions[0].sessionId}` : null);
  }, [allSessions, detail, selectedSessionKey]);

  const liveFrameIndex = followLive
    ? Math.max(0, (detail?.frames.length ?? 1) - 1)
    : Math.min(manualFrameIndex, Math.max(0, (detail?.frames.length ?? 1) - 1));

  const sessionDetail = usePolling<FluxSessionDetail | null>(
    activeRunId && activeSessionKey
      ? `/api/runs/${activeRunId}/sessions/${activeSessionKey.split(":")[0]}/${activeSessionKey.split(":")[1]}`
      : null,
    2500,
    null,
  );

  const currentFrame = detail?.frames[liveFrameIndex] ?? null;

  async function startRun() {
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(form),
    });
    if (!response.ok) return;
    const payload = await response.json() as { runId: string };
    setSelectedRunId(payload.runId);
    setFollowLive(true);
    setManualFrameIndex(0);
    setMobileSection("state");
  }

  async function controlRun(action: "stop" | "continue") {
    if (!activeRunId) return;
    await fetch(`/api/runs/${activeRunId}/control`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action }),
    });
  }

  const desktopRunList = (
    <RunList
      runs={runsPayload.runs}
      activeRunId={activeRunId}
      onSelect={(runId) => {
        setSelectedRunId(runId);
        setFollowLive(true);
        setManualFrameIndex(0);
      }}
    />
  );

  const desktopState = detail ? (
    <StateView
      detail={detail}
      currentFrame={currentFrame}
      liveFrameIndex={liveFrameIndex}
      followLive={followLive}
      setFollowLive={setFollowLive}
      setManualFrameIndex={setManualFrameIndex}
      controlRun={controlRun}
    />
  ) : (
    <div className="flex h-full items-center justify-center text-[var(--muted)]">Select or start a flux run.</div>
  );

  const desktopSessionDetail = sessionDetail ? (
    <SessionDetailView sessionDetail={sessionDetail} />
  ) : (
    <div className="text-sm text-[var(--muted)]">Select a session.</div>
  );

  return (
    <>
      <main className="flex h-dvh flex-col overflow-hidden lg:hidden">
        <header className="border-b border-white/10 bg-[var(--panel)] px-4 py-4">
          <div className="text-[11px] uppercase tracking-[0.24em] text-[var(--accent)]">Flux Monitor</div>
          <div className="mt-2 text-lg font-semibold text-[var(--foreground)]">Session Forge</div>
          <div className="mt-1 truncate font-mono text-xs text-[var(--muted)]">{detail?.runId ?? "No run selected"}</div>
          <div className="mt-4 grid grid-cols-4 gap-2">
            {([
              ["runs", "Runs"],
              ["state", "State"],
              ["sessions", "Sessions"],
              ["detail", "Detail"],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setMobileSection(key)}
                className={`rounded-xl px-3 py-2 text-xs font-semibold ${
                  mobileSection === key ? "bg-[var(--accent)] text-black" : "border border-white/10 bg-black/15 text-white/75"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </header>

        <section className="min-h-0 flex-1 overflow-auto p-4">
          {mobileSection === "runs" ? (
            <div className="space-y-4">
              <section className="rounded-[24px] border border-white/10 bg-[var(--panel)] p-4">
                <div className="mb-3 text-xs uppercase tracking-[0.2em] text-white/50">Start Run</div>
                <div className="space-y-3">
                  <input className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm" value={form.sessionName} onChange={(event) => setForm((value) => ({ ...value, sessionName: event.target.value }))} placeholder="run name prefix" />
                  <input className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm" value={form.gameId} onChange={(event) => setForm((value) => ({ ...value, gameId: event.target.value }))} placeholder="game id" />
                  <div className="grid grid-cols-2 gap-2">
                    <select className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm" value={form.provider} onChange={(event) => setForm((value) => ({ ...value, provider: event.target.value as FluxRunStartRequest["provider"] }))}>
                      <option value="claude">claude</option>
                      <option value="codex">codex</option>
                      <option value="mock">mock</option>
                    </select>
                    <select className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm" value={form.operationMode} onChange={(event) => setForm((value) => ({ ...value, operationMode: event.target.value as FluxRunStartRequest["operationMode"] }))}>
                      <option value="OFFLINE">OFFLINE</option>
                      <option value="ONLINE">ONLINE</option>
                      <option value="NORMAL">NORMAL</option>
                    </select>
                  </div>
                  <button onClick={() => void startRun()} className="w-full rounded-xl bg-[var(--accent)] px-3 py-2 text-sm font-semibold text-black">Start New Run</button>
                </div>
              </section>
              <div className="space-y-2">
                <RunList
                  runs={runsPayload.runs}
                  activeRunId={activeRunId}
                  onSelect={(runId) => {
                    setSelectedRunId(runId);
                    setFollowLive(true);
                    setManualFrameIndex(0);
                    setMobileSection("state");
                  }}
                />
              </div>
            </div>
          ) : null}

          {mobileSection === "state" ? desktopState : null}

          {mobileSection === "sessions" ? (
            detail ? (
              <SessionsView
                detail={detail}
                activeSessionKey={activeSessionKey}
                onSelect={(key) => {
                  setSelectedSessionKey(key);
                  setMobileSection("detail");
                }}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-[var(--muted)]">Select a run first.</div>
            )
          ) : null}

          {mobileSection === "detail" ? (
            sessionDetail ? <SessionDetailView sessionDetail={sessionDetail} /> : <div className="flex h-full items-center justify-center text-[var(--muted)]">Select a session.</div>
          ) : null}
        </section>
      </main>

      <main className="hidden h-dvh grid-cols-[320px_minmax(0,1fr)] overflow-hidden lg:grid">
        <aside className="border-r border-white/10 bg-[var(--panel)] backdrop-blur-xl">
          <div className="border-b border-white/10 px-5 py-4">
            <div className="text-xs uppercase tracking-[0.28em] text-[var(--accent)]">Flux Monitor</div>
            <h1 className="mt-2 text-2xl font-semibold text-[var(--foreground)]">Session Forge</h1>
            <p className="mt-2 text-sm text-[var(--muted)]">Runs, timelines, live sessions, and replay history for flux only.</p>
          </div>
          <div className="border-b border-white/10 px-5 py-4">
            <div className="mb-3 text-xs uppercase tracking-[0.2em] text-white/50">Start Run</div>
            <div className="space-y-3">
              <input className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm" value={form.sessionName} onChange={(event) => setForm((value) => ({ ...value, sessionName: event.target.value }))} placeholder="run name prefix" />
              <input className="w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm" value={form.gameId} onChange={(event) => setForm((value) => ({ ...value, gameId: event.target.value }))} placeholder="game id" />
              <div className="grid grid-cols-2 gap-2">
                <select className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm" value={form.provider} onChange={(event) => setForm((value) => ({ ...value, provider: event.target.value as FluxRunStartRequest["provider"] }))}>
                  <option value="claude">claude</option>
                  <option value="codex">codex</option>
                  <option value="mock">mock</option>
                </select>
                <select className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm" value={form.operationMode} onChange={(event) => setForm((value) => ({ ...value, operationMode: event.target.value as FluxRunStartRequest["operationMode"] }))}>
                  <option value="OFFLINE">OFFLINE</option>
                  <option value="ONLINE">ONLINE</option>
                  <option value="NORMAL">NORMAL</option>
                </select>
              </div>
              <button onClick={() => void startRun()} className="w-full rounded-xl bg-[var(--accent)] px-3 py-2 text-sm font-semibold text-black">Start New Run</button>
            </div>
          </div>
          <div className="min-h-0 overflow-auto p-3">
            {desktopRunList}
          </div>
        </aside>

        <section className="grid min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden">
          <header className="flex items-center justify-between gap-4 border-b border-white/10 bg-[var(--panel-alt)] px-5 py-4">
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-white/45">Selected Run</div>
              <div className="mt-1 font-mono text-lg">{detail?.runId ?? "No run selected"}</div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => void controlRun("continue")} disabled={!selectedRunId} className="rounded-xl border border-white/10 px-4 py-2 text-sm text-white/80 disabled:opacity-40">Continue</button>
              <button onClick={() => void controlRun("stop")} disabled={!activeRunId} className="rounded-xl border border-[var(--danger)]/35 bg-[var(--danger)]/10 px-4 py-2 text-sm text-[var(--danger)] disabled:opacity-40">Stop</button>
            </div>
          </header>

          <div className="grid min-h-0 min-w-0 grid-cols-[minmax(0,1.15fr)_minmax(420px,0.85fr)] overflow-hidden">
            <div className="min-h-0 overflow-auto p-5">
              {desktopState}
            </div>

            <aside className="min-h-0 border-l border-white/10 bg-[var(--panel)]">
              {detail ? (
                <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)]">
                  <div className="border-b border-white/10 p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-[var(--accent)]">Sessions</div>
                    <div className="mt-3 grid gap-3">
                      <SessionsView
                        detail={detail}
                        activeSessionKey={activeSessionKey}
                        onSelect={(key) => setSelectedSessionKey(key)}
                      />
                    </div>
                  </div>
                  <div className="min-h-0 overflow-auto p-4">
                    {desktopSessionDetail}
                  </div>
                </div>
              ) : null}
            </aside>
          </div>
        </section>
      </main>
    </>
  );
}
