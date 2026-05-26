import { useState } from "react";

import type { Evidence, QueryResponse } from "../types/api";

type Tab = "citations" | "retrieved" | "unused" | "debug";

interface EvidencePanelProps {
  response: QueryResponse | null;
}

function EvidenceItem({ item }: { item: Evidence }) {
  const snippet = item.text ?? item.raw_text ?? item.markdown_table ?? item.visual_type ?? "No snippet available";
  return (
    <article className="evidence-item">
      <div className="evidence-meta">
        <strong>{item.citation_id}</strong>
        <span>{item.filename ?? item.doc_id ?? "source"}</span>
        <span>score {item.score.toFixed(3)}</span>
      </div>
      <p>{snippet}</p>
    </article>
  );
}

export function EvidencePanel({ response }: EvidencePanelProps) {
  const [tab, setTab] = useState<Tab>("citations");

  const retrieved = response
    ? [...response.retrieved_evidence, ...response.table_evidence, ...response.visual_evidence]
    : [];
  const unused = response
    ? [
        ...response.unused_retrieved_evidence,
        ...response.unused_table_evidence,
        ...response.unused_visual_evidence,
      ]
    : [];

  return (
    <aside className="evidence-panel">
      <div className="tab-row">
        <button className={tab === "citations" ? "tab-active" : ""} onClick={() => setTab("citations")} type="button">
          Citations
        </button>
        <button className={tab === "retrieved" ? "tab-active" : ""} onClick={() => setTab("retrieved")} type="button">
          Retrieved
        </button>
        <button className={tab === "unused" ? "tab-active" : ""} onClick={() => setTab("unused")} type="button">
          Unused
        </button>
        <button className={tab === "debug" ? "tab-active" : ""} onClick={() => setTab("debug")} type="button">
          Debug
        </button>
      </div>

      {!response ? <p className="panel-empty">Run a query to inspect evidence.</p> : null}

      {response && tab === "citations" ? (
        <div className="evidence-stack">
          {[...response.answer_citations, ...response.table_citations, ...response.visual_citations].map((citation) => (
            <article className="evidence-item" key={`${citation.citation_id}-${citation.source_path}`}>
              <div className="evidence-meta">
                <strong>{citation.citation_id}</strong>
                <span>{citation.filename ?? citation.doc_id ?? "source"}</span>
              </div>
              <p>
                Page {citation.page_start ?? "?"}
                {citation.page_end && citation.page_end !== citation.page_start ? `-${citation.page_end}` : ""}
              </p>
            </article>
          ))}
        </div>
      ) : null}

      {response && tab === "retrieved" ? (
        <div className="evidence-stack">{retrieved.map((item) => <EvidenceItem item={item} key={`${item.citation_id}-${item.source_path}`} />)}</div>
      ) : null}

      {response && tab === "unused" ? (
        <div className="evidence-stack">{unused.map((item) => <EvidenceItem item={item} key={`${item.citation_id}-${item.source_path}`} />)}</div>
      ) : null}

      {response && tab === "debug" ? (
        <pre className="debug-block">{JSON.stringify(response.debug, null, 2)}</pre>
      ) : null}
    </aside>
  );
}
