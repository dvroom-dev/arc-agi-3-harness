"use client";

import { useState, useEffect, useRef } from "react";
import { ArcGrid } from "./ArcGrid";
import { Play, Pause, SkipBack, SkipForward, ChevronLeft, ChevronRight } from "lucide-react";

interface LevelSequences {
  level: number;
  sequences: {
    id: string;
    actionCount: number;
    endReason: string;
    actions: { step: number; action: string }[];
  }[];
}

interface StepData {
  action: string;
  step: number;
  beforeGrid: number[][] | null;
  afterGrid: number[][] | null;
  stateBefore: string;
  stateAfter: string;
  levelsBefore: number;
  levelsAfter: number;
}

interface SequencePlayerProps {
  runId: string;
}

export function SequencePlayer({ runId }: SequencePlayerProps) {
  const [levels, setLevels] = useState<LevelSequences[]>([]);
  const [selectedLevel, setSelectedLevel] = useState<number | null>(null);
  const [selectedSeq, setSelectedSeq] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState(1);
  const [stepData, setStepData] = useState<StepData | null>(null);
  const [playing, setPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(500); // ms between frames
  const playRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load sequences list
  useEffect(() => {
    fetch(`/api/runs/${runId}/sequences`)
      .then((r) => r.json())
      .then((d) => {
        const nextLevels = d.levels || [];
        const firstLevel = nextLevels[0] ?? null;
        setLevels(nextLevels);
        setSelectedLevel(firstLevel?.level ?? null);
        setSelectedSeq(firstLevel?.sequences[0]?.id ?? null);
        setCurrentStep(1);
        setStepData(null);
      })
      .catch(console.error);
  }, [runId]);

  const currentLevelData = levels.find((l) => l.level === selectedLevel);
  const currentSeqData = currentLevelData?.sequences.find(
    (s) => s.id === selectedSeq
  );
  const maxStep = currentSeqData?.actionCount || 0;

  // Load step grid
  useEffect(() => {
    if (selectedLevel === null || !selectedSeq) return;
    fetch(
      `/api/runs/${runId}/sequences?level=${selectedLevel}&sequence=${selectedSeq}&step=${currentStep}`
    )
      .then((r) => r.json())
      .then(setStepData)
      .catch(console.error);
  }, [runId, selectedLevel, selectedSeq, currentStep]);

  // Playback
  function stopPlayback() {
    setPlaying(false);
    if (playRef.current) {
      clearInterval(playRef.current);
      playRef.current = null;
    }
  }

  function startPlayback() {
    if (!maxStep) return;
    setPlaying(true);
    playRef.current = setInterval(() => {
      setCurrentStep((prev) => {
        if (prev >= maxStep) {
          stopPlayback();
          return prev;
        }
        return prev + 1;
      });
    }, playSpeed);
  }

  useEffect(() => {
    return () => {
      if (playRef.current) clearInterval(playRef.current);
    };
  }, []);

  if (levels.length === 0) {
    return (
      <div className="p-4 text-sm text-zinc-600">
        No action sequences recorded for this run
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 min-w-0">
      {/* Left: level/sequence picker */}
      <div className="w-44 border-r border-zinc-800 overflow-y-auto shrink-0">
        <div className="text-xs text-zinc-500 px-2 py-1.5 border-b border-zinc-800 font-medium">
          SEQUENCES
        </div>
        {levels.map((lev) => (
          <div key={lev.level}>
            <button
              onClick={() => {
                setSelectedLevel(lev.level);
                setSelectedSeq(lev.sequences[0]?.id ?? null);
                setCurrentStep(1);
                setStepData(null);
                stopPlayback();
              }}
              className={`w-full text-left px-2 py-1 text-xs font-medium ${
                selectedLevel === lev.level
                  ? "bg-zinc-800 text-zinc-200"
                  : "text-zinc-400 hover:bg-zinc-800/50"
              }`}
            >
              Level {lev.level}
              <span className="text-zinc-600 ml-1">
                ({lev.sequences.length})
              </span>
            </button>
            {selectedLevel === lev.level &&
              lev.sequences.map((seq) => (
                <button
                  key={seq.id}
                  onClick={() => {
                    setSelectedSeq(seq.id);
                    setCurrentStep(1);
                    setStepData(null);
                    stopPlayback();
                  }}
                  className={`w-full text-left px-4 py-0.5 text-xs ${
                    selectedSeq === seq.id
                      ? "bg-blue-900/30 text-blue-300"
                      : "text-zinc-500 hover:bg-zinc-800/30"
                  }`}
                >
                  {seq.id}
                  <span className="text-zinc-600 ml-1">
                    {seq.actionCount}a
                  </span>
                  {seq.endReason === "level_change" && (
                    <span className="text-green-500 ml-1">&#10003;</span>
                  )}
                </button>
              ))}
          </div>
        ))}
      </div>

      {/* Right: player */}
      <div className="flex-1 min-h-0 min-w-0 flex flex-col">
        {currentSeqData ? (
          <>
            {/* Action strip */}
            <div className="flex items-center gap-1 px-2 py-1.5 border-b border-zinc-800 overflow-x-auto shrink-0">
              {currentSeqData.actions.map((a) => (
                <button
                  key={a.step}
                  onClick={() => {
                    setCurrentStep(a.step);
                    stopPlayback();
                  }}
                  className={`px-1.5 py-0.5 text-xs font-mono rounded shrink-0 ${
                    currentStep === a.step
                      ? "bg-blue-600 text-white"
                      : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
                  }`}
                >
                  {a.action.replace("ACTION", "A")}
                </button>
              ))}
            </div>

            {/* Grid display */}
            <div className="flex-1 min-h-0 min-w-0 overflow-auto p-4">
              <div className="flex min-h-full min-w-full items-start justify-center">
                <div className="flex min-w-max flex-col gap-6">
                  {stepData?.beforeGrid && (
                    <div>
                      <div className="text-xs text-zinc-500 mb-1 text-center">
                        Before
                      </div>
                      <ArcGrid grid={stepData.beforeGrid} cellSize={5} className="rounded" />
                    </div>
                  )}
                  {stepData?.afterGrid && (
                    <div>
                      <div className="text-xs text-zinc-500 mb-1 text-center">
                        After &middot; {stepData.action}
                      </div>
                      <ArcGrid grid={stepData.afterGrid} cellSize={5} className="rounded" />
                    </div>
                  )}
                  {!stepData?.beforeGrid && !stepData?.afterGrid && (
                    <div className="text-sm text-zinc-600">
                      No grid data for this step
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Transport controls */}
            <div className="flex items-center justify-center gap-3 py-2 border-t border-zinc-800 shrink-0">
              <button
                onClick={() => {
                  setCurrentStep(1);
                  stopPlayback();
                }}
                className="text-zinc-400 hover:text-zinc-200"
              >
                <SkipBack size={16} />
              </button>
              <button
                onClick={() => {
                  setCurrentStep((p) => Math.max(1, p - 1));
                  stopPlayback();
                }}
                className="text-zinc-400 hover:text-zinc-200"
              >
                <ChevronLeft size={16} />
              </button>
              <button
                onClick={() => (playing ? stopPlayback() : startPlayback())}
                className="text-zinc-300 hover:text-white bg-zinc-800 rounded-full p-1.5"
              >
                {playing ? <Pause size={16} /> : <Play size={16} />}
              </button>
              <button
                onClick={() => {
                  setCurrentStep((p) => Math.min(maxStep, p + 1));
                  stopPlayback();
                }}
                className="text-zinc-400 hover:text-zinc-200"
              >
                <ChevronRight size={16} />
              </button>
              <button
                onClick={() => {
                  setCurrentStep(maxStep);
                  stopPlayback();
                }}
                className="text-zinc-400 hover:text-zinc-200"
              >
                <SkipForward size={16} />
              </button>
              <span className="text-xs text-zinc-500 ml-2">
                {currentStep}/{maxStep}
              </span>
              <select
                value={playSpeed}
                onChange={(e) => setPlaySpeed(parseInt(e.target.value))}
                className="bg-zinc-800 border border-zinc-700 rounded text-xs text-zinc-400 px-1 py-0.5 ml-2"
              >
                <option value={200}>5x</option>
                <option value={500}>2x</option>
                <option value={1000}>1x</option>
                <option value={2000}>0.5x</option>
              </select>
            </div>

            {/* Step info */}
            {stepData && (
              <div className="text-xs text-zinc-500 px-3 py-1 border-t border-zinc-800/50 shrink-0">
                Step {stepData.step}: {stepData.action} &middot;{" "}
                {stepData.stateBefore} → {stepData.stateAfter}
                {stepData.levelsAfter > stepData.levelsBefore && (
                  <span className="text-green-400 ml-2">LEVEL UP!</span>
                )}
              </div>
            )}
          </>
        ) : (
          <div className="flex items-center justify-center h-full text-sm text-zinc-600">
            Select a sequence to play
          </div>
        )}
      </div>
    </div>
  );
}
