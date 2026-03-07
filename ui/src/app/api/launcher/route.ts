import { NextResponse } from "next/server";
import { launchRun, readRecentRunParams } from "@/lib/runParams.server";
import { summarizeRunLaunchParams } from "@/lib/runParams";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  try {
    const recentParams = await readRecentRunParams();
    return NextResponse.json({
      recentParams,
      recentSummary: summarizeRunLaunchParams(recentParams),
    });
  } catch (error) {
    return NextResponse.json(
      { error: String(error) },
      { status: 500 }
    );
  }
}

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const result = await launchRun(body?.params ?? body);
    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 400 }
    );
  }
}
