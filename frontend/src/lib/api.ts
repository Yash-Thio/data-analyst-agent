const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ColumnProfile = {
  name: string;
  dtype: string;
  role: string;
  null_count: number;
  null_pct: number;
  unique_count: number;
  sample_values: string[];
};

export type DatasetProfile = {
  table_name: string;
  row_count: number;
  column_count: number;
  columns: ColumnProfile[];
  date_columns: string[];
  numeric_columns: string[];
  categorical_columns: string[];
};

export type AgentEvent = {
  type: string;
  node?: string;
  message?: string;
  tool?: string;
  sql?: string;
  row_count?: number;
  id?: string;
  summary?: string;
  spec?: ChartSpec;
  finding_id?: string;
  text?: string;
  evidence_ids?: string[];
  content?: string;
  session_id?: string;
  limitations?: string[];
};

export type ChartSpec = {
  id: string;
  finding_id: string;
  type: "bar" | "line" | "area";
  title: string;
  data: Record<string, unknown>[];
  x_key: string;
  y_key: string;
};

export type Evidence = {
  id: string;
  finding_id: string;
  sql: string;
  result_preview: Record<string, unknown>[];
  metrics: Record<string, number | string | null>;
  chart_id: string | null;
};

export type Claim = {
  id: string;
  text: string;
  evidence_ids: string[];
  confidence: "high" | "medium" | "low";
};

export type ReasoningStep = {
  order: number;
  node: string;
  description: string;
  output_summary: string;
};

export type Explanation = {
  summary: string;
  claims: Claim[];
  evidence: Evidence[];
  reasoning_trace: ReasoningStep[];
  limitations: string[];
  markdown: string;
};

export async function uploadDataset(file: File): Promise<{
  dataset_id: string;
  profile: DatasetProfile;
}> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_URL}/datasets`, { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Upload failed");
  }
  return res.json();
}

export async function createSession(datasetId: string): Promise<{ session_id: string }> {
  const res = await fetch(`${API_URL}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId }),
  });
  if (!res.ok) throw new Error("Failed to create session");
  return res.json();
}

export async function askQuestion(sessionId: string, question: string): Promise<void> {
  const res = await fetch(`${API_URL}/sessions/${sessionId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to start analysis");
  }
}

export function streamSession(
  sessionId: string,
  onEvent: (event: AgentEvent) => void,
  onError?: (err: Error) => void
): EventSource {
  const es = new EventSource(`${API_URL}/sessions/${sessionId}/stream`);
  const handler = (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as AgentEvent;
      onEvent(data);
    } catch {
      /* ignore malformed */
    }
  };
  es.addEventListener("message", handler);
  [
    "node_start",
    "tool_call",
    "finding",
    "chart",
    "claim",
    "explanation",
    "report_chunk",
    "done",
    "error",
    "ping",
  ].forEach((type) => es.addEventListener(type, handler));

  es.onerror = () => {
    onError?.(new Error("Stream connection error"));
    es.close();
  };
  return es;
}

export async function getSession(sessionId: string): Promise<{
  status: string;
  explanation: Explanation | null;
  charts: ChartSpec[] | null;
  error?: string;
}> {
  const res = await fetch(`${API_URL}/sessions/${sessionId}`);
  if (!res.ok) throw new Error("Failed to fetch session");
  return res.json();
}
