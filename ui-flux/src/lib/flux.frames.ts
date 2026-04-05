import fs from "node:fs/promises";
import path from "node:path";
import { parseHexGrid } from "@/lib/grid";
import type { FluxActionSummary, FluxFrameSnapshot } from "@/lib/types";

type JsonRecord = Record<string, unknown>;

async function readText(filePath: string): Promise<string | null> {
  try {
    return await fs.readFile(filePath, "utf8");
  } catch {
    return null;
  }
}

async function readJson<T = JsonRecord>(filePath: string): Promise<T | null> {
  const raw = await readText(filePath);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

async function readGridIfPresent(filePath: string | null): Promise<number[][] | null> {
  if (!filePath) return null;
  const raw = await readText(filePath);
  return raw ? parseHexGrid(raw) : null;
}

export async function readFrameSnapshots(gameDir: string): Promise<{
  frames: FluxFrameSnapshot[];
  actions: FluxActionSummary[];
  currentLevel: number | null;
}> {
  const levelCurrentDir = path.join(gameDir, "level_current");
  const meta = await readJson<JsonRecord>(path.join(levelCurrentDir, "meta.json"));
  const currentLevel = typeof meta?.level === "number" ? Number(meta.level) : null;
  const initialHex = await readText(path.join(levelCurrentDir, "initial_state.hex"));
  const currentHex = await readText(path.join(levelCurrentDir, "current_state.hex"));
  const frames: FluxFrameSnapshot[] = [];
  const actions: FluxActionSummary[] = [];
  let lastActionLabel: string | null = null;
  if (initialHex) {
    frames.push({
      id: "initial",
      label: "Initial",
      grid: parseHexGrid(initialHex),
      actionLabel: null,
      lastActionLabel: null,
      turnDir: null,
      changedPixels: 0,
      stepCount: 0,
    });
  }

  const levelDir = currentLevel ? path.join(gameDir, `level_${currentLevel}`) : levelCurrentDir;
  const sequenceRootCandidates = [
    path.join(levelCurrentDir, "sequences"),
    path.join(levelDir, "sequences"),
  ];
  let usedSequenceArtifacts = false;

  for (const sequenceRoot of sequenceRootCandidates) {
    const sequenceEntries = await fs.readdir(sequenceRoot, { withFileTypes: true }).catch(() => []);
    const sequenceJsonNames = sequenceEntries
      .filter((entry) => entry.isFile() && entry.name.startsWith("seq_") && entry.name.endsWith(".json"))
      .map((entry) => entry.name)
      .sort((left, right) => left.localeCompare(right));
    if (sequenceJsonNames.length === 0) continue;

    usedSequenceArtifacts = true;
    const sequences = await Promise.all(sequenceJsonNames.map(async (name) => {
      const payload = await readJson<JsonRecord>(path.join(sequenceRoot, name));
      return payload ? { name, payload } : null;
    }));
    const validSequences = sequences.filter(Boolean) as Array<{ name: string; payload: JsonRecord }>;

    for (let index = 0; index < validSequences.length; index += 1) {
      const { payload } = validSequences[index]!;
      const nextPayload = validSequences[index + 1]?.payload ?? null;
      const sequenceId = typeof payload.sequence_id === "string" ? String(payload.sequence_id) : `seq_${String(index + 1).padStart(4, "0")}`;
      const sequenceNumber = typeof payload.sequence_number === "number" ? Number(payload.sequence_number) : index + 1;
      const sequenceLabel = `sequence ${sequenceNumber}`;
      const sequenceActions = Array.isArray(payload.actions) ? payload.actions : [];

      for (const sequenceAction of sequenceActions) {
        if (!sequenceAction || typeof sequenceAction !== "object" || Array.isArray(sequenceAction)) continue;
        const action = sequenceAction as JsonRecord;
        const actionIndex = typeof action.action_index === "number" ? Number(action.action_index) : actions.length + 1;
        const actionName = typeof action.action_name === "string" && String(action.action_name).trim().length > 0
          ? String(action.action_name)
          : "UNKNOWN";
        const actionDisplayLabel = `${actionName} (${sequenceLabel})`;
        const files = action.files && typeof action.files === "object" && !Array.isArray(action.files)
          ? action.files as JsonRecord
          : {};
        const afterGrid = await readGridIfPresent(
          typeof files.after_state_hex === "string" ? path.join(levelDir, String(files.after_state_hex)) : null,
        );
        if (!afterGrid) continue;
        const actionDir = typeof files.meta_json === "string"
          ? path.dirname(path.join(levelDir, String(files.meta_json)))
          : levelDir;
        lastActionLabel = actionDisplayLabel;
        actions.push({
          step: actionIndex,
          actionLabel: actionDisplayLabel,
          changedPixels: typeof action.changed_pixels === "number" ? Number(action.changed_pixels) : 0,
          turnDir: path.relative(gameDir, actionDir),
          stateBefore: typeof action.state_before === "string" ? String(action.state_before) : "",
          stateAfter: typeof action.state_after === "string" ? String(action.state_after) : "",
        });
        frames.push({
          id: `${sequenceId}-action-${String(actionIndex)}`,
          label: `${actionIndex}. ${actionDisplayLabel}`,
          grid: afterGrid,
          actionLabel: actionDisplayLabel,
          lastActionLabel,
          turnDir: path.relative(gameDir, actionDir),
          changedPixels: typeof action.changed_pixels === "number" ? Number(action.changed_pixels) : 0,
          stepCount: actionIndex,
        });
      }

      if (payload.end_reason === "reset_level" && typeof payload.end_action_index === "number") {
        const resetIndex = Number(payload.end_action_index);
        const nextActions = nextPayload && Array.isArray(nextPayload.actions) ? nextPayload.actions : [];
        const nextFirst = nextActions[0] && typeof nextActions[0] === "object" && !Array.isArray(nextActions[0])
          ? nextActions[0] as JsonRecord
          : null;
        const nextFiles = nextFirst?.files && typeof nextFirst.files === "object" && !Array.isArray(nextFirst.files)
          ? nextFirst.files as JsonRecord
          : {};
        const resetGrid = await readGridIfPresent(
          typeof nextFiles.before_state_hex === "string"
            ? path.join(levelDir, String(nextFiles.before_state_hex))
            : path.join(levelCurrentDir, "initial_state.hex"),
        );
        if (!resetGrid) continue;
        lastActionLabel = `RESET (${sequenceLabel})`;
        actions.push({
          step: resetIndex,
          actionLabel: lastActionLabel,
          changedPixels: 0,
          turnDir: path.relative(gameDir, path.join(sequenceRoot, sequenceId)),
          stateBefore: typeof sequenceActions.at(-1) === "object" && sequenceActions.at(-1) && !Array.isArray(sequenceActions.at(-1))
            ? String((sequenceActions.at(-1) as JsonRecord).state_after ?? "")
            : "",
          stateAfter: typeof nextFirst?.state_before === "string" ? String(nextFirst.state_before) : "NOT_FINISHED",
        });
        frames.push({
          id: `${sequenceId}-reset-${String(resetIndex)}`,
          label: `${resetIndex}. RESET (${sequenceLabel})`,
          grid: resetGrid,
          actionLabel: "RESET",
          lastActionLabel,
          turnDir: path.relative(gameDir, path.join(sequenceRoot, sequenceId)),
          changedPixels: 0,
          stepCount: resetIndex,
        });
      }
    }
    break;
  }

  if (!usedSequenceArtifacts) {
    const turnEntries = await fs.readdir(levelCurrentDir, { withFileTypes: true }).catch(() => []);
    const turnDirs = turnEntries
      .filter((entry) => entry.isDirectory() && entry.name.startsWith("turn_"))
      .map((entry) => entry.name)
      .sort((left, right) => left.localeCompare(right))
      .slice(-120);
    for (const turnDirName of turnDirs) {
      const turnDir = path.join(levelCurrentDir, turnDirName);
      const turnMeta = await readJson<JsonRecord>(path.join(turnDir, "meta.json"));
      const afterHex = await readText(path.join(turnDir, "after_state.hex"));
      if (!turnMeta || !afterHex) continue;
      const actionIndex = typeof turnMeta.tool_turn === "number"
        ? Number(turnMeta.tool_turn)
        : Number(String(turnDirName).split("_").pop() || actions.length + 1);
      const actionLabel = typeof turnMeta.action_input_name === "string" && String(turnMeta.action_input_name).trim().length > 0
        ? String(turnMeta.action_input_name)
        : (typeof turnMeta.action_label === "string" ? String(turnMeta.action_label) : "UNKNOWN");
      lastActionLabel = actionLabel;
      actions.push({
        step: actionIndex,
        actionLabel,
        changedPixels: typeof turnMeta.changed_pixels === "number" ? Number(turnMeta.changed_pixels) : 0,
        turnDir: path.relative(gameDir, turnDir),
        stateBefore: typeof turnMeta.state_before_action === "string" ? String(turnMeta.state_before_action) : "",
        stateAfter: typeof turnMeta.state_after_action === "string" ? String(turnMeta.state_after_action) : "",
      });
      frames.push({
        id: `action-${actionIndex}`,
        label: `${actionIndex}. ${actionLabel}`,
        grid: parseHexGrid(afterHex),
        actionLabel,
        lastActionLabel,
        turnDir: path.relative(gameDir, turnDir),
        changedPixels: typeof turnMeta.changed_pixels === "number" ? Number(turnMeta.changed_pixels) : 0,
        stepCount: actionIndex,
      });
    }
  }

  if (currentHex) {
    const currentGrid = parseHexGrid(currentHex);
    const lastGrid = frames[frames.length - 1]?.grid;
    const sameAsLast = JSON.stringify(lastGrid) === JSON.stringify(currentGrid);
    if (!sameAsLast) {
      frames.push({
        id: "current",
        label: "Current",
        grid: currentGrid,
        actionLabel: lastActionLabel,
        lastActionLabel,
        turnDir: null,
        changedPixels: 0,
        stepCount: actions.length > 0 ? actions[actions.length - 1]!.step : 0,
      });
    }
  }

  return { frames, actions, currentLevel };
}
