import axios from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

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
  syear?: string;
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

export async function extractPdf(
  request: ExtractionRequest
): Promise<ExtractionResponse> {
  const { data } = await api.post<ExtractionResponse>(
    "/generate-chapter-ppt",
    request
  );
  return data;
}

export async function uploadPdf(
  file: File,
  metadata?: Omit<ExtractionRequest, "pdf_url">
): Promise<ExtractionResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (metadata) {
    Object.entries(metadata).forEach(([key, value]) => {
      if (value) formData.append(key, value);
    });
  }

  const { data } = await api.post<ExtractionResponse>(
    "/upload-chapter-ppt",
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    }
  );
  return data;
}

export interface SemanticIntelligenceRequest {
  markdown_file_path?: string;
  markdown_content?: string;
  pdf_cache_id?: number;
  force_regenerate?: boolean;
}

export async function generateSemanticIntelligence(
  request: SemanticIntelligenceRequest
) {
  // Use a separate axios instance or absolute URL because this endpoint is outside /api
  const base = API_BASE.replace('/api', '');
  const { data } = await axios.post(
    `${base}/phase2/generate`,
    request,
    { headers: { "Content-Type": "application/json" } }
  );
  return data;
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
  request: TeachingIntelligenceRequest
) {
  const base = API_BASE.replace('/api', '');
  const { data } = await axios.post(
    `${base}/teaching-intelligence/generate`,
    request,
    { headers: { "Content-Type": "application/json" } }
  );
  return data;
}

