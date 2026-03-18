export interface ParsedSupervisorResponse {
  decision: string | null;
  payload: Record<string, unknown> | null;
  modeAssessment: Record<string, unknown> | null;
  reasoning: string | null;
  errorKind: string | null;
  errorMessage: string | null;
  providerThreadId: string | null;
  providerTurnId: string | null;
}

export function parseSupervisorResponse(
  responseText: string | null
): ParsedSupervisorResponse {
  if (!responseText) {
    return {
      decision: null,
      payload: null,
      modeAssessment: null,
      reasoning: null,
      errorKind: null,
      errorMessage: null,
      providerThreadId: null,
      providerTurnId: null,
    };
  }

  try {
    const parsed = JSON.parse(responseText) as Record<string, unknown>;
    return {
      decision: typeof parsed.decision === "string" ? parsed.decision : null,
      payload:
        parsed.payload && typeof parsed.payload === "object"
          ? (parsed.payload as Record<string, unknown>)
          : null,
      modeAssessment:
        parsed.mode_assessment && typeof parsed.mode_assessment === "object"
          ? (parsed.mode_assessment as Record<string, unknown>)
          : null,
      reasoning: typeof parsed.reasoning === "string" ? parsed.reasoning.trim() : null,
      errorKind: typeof parsed.error_type === "string" ? parsed.error_type.trim() : null,
      errorMessage:
        typeof parsed.error === "string" && parsed.error.trim()
          ? parsed.error.trim()
          : typeof parsed.message === "string" && parsed.message.trim()
            ? parsed.message.trim()
            : null,
      providerThreadId:
        typeof parsed.provider_thread_id === "string"
          ? parsed.provider_thread_id.trim() || null
          : null,
      providerTurnId:
        typeof parsed.provider_turn_id === "string"
          ? parsed.provider_turn_id.trim() || null
          : null,
    };
  } catch {
    return {
      decision: null,
      payload: null,
      modeAssessment: null,
      reasoning: null,
      errorKind: null,
      errorMessage: null,
      providerThreadId: null,
      providerTurnId: null,
    };
  }
}

export function formatModeAssessmentBlock(
  modeAssessment: Record<string, unknown> | null
): string | null {
  if (!modeAssessment) return null;
  const lines: string[] = [];
  if (typeof modeAssessment.current_mode_stop_satisfied === "boolean") {
    lines.push(`current_mode_stop_satisfied: ${String(modeAssessment.current_mode_stop_satisfied)}`);
  }
  if (typeof modeAssessment.recommended_action === "string") {
    lines.push(`recommended_action: ${modeAssessment.recommended_action}`);
  }
  const ranked = Array.isArray(modeAssessment.candidate_modes_ranked)
    ? modeAssessment.candidate_modes_ranked
    : [];
  for (const candidate of ranked) {
    if (!candidate || typeof candidate !== "object") continue;
    const mode =
      typeof (candidate as { mode?: unknown }).mode === "string"
        ? (candidate as { mode: string }).mode
        : "(unknown)";
    const confidence =
      typeof (candidate as { confidence?: unknown }).confidence === "string"
        ? (candidate as { confidence: string }).confidence
        : "unknown";
    const evidence =
      typeof (candidate as { evidence?: unknown }).evidence === "string"
        ? (candidate as { evidence: string }).evidence.trim()
        : "";
    lines.push(`candidate_${mode}: ${confidence}${evidence ? ` - ${evidence}` : ""}`);
  }
  return lines.length > 0 ? lines.join("\n") : null;
}
