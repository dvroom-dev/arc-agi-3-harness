import { NextResponse } from "next/server";
import { readFluxSessionDetail } from "@/lib/flux.server";
import type { FluxSessionType } from "@/lib/types";

export const dynamic = "force-dynamic";

function isSessionType(value: string): value is FluxSessionType {
  return value === "solver" || value === "modeler" || value === "bootstrapper";
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ runId: string; sessionType: string; sessionId: string }> | { runId: string; sessionType: string; sessionId: string } },
) {
  try {
    const { runId, sessionType, sessionId } = await context.params;
    if (!isSessionType(sessionType)) {
      return NextResponse.json({ error: `invalid session type: ${sessionType}` }, { status: 400 });
    }
    const detail = await readFluxSessionDetail(runId, sessionType, sessionId);
    if (!detail) {
      return NextResponse.json({ error: `session not found: ${sessionType}/${sessionId}` }, { status: 404 });
    }
    return NextResponse.json(detail);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}
