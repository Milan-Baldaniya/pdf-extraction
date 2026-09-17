import axios from "axios";
import { API_BASE, apiRootUrl, apiUrl } from "./api-url";

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 0, // MinerU extraction can take several minutes; let the server decide.
  headers: {
    "Content-Type": "application/json",
  },
});

export interface ExtractionRequest {
  pdf_url: string;
  document_type?: string;
  document_title?: string;
  chapter_number?: string;
  standard?: string;
  subject_name?: string;
  board?: string;
  syear?: number;
}

export interface ExtractionResponse {
  status: "success";
  processing_mode: string;
  markdown_content: string;
  json_content: JsonValue | null;
  metadata: Record<string, JsonValue>;
  page_count: number | null;
  images_extracted: number;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

export async function healthCheck(): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>("/health");
  return data;
}

export interface JobAccepted {
  job_id: string;
  state: string;
  status_url: string;
  result_url: string;
}

export interface JobStatus {
  job_id: string;
  state: string;
  message: string;
  updated_at: string;
  metadata: Record<string, JsonValue>;
  done: boolean;
  result_ready: boolean;
}

export type JobProgress = (status: JobStatus) => void;

/** How often to ask the server for job progress. */
const POLL_INTERVAL_MS = 3000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Pull FastAPI's `detail` out of an error response, falling back to the status. */
async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Non-JSON error body; fall through.
  }
  return `${fallback} (HTTP ${res.status})`;
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(apiUrl(`/status/${jobId}`), { cache: "no-store" });
  if (!res.ok) throw new Error(await errorMessage(res, "Could not read job status"));
  return res.json();
}

export async function getJobResult<T>(jobId: string): Promise<T> {
  const res = await fetch(apiUrl(`/jobs/${jobId}/result`), { cache: "no-store" });
  if (!res.ok) throw new Error(await errorMessage(res, "Could not read job result"));
  return res.json();
}

/**
 * Poll a queued job until it finishes, then return its payload.
 *
 * All jobs share one server-side registry, so the polling path is always under
 * `/api` no matter which router queued the work.
 */
export async function waitForJob<T>(
  jobId: string,
  onProgress?: JobProgress
): Promise<T> {
  for (;;) {
    let status: JobStatus;
    try {
      status = await getJobStatus(jobId);
    } catch {
      // A dropped poll (sleeping laptop, brief restart) should not abort a job
      // that may still be running; back off and try again.
      await sleep(POLL_INTERVAL_MS);
      continue;
    }

    onProgress?.(status);

    if (status.state === "failed") {
      throw new Error(status.message || "Job failed");
    }
    if (status.done && status.result_ready) {
      return getJobResult<T>(jobId);
    }

    await sleep(POLL_INTERVAL_MS);
  }
}

/**
 * Start a background job and wait for its result.
 *
 * The work these endpoints do — MinerU extraction, the DeepSeek agent swarms —
 * runs far longer than a proxy or browser will hold one request open, so the
 * server returns a job id straight away and this issues only short polls.
 */
export async function runJob<T>(
  url: string,
  init?: RequestInit,
  onProgress?: JobProgress
): Promise<T> {
  const res = await fetch(url, { method: "POST", ...init });
  if (!res.ok) throw new Error(await errorMessage(res, "Could not start job"));
  const accepted: JobAccepted = await res.json();
  return waitForJob<T>(accepted.job_id, onProgress);
}

/** POST a JSON body as a background job. */
export function runJsonJob<T>(
  url: string,
  body: unknown,
  onProgress?: JobProgress
): Promise<T> {
  return runJob<T>(
    url,
    {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    onProgress
  );
}

export async function extractPdf(
  request: ExtractionRequest,
  onProgress?: JobProgress
): Promise<ExtractionResponse> {
  return runJsonJob<ExtractionResponse>(
    apiUrl("/jobs/extract"),
    request,
    onProgress
  );
}

export async function uploadPdf(
  file: File,
  metadata?: Omit<ExtractionRequest, "pdf_url">,
  onProgress?: JobProgress
): Promise<ExtractionResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (metadata) {
    Object.entries(metadata).forEach(([key, value]) => {
      // syear arrives as a number; FormData only accepts strings or Blobs.
      if (value) formData.append(key, String(value));
    });
  }

  // No Content-Type header: the browser must set the multipart boundary.
  return runJob<ExtractionResponse>(
    apiUrl("/jobs/upload"),
    { body: formData },
    onProgress
  );
}

/**
 * Run the Phase 2 semantic swarm for an extraction.
 *
 * Keyed on the extraction id (the `pdf_cache_id` attached to an extraction's
 * metadata), which is what the backend addresses these by.
 */
export async function generateSemanticIntelligence(
  extractionId: number,
  force = false,
  onProgress?: JobProgress
) {
  return runJob<unknown>(
    apiUrl(
      `/jobs/semantic-intelligence/${extractionId}/process?force=${force}`
    ),
    undefined,
    onProgress
  );
}

export interface TeachingIntelligenceRequest {
  standard_id?: number;
  subject_id?: number;
  chapter_id: number;
  language?: string;
  teaching_style?: string;
  difficulty_level?: string;
  force_new?: boolean;
}

