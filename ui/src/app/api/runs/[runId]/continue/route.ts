import { NextResponse } from "next/server";
import { continueRun } from "@/lib/runParams.server";
import { findHarnessProcessForRun } from "@/lib/runState.server";

export const dynamic = "force-dynamic";

export async function POST(
  _request: Request,
  context: { params: Promise<{ runId: string }> }
) {
  try {
    const { runId } = await context.params;
    const active = await findHarnessProcessForRun(runId);
    if (active) {
      return NextResponse.json(
        { error: `Run ${runId} is already active (pid ${active.pid}).` },
        { status: 409 }
      );
    }
    const result = await continueRun(runId);
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 400 }
    );
  }
}
