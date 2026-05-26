import type {
  DocumentListResponse,
  HealthResponse,
  IngestionJobResponse,
  QueryRequest,
  QueryResponse,
  ReadyResponse,
} from "../types/api";

const API_BASE_URL =
  import.meta.env.VITE_DOCIFER_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  details: unknown;

  constructor(message: string, status: number, details: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const rawDetails = await response.text();
    let details: unknown = rawDetails;
    if (rawDetails) {
      try {
        details = JSON.parse(rawDetails);
      } catch {
        details = rawDetails;
      }
    }
    throw new ApiError(`Request failed with status ${response.status}`, response.status, details);
  }

  return response.json() as Promise<T>;
}

async function requestFormData<T>(
  path: string,
  formData: FormData,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    method: "POST",
    body: formData,
    headers: {
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const rawDetails = await response.text();
    let details: unknown = rawDetails;
    if (rawDetails) {
      try {
        details = JSON.parse(rawDetails);
      } catch {
        details = rawDetails;
      }
    }
    throw new ApiError(`Request failed with status ${response.status}`, response.status, details);
  }

  return response.json() as Promise<T>;
}

export const dociferApi = {
  health: () => requestJson<HealthResponse>("/health"),
  ready: () => requestJson<ReadyResponse>("/ready"),
  documents: () => requestJson<DocumentListResponse>("/documents?limit=200"),
  query: (body: QueryRequest) =>
    requestJson<QueryResponse>("/query", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  uploadPdf: (file: File, forceReprocess = false): Promise<IngestionJobResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    if (forceReprocess) {
      formData.append("force_reprocess", "true");
    }
    return requestFormData<IngestionJobResponse>("/ingestion/upload", formData);
  },
  ingestionJob: (jobId: string): Promise<IngestionJobResponse> =>
    requestJson<IngestionJobResponse>(`/ingestion/jobs/${jobId}`),
};
