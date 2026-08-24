"use client";

import { useCallback, useEffect, useState } from "react";
import { AgentActivityFeed } from "@/components/AgentActivityFeed";
import { AnalysisReport } from "@/components/AnalysisReport";
import { ChartPanel } from "@/components/ChartPanel";
import { DatasetSummary } from "@/components/DatasetSummary";
import { EvidenceExplorer } from "@/components/EvidenceExplorer";
import { FileUpload } from "@/components/FileUpload";
import { QuestionInput } from "@/components/QuestionInput";
import { ReasoningTrace } from "@/components/ReasoningTrace";
import {
  askQuestion,
  cancelAnalysis,
  createSession,
  getSession,
  pingHealth,
  SessionGoneError,
  streamSession,
  waitForBackend,
  type AgentEvent,
  type ChartSpec,
  type Claim,
  type DatasetProfile,
  type Evidence,
  type Explanation,
} from "@/lib/api";

type BackendStatus = "checking" | "waking" | "ready" | "unreachable";

/**
 * A free-tier instance idles out after 15 minutes without an *inbound*
 * request. Server-sent heartbeats don't count, so a long analysis needs the
 * client to check in periodically to stay alive.
 */
const KEEPALIVE_MS = 5 * 60 * 1000;

export default function HomePage() {
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [charts, setCharts] = useState<ChartSpec[]>([]);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("checking");

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (await pingHealth()) {
        if (!cancelled) setBackendStatus("ready");
        return;
      }
      if (!cancelled) setBackendStatus("waking");
      const ok = await waitForBackend();
      if (!cancelled) setBackendStatus(ok ? "ready" : "unreachable");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!running || !sessionId) return;
    const timer = setInterval(() => {
      void getSession(sessionId).catch(() => {});
    }, KEEPALIVE_MS);
    return () => clearInterval(timer);
  }, [running, sessionId]);

  const handleSessionGone = useCallback(() => {
    setDatasetId(null);
    setProfile(null);
    setFilename(null);
    setSessionId(null);
    setRunning(false);
    setEvents([]);
    setCharts([]);
    setExplanation(null);
    setSelectedEvidence(null);
    setError("The analysis server restarted and lost the uploaded data. Upload the CSV again to continue.");
  }, []);

  const onUploaded = useCallback(
    async (id: string, p: DatasetProfile, name: string) => {
      setDatasetId(id);
      setProfile(p);
      setFilename(name);
      setExplanation(null);
      setCharts([]);
      setEvents([]);
      setSelectedEvidence(null);
      setError(null);
      try {
        const session = await createSession(id);
        setSessionId(session.session_id);
      } catch (e) {
        if (e instanceof SessionGoneError) handleSessionGone();
        else setError(e instanceof Error ? e.message : "Failed to create session");
      }
    },
    [handleSessionGone]
  );

  const onAsk = useCallback(
    async (question: string) => {
      if (!datasetId) return;
      setRunning(true);
      setError(null);
      setEvents([]);
      setCharts([]);
      setExplanation(null);
      setSelectedEvidence(null);

      try {
        const session = await createSession(datasetId);
        setSessionId(session.session_id);

        const es = streamSession(
          session.session_id,
          (event) => {
            if (event.type === "ping") return;
            setEvents((prev) => [...prev, event]);
            if (event.type === "chart" && event.spec) {
              setCharts((prev) => [...prev, event.spec as ChartSpec]);
            }
            // `step_error` is a step that failed and was recorded; the run
            // carries on and reports what it could establish.
            if (event.type === "error") {
              setError(event.message || "Analysis failed");
              setRunning(false);
              es.close();
            }
            if (event.type === "done") {
              void getSession(session.session_id)
                .then((s) => {
                  if (s.explanation) setExplanation(s.explanation);
                  if (s.charts) setCharts(s.charts);
                  setRunning(false);
                })
                .catch((e) => {
                  if (e instanceof SessionGoneError) handleSessionGone();
                  else setError("Could not load the finished report");
                  setRunning(false);
                });
              es.close();
            }
          },
          (err) => {
            setError(err.message);
            setRunning(false);
          }
        );

        await askQuestion(session.session_id, question);
      } catch (e) {
        if (e instanceof SessionGoneError) {
          handleSessionGone();
          return;
        }
        setError(e instanceof Error ? e.message : "Failed to start");
        setRunning(false);
      }
    },
    [datasetId, handleSessionGone]
  );

  function handleSelectClaim(claim: Claim) {
    if (!explanation) return;
    const first = claim.evidence_ids[0];
    const ev = explanation.evidence.find((e) => e.id === first) || null;
    setSelectedEvidence(ev);
  }

  return (
    <main className="mx-auto min-h-screen max-w-6xl px-4 py-8">
      <header className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
          Autonomous Data Analyst
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          Upload a CSV, ask a question, and get an explainable, evidence-backed answer.
        </p>
      </header>

      {backendStatus === "waking" && (
        <p className="mb-6 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          Waking up the analysis server. This takes up to a minute on the first request.
        </p>
      )}

      {backendStatus === "unreachable" && (
        <p className="mb-6 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
          The analysis server is not responding. Reload the page to try again.
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="space-y-4">
          <FileUpload onUploaded={onUploaded} />

          {profile && filename && <DatasetSummary filename={filename} profile={profile} />}

          {datasetId && (
            <QuestionInput disabled={running || !datasetId} onSubmit={onAsk} />
          )}

          {running && sessionId && (
            <button
              type="button"
              onClick={() => {
                void cancelAnalysis(sessionId);
                setRunning(false);
              }}
              className="text-xs text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
            >
              Stop this analysis
            </button>
          )}

          {error && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
              {error}
            </p>
          )}

          <AgentActivityFeed events={events} />
          {explanation && <ReasoningTrace steps={explanation.reasoning_trace} />}
        </section>

        <section className="space-y-4">
          {running && !explanation && (
            <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-700 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-200">
              Agent is analyzing…
            </div>
          )}

          {explanation && (
            <>
              <AnalysisReport
                explanation={explanation}
                selectedEvidenceId={selectedEvidence?.id ?? null}
                onSelectClaim={handleSelectClaim}
                onSelectEvidence={setSelectedEvidence}
              />
              <EvidenceExplorer evidence={selectedEvidence} />
            </>
          )}

          <ChartPanel charts={charts} />
        </section>
      </div>
    </main>
  );
}
