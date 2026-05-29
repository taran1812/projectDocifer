import { Search } from "lucide-react";
import type { FormEvent } from "react";

import type { DocumentSummary, EvidenceMode, QueryScope } from "../types/api";

interface QueryComposerProps {
  question: string;
  setQuestion: (value: string) => void;
  scope: QueryScope;
  setScope: (value: QueryScope) => void;
  evidenceMode: EvidenceMode;
  setEvidenceMode: (value: EvidenceMode) => void;
  verifyCitations: boolean;
  setVerifyCitations: (value: boolean) => void;
  selectedDocument: DocumentSummary | null;
  isLoading: boolean;
  onSubmit: () => void;
}

export function QueryComposer({
  question,
  setQuestion,
  scope,
  setScope,
  evidenceMode,
  setEvidenceMode,
  verifyCitations,
  setVerifyCitations,
  selectedDocument,
  isLoading,
  onSubmit,
}: QueryComposerProps) {
  const disabled = isLoading || question.trim().length === 0 || (scope === "single" && !selectedDocument);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!disabled) {
      onSubmit();
    }
  }

  return (
    <form className="query-composer" onSubmit={handleSubmit}>
      <div className="composer-context">
        <span>{scope === "single" ? selectedDocument?.filename ?? "Select a document" : "All indexed documents"}</span>
        <div className="segmented-control" aria-label="Query scope">
          <button
            className={scope === "single" ? "segmented-active" : ""}
            onClick={() => setScope("single")}
            type="button"
          >
            Single
          </button>
          <button
            className={scope === "all" ? "segmented-active" : ""}
            onClick={() => setScope("all")}
            type="button"
          >
            All
          </button>
        </div>
      </div>
      <textarea
        aria-label="Question"
        onChange={(event) => setQuestion(event.target.value)}
        placeholder="Ask a grounded question about the selected document or corpus..."
        value={question}
      />
      <div className="composer-controls">
        <label>
          Evidence
          <select
            onChange={(event) => setEvidenceMode(event.target.value as EvidenceMode)}
            value={evidenceMode}
          >
            <option value="auto">Auto</option>
            <option value="text">Text</option>
            <option value="table">Table</option>
            <option value="visual">Visual</option>
          </select>
        </label>
        <label className="toggle-control">
          <input
            checked={verifyCitations}
            onChange={(event) => setVerifyCitations(event.target.checked)}
            type="checkbox"
          />
          Verify citations
        </label>
        <button className="primary-action" disabled={disabled} type="submit">
          <Search size={17} />
          {isLoading ? "Querying" : "Ask"}
        </button>
      </div>
    </form>
  );
}
