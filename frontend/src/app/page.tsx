"use client";

import { useCallback, useState } from "react";
import { AgentActivityFeed } from "@/components/AgentActivityFeed";
import { AnalysisReport } from "@/components/AnalysisReport";
import { ChartPanel } from "@/components/ChartPanel";
import { EvidenceExplorer } from "@/components/EvidenceExplorer";
import { FileUpload } from "@/components/FileUpload";
import { QuestionInput } from "@/components/QuestionInput";
import { ReasoningTrace } from "@/components/ReasoningTrace";
import {
  askQuestion,
  createSession,
  getSession,
  streamSession,
  type AgentEvent,
  type ChartSpec,
  type Claim,
  type DatasetProfile,
  type Evidence,
  type Explanation,
} from "@/lib/api";

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
      const session = await createSession(id);
      setSessionId(session.session_id);
    },
    []
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
            if (event.type === "error") {
              setError(event.message || "Analysis failed");
              setRunning(false);
              es.close();
            }
            if (event.type === "done") {
              void getSession(session.session_id).then((s) => {
                if (s.explanation) setExplanation(s.explanation);
                if (s.charts) setCharts(s.charts);
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
        setError(e instanceof Error ? e.message : "Failed to start");
        setRunning(false);
      }
    },
    [datasetId]
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

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="space-y-4">
          <FileUpload onUploaded={onUploaded} />

          {profile && (
            <div className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
              <p className="text-sm font-medium">
                {filename} · {profile.row_count} rows · {profile.column_count} columns
              </p>
              <div className="mt-2 flex flex-wrap gap-1">
                {profile.columns.map((c) => (
                  <span
                    key={c.name}
                    className="rounded bg-zinc-100 px-2 py-0.5 text-xs dark:bg-zinc-800"
                    title={c.role}
                  >
                    {c.name}
                    <span className="ml-1 text-zinc-400">{c.role}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {datasetId && (
            <QuestionInput disabled={running || !datasetId} onSubmit={onAsk} />
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