export async function generateTeachingIntelligence(
  request: TeachingIntelligenceRequest,
  onProgress?: JobProgress
) {
  // Mounted outside /api, so this needs the server root rather than apiUrl().
  return runJsonJob<unknown>(
    apiRootUrl("/teaching-intelligence/jobs/generate"),
    request,
    onProgress
  );
}


export interface Subject {
  id: number;
  subject_name: string;
}

export async function fetchSubjectsByStandard(standardName: string): Promise<Subject[]> {
  const { data } = await api.get<Subject[]>(`/subjects/${encodeURIComponent(standardName)}`);
  return data;
}

export interface CreateSubjectPayload {
  standard_name: string;
  subject_name: string;
  subject_code?: string;
  subject_type?: string;
  short_name?: string;
  display_name?: string;
}

export async function createSubject(payload: CreateSubjectPayload): Promise<Subject> {
  const { data } = await api.post<Subject>(`/subjects`, payload);
  return data;
}


// ---------------------------------------------------------------------------
// Overnight extraction queue
//
// The queue is a detached process on the server, not a job of the API, so these
// endpoints read files it publishes rather than talking to it. That is why
// status can say "crashed": the heartbeat went stale while nobody was watching.
// ---------------------------------------------------------------------------

export interface QueueChapterInFlight {
  label: string
  title: string
  subject: string
  standard: number | null
  chapter: number | null
  attempt: number
  started_at: string
}

export interface QueueStatus {
  running: boolean
  state: "idle" | "running" | "stopping" | "finished" | "stopped" | "interrupted" | "crashed"
  message: string
  run_id?: string | null
  pid?: number | null
  started_at?: string | null
  started_human?: string
  finished_at?: string | null
  updated_at?: string | null
  elapsed_seconds?: number | null
  elapsed_human?: string
  counts?: Record<string, number>
  finished_count?: number
  total?: number
  remaining?: number | null
  percent?: number
  current?: QueueChapterInFlight[]
  current_subject?: string
  last_finished?: { label: string; title: string; status: string; seconds: number; at: string } | null
  plan?: { chapters?: number; batch_size?: number; subjects?: { name: string; chapters: number }[] }
  degraded?: boolean
  low_memory_batches?: number
  free_gb?: number | null
  failures?: { label: string; title: string; error: string }[]
  stop_requested?: boolean
  log_file?: string | null
  sheet_exists?: boolean
  /** The sheet this status is about, and every sheet on the machine. */
  sheet?: string | null
  sheets?: string[]
}

export interface NightChapter {
  key: string
  label: string
  subject: string
  chapter: number | null
  status: string
  extraction_id: number | null
  pages: number | null
  md_chars: number | null
  images: number | null
  seconds: number | null
  duration_human: string
  attempts: number | null
  error: string
  at: string
  at_human: string
}

export interface NightSubject {
  name: string
  done: number
  failed: number
  skipped: number
  touched: number
  complete: boolean
}

export interface Night {
  run_id: string
  state: string
  live: boolean
  started_at: string | null
  finished_at: string | null
  when_human: string
  duration_seconds: number | null
  duration_human: string
  counts: Record<string, number>
  headline: string
  details: string[]
  subjects: NightSubject[]
  chapters: NightChapter[]
  log_file: string | null
}

export interface QueueOverviewSubject {
  name: string
  standard: number | null
  subject: string
  board: string
  total: number
  settled: number
  percent: number
  chapters: {
    chapter: number | null
    title: string
    status: string
    extraction_id: number | null
    pages: number | null
    md_chars: number | null
    attempts: number
    error: string
    pdf_url: string
  }[]
  [bucket: string]: unknown
}

export interface QueueOverview {
  exists: boolean
  sheet?: string
  sheets?: string[]
  subjects: QueueOverviewSubject[]
  totals: Record<string, number>
  total_rows?: number
  pending?: number
}

export interface QueueStartOptions {
  sheet?: string | null
  batch_size?: number
  only_standard?: string | null
  only_subject?: string | null
  force?: boolean
  stop_at?: string | null
}

export async function fetchQueueStatus(sheet?: string | null): Promise<QueueStatus> {
  const { data } = await api.get<QueueStatus>("/queue/status", { params: sheet ? { sheet } : {} })
  return data
}

export async function startQueue(options: QueueStartOptions = {}): Promise<{ started: boolean; pid: number; message: string }> {
  const { data } = await api.post("/queue/start", { batch_size: 2, ...options })
  return data
}

export async function stopQueue(sheet?: string | null): Promise<{ stopped: boolean; message: string; state: string }> {
  const { data } = await api.post("/queue/stop", {}, { params: sheet ? { sheet } : {} })
  return data
}

export async function fetchNights(limit = 30, sheet?: string | null): Promise<Night[]> {
  const { data } = await api.get<Night[]>("/queue/nights", {
    params: sheet ? { limit, sheet } : { limit },
  })
  return data
}

export async function fetchNightLog(runId: string, tailLines = 400): Promise<{
  run_id: string
  file: string
  total_lines: number
  truncated: boolean
  text: string
}> {
  const { data } = await api.get(`/queue/nights/${runId}/log`, { params: { tail_lines: tailLines } })
  return data
}

export async function fetchQueueOverview(sheet?: string | null): Promise<QueueOverview> {
  const { data } = await api.get<QueueOverview>("/queue/overview", {
    params: sheet ? { sheet } : {},
  })
  return data
}
