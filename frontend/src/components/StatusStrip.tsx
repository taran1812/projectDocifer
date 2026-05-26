import { Activity, Database, Timer } from "lucide-react";

import type { EvidenceMode, QueryScope } from "../types/api";

interface StatusStripProps {
  readyStatus: string;
  scope: QueryScope;
  evidenceMode: EvidenceMode;
  latencyMs: number | null;
  requestStatus: string;
}

export function StatusStrip({
  readyStatus,
  scope,
  evidenceMode,
  latencyMs,
  requestStatus,
}: StatusStripProps) {
  return (
    <header className="status-strip">
      <div className="brand-block">
        <span className="brand-mark">D</span>
        <div>
          <h1>Docifer Workbench</h1>
          <p>Grounded document intelligence</p>
        </div>
      </div>
      <div className="status-items">
        <span className={`status-pill status-${readyStatus}`}>
          <Activity size={15} />
          {readyStatus}
        </span>
        <span className="status-pill">
          <Database size={15} />
          {scope} / {evidenceMode}
        </span>
        <span className="status-pill">
          <Timer size={15} />
          {latencyMs === null ? "no query yet" : `${Math.round(latencyMs)} ms`}
        </span>
        <span className="status-pill">{requestStatus}</span>
      </div>
    </header>
  );
}
