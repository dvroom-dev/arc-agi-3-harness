import { NextResponse } from "next/server";
import { listFluxRuns, startFluxRun } from "@/lib/flux.server";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json({ runs: await listFluxRuns() });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}

export async function POST(request: Request) {
  try {
    const payload = await request.json();
    return NextResponse.json(await startFluxRun(payload), { status: 202 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}
