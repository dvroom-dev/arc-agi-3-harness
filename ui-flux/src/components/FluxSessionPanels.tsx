import SessionStatusBadge from "@/components/SessionStatusBadge";
import type { FluxRunDetail, FluxSessionDetail, FluxSessionType } from "@/lib/types";

const SESSION_TYPES: FluxSessionType[] = ["solver", "modeler", "bootstrapper"];

export function SessionsView({
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
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <SessionStatusBadge status={session.status} />
                    <span className="text-[10px] uppercase tracking-[0.14em] text-white/45">
                      prompts {session.promptCount}
                    </span>
                    <span className="text-[10px] uppercase tracking-[0.14em] text-white/45">
                      replies {session.assistantMessageCount}
                    </span>
                  </div>
                  {session.stopReason ? (
                    <div className="mt-2 line-clamp-2 text-[11px] text-white/55">{session.stopReason}</div>
                  ) : null}
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

export function SessionDetailView({ sessionDetail }: { sessionDetail: FluxSessionDetail }) {
  return (
    <div className="space-y-4">
      <section className="rounded-[24px] border border-white/10 bg-[var(--panel)] p-4">
        <div className="font-mono text-sm text-white">{sessionDetail.session?.sessionId}</div>
        <div className="mt-2 text-xs text-[var(--muted)]">{sessionDetail.session?.provider} · {sessionDetail.session?.model}</div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <SessionStatusBadge status={sessionDetail.session?.status ?? "unknown"} />
          <span className="text-[10px] uppercase tracking-[0.14em] text-white/45">
            prompts {sessionDetail.session?.promptCount ?? 0}
          </span>
          <span className="text-[10px] uppercase tracking-[0.14em] text-white/45">
            user msgs {sessionDetail.session?.userMessageCount ?? 0}
          </span>
          <span className="text-[10px] uppercase tracking-[0.14em] text-white/45">
            replies {sessionDetail.session?.assistantMessageCount ?? 0}
          </span>
        </div>
        {sessionDetail.session?.stopReason ? (
          <div className="mt-3 rounded-xl border border-white/8 bg-black/20 p-3 text-[11px] text-white/65">
            {sessionDetail.session.stopReason}
          </div>
        ) : null}
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
