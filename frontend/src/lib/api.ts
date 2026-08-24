const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ColumnRole = "measure" | "dimension" | "temporal" | "identifier";

export type ColumnProfile = {
  name: string;
  semantic_type: string;
  storage_type: string;
  duckdb_type: string;
  role: ColumnRole;
  null_count: number;
  null_pct: number;
  unique_count: number;
  unique_ratio: number;
  sample_values: string[];
  stats: Record<string, number | null> | null;
  date_range: { min: string | null; max: string | null } | null;
  top_values: Record<string, number> | null;
  date_format: string | null;
  temporal_grain: string | null;
  warnings: string[];
  notes: string[];
};

export type QualityWarning = {
  code: string;
  column: string;
  message: string;
  severity: "info" | "warning" | "error";
};

export type WideLayout = {
  id_columns: string[];
  value_columns: string[];
  period_grain: string;
  period_name: string;
  value_name: string;
};

export type DatasetProfile = {
  table_name: string;
  long_table_name: string | null;
  layout: "long" | "wide";
  row_count: number;
  column_count: number;
  columns: ColumnProfile[];
  measures: string[];
  dimensions: string[];
  temporal: string[];
  identifiers: string[];
  date_columns: string[];
  numeric_columns: string[];
  categorical_columns: string[];
  quality: {
    warnings: QualityWarning[];
    normalized_expressions: Record<string, string>;
    duplicate_rows: number;
  };
  wide: WideLayout | null;
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
  confidence?: string;
  content?: string;
  session_id?: string;
  limitations?: string[];
  degraded?: boolean;
  recoverable?: boolean;
  attempt?: number;
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
  row_count: number;
  truncated: boolean;
  chart_id: string | null;
};

export type Claim = {
  id: string;
  text: string;
  evidence_ids: string[];
  confidence: "high" | "medium" | "low";
};

export type ClaimCheck = {
  claim_id: string;
  status: "verified" | "unverified" | "rejected";
  detail: string;
  unmatched_numbers: number[];
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
  checks: ClaimCheck[];
  degraded: boolean;
};

/** Events that end the stream. Anything else keeps it open. */
export const TERMINAL_EVENTS = ["done", "error"];

const STREAM_EVENT_TYPES = [
  "node_start",
  "tool_call",
  "finding",
  "chart",
  "claim",
  "explanation",
  "report_chunk",
  "warning",
  "step_retry",
  "step_error",
  "done",
  "error",
  "ping",
];

/**
 * The dataset or session no longer exists server-side. On a free host the
 * instance is recreated after it idles, which wipes both the uploaded CSV and
 * the in-memory session, so the only recovery is to upload again.
 */
export class SessionGoneError extends Error {
  constructor(message = "The analysis server restarted and lost this dataset.") {
    super(message);
    this.name = "SessionGoneError";
  }
}

export async function pingHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

/** Poll /health while a sleeping instance wakes up (roughly a minute). */
export async function waitForBackend(attempts = 12, delayMs = 5000): Promise<boolean> {
  for (let i = 0; i < attempts; i++) {
    if (await pingHealth()) return true;
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  return false;
}

export async function uploadDataset(file: File): Promise<{
  dataset_id: string;
  profile: DatasetProfile;
}> {
  const form = new FormData();
  form.append("file", file);

  let res: Response;
  try {
    res = await fetch(`${API_URL}/datasets`, { method: "POST", body: form });
  } catch {
    // A sleeping instance drops the first connection; wake it and retry once.
    if (!(await waitForBackend())) {
      throw new Error("Cannot reach the analysis server. Try again in a moment.");
    }
    const retryForm = new FormData();
    retryForm.append("file", file);
    res = await fetch(`${API_URL}/datasets`, { method: "POST", body: retryForm });
  }

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
  if (res.status === 404) throw new SessionGoneError();
  if (!res.ok) throw new Error("Failed to create session");
  return res.json();
}

export async function askQuestion(sessionId: string, question: string): Promise<void> {
  const res = await fetch(`${API_URL}/sessions/${sessionId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (res.status === 404) throw new SessionGoneError();
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to start analysis");
  }
}

export async function cancelAnalysis(sessionId: string): Promise<void> {
  await fetch(`${API_URL}/sessions/${sessionId}/cancel`, { method: "POST" }).catch(() => {});
}

export function streamSession(
  sessionId: string,
  onEvent: (event: AgentEvent) => void,
  onError?: (err: Error) => void
): EventSource {
  const es = new EventSource(`${API_URL}/sessions/${sessionId}/stream`);
  let finished = false;

  const handler = (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as AgentEvent;
      if (TERMINAL_EVENTS.includes(data.type)) finished = true;
      onEvent(data);
    } catch {
      /* ignore malformed */
    }
  };

  es.addEventListener("message", handler);
  STREAM_EVENT_TYPES.forEach((type) => es.addEventListener(type, handler));

  es.onerror = () => {
    // The server closes the connection after the terminal event; that is a
    // normal end of stream, not a failure worth showing the user.
    if (!finished) onError?.(new Error("Lost connection to the analysis stream"));
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
  if (res.status === 404) throw new SessionGoneError();
  if (!res.ok) throw new Error("Failed to fetch session");
  return res.json();
}
