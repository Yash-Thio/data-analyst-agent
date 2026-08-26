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

  const hasWorkspace = Boolean(profile && filename && datasetId);
  const hasResults = Boolean(explanation) || charts.length > 0;

  return (
    <div className="min-h-screen">
      <header className="chrome sticky top-0 z-20">
        <div className="mx-auto flex max-w-5xl items-start justify-between gap-4 px-6 py-4 sm:px-8">
          <div>
            <h1 className="display-title">Autonomous Data Analyst</h1>
            <p className="mt-1 text-sm text-[var(--label-secondary)]">
              Upload a CSV, ask a question, and get an explainable, evidence-backed answer.
            </p>
          </div>
          {backendStatus === "waking" && (
            <p className="status-pill banner-warn shrink-0">
              Waking up the analysis server. This takes up to a minute on the first request.
            </p>
          )}
          {backendStatus === "unreachable" && (
            <p className="status-pill banner-error shrink-0">
              The analysis server is not responding. Reload the page to try again.
            </p>
          )}
        </div>
      </header>

      <main className="mx-auto px-6 py-10 sm:px-8">
        {!hasWorkspace && (
          <div className="flex min-h-[calc(100vh-8.5rem)] items-center justify-center">
            <FileUpload onUploaded={onUploaded} />
          </div>
        )}

        {hasWorkspace && profile && filename && (
          <div className="mx-auto max-w-3xl space-y-10">
            <div className="grouped">
              <div className="grouped-row">
                <div className="mb-3 flex items-start justify-between gap-3">
                  <p className="section-title">Dataset</p>
                  <FileUpload compact onUploaded={onUploaded} />
                </div>
                <DatasetSummary filename={filename} profile={profile} />
              </div>
              <div className="grouped-row">
                <p className="section-title mb-3">Question</p>
                <QuestionInput disabled={running || !datasetId} onSubmit={onAsk} />
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  {running && sessionId && (
                    <button
                      type="button"
                      onClick={() => {
                        void cancelAnalysis(sessionId);
                        setRunning(false);
                      }}
                      className="btn btn-secondary"
                    >
                      Stop this analysis
                    </button>
                  )}
                  {running && !explanation && (
                    <p className="banner banner-info">Agent is analyzing…</p>
                  )}
                </div>
                {error && <p className="banner banner-error mt-3">{error}</p>}
              </div>
            </div>

            {events.length > 0 && (
              <section className="process space-y-3">
                <h2 className="section-title">Agent activity</h2>
                <AgentActivityFeed events={events} />
              </section>
            )}
          </div>
        )}

        {hasWorkspace && hasResults && (
          <div className="enter mx-auto mt-14 max-w-5xl space-y-12">
            {explanation && (
              <div
                className={
                  selectedEvidence
                    ? "grid gap-10 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)] lg:items-start"
                    : "space-y-4"
                }
              >
                <section className="space-y-4">
                  <AnalysisReport
                    explanation={explanation}
                    selectedEvidenceId={selectedEvidence?.id ?? null}
                    onSelectClaim={handleSelectClaim}
                    onSelectEvidence={setSelectedEvidence}
                  />
                  {!selectedEvidence && (
                    <p className="hint">
                      Click a claim or evidence ID to inspect SQL and result rows.
                    </p>
                  )}
                </section>
                {selectedEvidence && (
                  <aside className="surface p-5 sm:p-6">
                    <EvidenceExplorer evidence={selectedEvidence} />
                  </aside>
                )}
              </div>
            )}

            <ChartPanel charts={charts} />

            {explanation && explanation.reasoning_trace.length > 0 && (
              <details open className="process border-t border-[var(--separator)] pt-8">
                <summary className="section-title cursor-pointer">Reasoning trace</summary>
                <div className="mt-4">
                  <ReasoningTrace steps={explanation.reasoning_trace} />
                </div>
              </details>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
