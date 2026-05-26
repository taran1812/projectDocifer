import { useEffect, useState } from "react";

import { dociferApi } from "./lib/api";
import type { DocumentSummary } from "./types/api";

export default function App() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dociferApi
      .documents()
      .then((response) => setDocuments(response.documents))
      .catch((requestError: unknown) => {
        setError(requestError instanceof Error ? requestError.message : "Unable to load documents");
      });
  }, []);

  return (
    <main className="app-shell">
      <section className="empty-state">
        <p className="eyebrow">Docifer</p>
        <h1>Workbench loading</h1>
        <p>{error ?? `${documents.length} documents available`}</p>
      </section>
    </main>
  );
}
