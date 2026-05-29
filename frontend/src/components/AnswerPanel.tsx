import { AlertCircle, CheckCircle2 } from "lucide-react";

import type { QueryResponse } from "../types/api";

interface AnswerPanelProps {
  response: QueryResponse | null;
  error: string | null;
  isLoading: boolean;
}

export function AnswerPanel({ response, error, isLoading }: AnswerPanelProps) {
  if (isLoading) {
    return <section className="answer-panel loading-panel">Retrieving evidence and generating answer...</section>;
  }

  if (error) {
    return (
      <section className="answer-panel error-panel">
        <AlertCircle size={20} />
        <div>
          <h2>Request failed</h2>
          <p>{error}</p>
        </div>
      </section>
    );
  }

  if (!response) {
    return (
      <section className="answer-panel empty-answer">
        <h2>Ask a question to inspect grounded evidence</h2>
        <p>Answers will appear here with citations and evidence diagnostics.</p>
      </section>
    );
  }

  return (
    <section className="answer-panel">
      <div className="answer-heading">
        <CheckCircle2 size={20} />
        <div>
          <h2>Answer</h2>
          <p>{response.answer_citations.length} final citations</p>
        </div>
      </div>
      <p className="answer-text">{response.answer}</p>
      <div className="citation-row">
        {[...response.answer_citations, ...response.table_citations, ...response.visual_citations].map(
          (citation, idx) => (
            <span className="citation-chip" key={`${idx}-${citation.citation_id}-${citation.source_path}`}>
              {citation.citation_id}
              <small>
                {citation.filename ?? citation.doc_id ?? "source"} p.
                {citation.page_start ?? "?"}
              </small>
            </span>
          ),
        )}
      </div>
    </section>
  );
}
