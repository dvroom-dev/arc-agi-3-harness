export function sessionStatusClasses(status: string): string {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "running") return "bg-emerald-500/15 text-emerald-300 border-emerald-400/30";
  if (normalized === "failed") return "bg-rose-500/15 text-rose-300 border-rose-400/30";
  if (normalized === "stopped") return "bg-amber-500/15 text-amber-300 border-amber-400/30";
  if (normalized === "idle") return "bg-white/8 text-white/65 border-white/10";
  return "bg-sky-500/15 text-sky-300 border-sky-400/30";
}

export default function SessionStatusBadge({ status }: { status: string }) {
  return (
    <span className={`rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.14em] ${sessionStatusClasses(status)}`}>
      {status}
    </span>
  );
}
