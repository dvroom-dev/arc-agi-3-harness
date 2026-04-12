import { NextResponse } from "next/server";
import { controlFluxRun } from "@/lib/flux.server";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ runId: string }> | { runId: string } },
) {
  try {
    const { runId } = await context.params;
    const payload = await request.json() as { action?: "stop" | "continue" };
    const action = payload?.action;
    if (action !== "stop" && action !== "continue") {
      return NextResponse.json({ error: "action must be 'stop' or 'continue'" }, { status: 400 });
    }
    return NextResponse.json(await controlFluxRun(runId, action));
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}
