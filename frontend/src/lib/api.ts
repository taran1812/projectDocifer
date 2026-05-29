import type {
  DocumentDeleteResponse,
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

function parseErrorDetails(rawDetails: string): unknown {
  if (!rawDetails) {
    return "";
  }
  try {
    return JSON.parse(rawDetails);
  } catch {
    return rawDetails;
  }
}

function getErrorMessage(status: number, details: unknown) {
  if (
    details &&
    typeof details === "object" &&
    "detail" in details &&
    typeof details.detail === "string"
  ) {
    return details.detail;
  }
  if (typeof details === "string" && details.trim()) {
    return details;
  }
  return `Request failed with status ${status}`;
}

async function throwIfNotOk(response: Response): Promise<void> {
  if (!response.ok) {
    const rawDetails = await response.text();
    const details = parseErrorDetails(rawDetails);
    throw new ApiError(getErrorMessage(response.status, details), response.status, details);
  }
}

const API_KEY = import.meta.env.VITE_DOCIFER_API_KEY ?? "";

function apiKeyHeader(): Record<string, string> {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...apiKeyHeader(),
      ...init?.headers,
    },
  });
  await throwIfNotOk(response);
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
      ...apiKeyHeader(),
      ...init?.headers,
    },
  });
  await throwIfNotOk(response);
  return response.json() as Promise<T>;
}

export const dociferApi = {
  health: () => requestJson<HealthResponse>("/health"),
  ready: () => requestJson<ReadyResponse>("/ready"),
  documents: () => requestJson<DocumentListResponse>("/documents?limit=200"),
  deleteDocument: (documentId: string): Promise<DocumentDeleteResponse> =>
    requestJson<DocumentDeleteResponse>(`/documents/${documentId}`, {
      method: "DELETE",
    }),
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
