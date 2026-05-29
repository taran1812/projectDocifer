import { useEffect, useMemo, useState } from "react";

import { AnswerPanel } from "./components/AnswerPanel";
import { DocumentList } from "./components/DocumentList";
import { EvidencePanel } from "./components/EvidencePanel";
import UploadPanel from "./components/UploadPanel";
import { QueryComposer } from "./components/QueryComposer";
import { StatusStrip } from "./components/StatusStrip";
import { ApiError, dociferApi } from "./lib/api";
import type {
  DocumentSummary,
  EvidenceMode,
  QueryRequest,
  QueryResponse,
  QueryScope,
} from "./types/api";

const DEFAULT_QUERY_PARAMS = {
  max_documents: 5,
  max_evidence_per_document: 3,
  top_k: 4,
  retrieval_mode: "hybrid" as const,
  table_top_k: 4,
  visual_top_k: 3,
} satisfies Partial<QueryRequest>;

export default function App() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [scope, setScope] = useState<QueryScope>("single");
  const [evidenceMode, setEvidenceMode] = useState<EvidenceMode>("auto");
  const [verifyCitations, setVerifyCitations] = useState(true);
  const [readyStatus, setReadyStatus] = useState("checking");
  const [requestStatus, setRequestStatus] = useState("idle");
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [response, setResponse] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [removingDocumentId, setRemovingDocumentId] = useState<string | null>(null);

  const selectedDocument = useMemo(
    () => documents.find((document) => document.document_id === selectedDocumentId) ?? null,
    [documents, selectedDocumentId],
  );

  useEffect(() => {
    Promise.allSettled([dociferApi.ready(), dociferApi.documents()]).then(
      ([readyResult, docsResult]) => {
        if (readyResult.status === "fulfilled") {
          setReadyStatus(readyResult.value.status);
        } else {
          setReadyStatus("offline");
        }
        if (docsResult.status === "fulfilled") {
          setDocuments(docsResult.value.documents);
          setSelectedDocumentId(docsResult.value.documents[0]?.document_id ?? null);
        } else {
          const loadError = docsResult.reason;
          setError(loadError instanceof Error ? loadError.message : "Unable to load documents");
        }
      },
    );
  }, []);

  async function runQuery() {
    if (!question.trim()) {
      return;
    }
    if (scope === "single" && !selectedDocument) {
      setError("Select a document before running a single-document query.");
      return;
    }

    const payload: QueryRequest = {
      ...DEFAULT_QUERY_PARAMS,
      question: question.trim(),
      scope,
      evidence_mode: evidenceMode,
      verify_citations: verifyCitations,
      ...(scope === "single" && selectedDocument
        ? { content_hash: selectedDocument.content_hash }
        : {}),
    };

    setIsLoading(true);
    setError(null);
    setResponse(null);
    setRequestStatus("running");
    const started = performance.now();
    try {
      const result = await dociferApi.query(payload);
      setResponse(result);
      setLatencyMs(performance.now() - started);
      setRequestStatus("complete");
    } catch (queryError: unknown) {
      const message =
        queryError instanceof ApiError
          ? `${queryError.message}: ${JSON.stringify(queryError.details)}`
          : queryError instanceof Error
            ? queryError.message
            : "Query failed";
      setError(message);
      setRequestStatus("failed");
    } finally {
      setIsLoading(false);
    }
  }

  async function refreshDocuments(nextSelectedDocumentId?: string | null) {
    const result = await dociferApi.documents();
    setDocuments(result.documents);
    const hasRequestedSelection = result.documents.some(
      (document) => document.document_id === nextSelectedDocumentId,
    );
    setSelectedDocumentId(
      hasRequestedSelection
        ? nextSelectedDocumentId ?? null
        : result.documents[0]?.document_id ?? null,
    );
  }

  async function removeUploadedDocument(document: DocumentSummary) {
    const confirmed = window.confirm(
      `Remove "${document.filename}"? This deletes its indexed evidence${document.is_uploaded ? " and stored upload" : ""}.`,
    );
    if (!confirmed) {
      return;
    }

    setRemovingDocumentId(document.document_id);
    setError(null);
    try {
      await dociferApi.deleteDocument(document.document_id);
      await refreshDocuments(
        selectedDocumentId === document.document_id ? null : selectedDocumentId,
      );
      if (selectedDocumentId === document.document_id) {
        setResponse(null);
        setRequestStatus("idle");
        setLatencyMs(null);
      }
    } catch (removeError: unknown) {
      const message =
        removeError instanceof ApiError
          ? removeError.message
          : removeError instanceof Error
            ? removeError.message
            : "Unable to remove document";
      setError(message);
    } finally {
      setRemovingDocumentId(null);
    }
  }

  return (
    <main className="workbench">
      <StatusStrip
        evidenceMode={evidenceMode}
        latencyMs={latencyMs}
        readyStatus={readyStatus}
        requestStatus={requestStatus}
        scope={scope}
      />
      <div className="workbench-grid">
        <aside className="document-rail">
          <UploadPanel
            onIngestionComplete={(job) => {
              refreshDocuments(job.document_id)
                .then(() => setScope("single"))
                .catch((err: unknown) => {
                  setError(err instanceof Error ? err.message : "Failed to refresh document list after upload");
                });
            }}
          />
          <DocumentList
            documents={documents}
            onSelect={(document) => {
              setSelectedDocumentId(document.document_id);
              setScope("single");
            }}
            onRemove={removeUploadedDocument}
            removingDocumentId={removingDocumentId}
            selectedDocumentId={selectedDocumentId}
          />
        </aside>
        <section className="center-column">
          <QueryComposer
            evidenceMode={evidenceMode}
            isLoading={isLoading}
            onSubmit={runQuery}
            question={question}
            scope={scope}
            selectedDocument={selectedDocument}
            setEvidenceMode={setEvidenceMode}
            setQuestion={setQuestion}
            setScope={setScope}
            setVerifyCitations={setVerifyCitations}
            verifyCitations={verifyCitations}
          />
          <AnswerPanel error={error} isLoading={isLoading} response={response} />
        </section>
        <EvidencePanel response={response} />
      </div>
    </main>
  );
}
