import { FileText, Trash2 } from "lucide-react";

import type { DocumentSummary, ModalityIndexStatus } from "../types/api";

interface DocumentListProps {
  documents: DocumentSummary[];
  selectedDocumentId: string | null;
  onSelect: (document: DocumentSummary) => void;
  onRemove: (document: DocumentSummary) => void;
  removingDocumentId: string | null;
}

function ModalityBadge({ label, status }: { label: string; status: ModalityIndexStatus }) {
  return (
    <span className={`modality-badge modality-${status.status}`}>
      {label}
      <strong>{status.count}</strong>
    </span>
  );
}

export function DocumentList({
  documents,
  selectedDocumentId,
  onSelect,
  onRemove,
  removingDocumentId,
}: DocumentListProps) {
  return (
    <>
      <div className="panel-heading">
        <FileText size={18} />
        <div>
          <h2>Documents</h2>
          <p>{documents.length} indexed sources</p>
        </div>
      </div>
      <div className="document-list">
        {documents.map((document) => (
          <article
            className={`document-item ${
              selectedDocumentId === document.document_id ? "is-selected" : ""
            }`}
            key={document.document_id}
          >
            <button className="document-select" onClick={() => onSelect(document)} type="button">
              <span className="document-id">{document.doc_id ?? "DOC"}</span>
              <span className="document-name">{document.filename}</span>
              <span className="document-status">
                {document.latest_ingestion_status ?? "unknown"}
                {document.is_uploaded ? " / uploaded" : ""}
              </span>
              <span className="modality-row">
                <ModalityBadge label="Text" status={document.modalities.text} />
                <ModalityBadge label="Table" status={document.modalities.table} />
                <ModalityBadge label="Visual" status={document.modalities.visual} />
              </span>
            </button>
            <button
              aria-label={`Remove ${document.filename}`}
              className="document-remove"
              disabled={removingDocumentId === document.document_id}
              onClick={() => onRemove(document)}
              title="Remove document"
              type="button"
            >
              <Trash2 size={14} />
              <span>{removingDocumentId === document.document_id ? "Removing" : "Remove"}</span>
            </button>
          </article>
        ))}
      </div>
    </>
  );
}
