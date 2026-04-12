import { NextResponse } from "next/server";
import { readFluxRunDetail } from "@/lib/flux.server";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ runId: string }> | { runId: string } },
) {
  try {
    const { runId } = await context.params;
    const detail = await readFluxRunDetail(runId);
    if (!detail) {
      return NextResponse.json({ error: `run not found: ${runId}` }, { status: 404 });
    }
    return NextResponse.json(detail);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}
