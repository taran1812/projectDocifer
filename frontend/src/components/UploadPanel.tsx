import { useState, useRef, useEffect } from "react";
import { dociferApi } from "../lib/api";
import type { IngestionJobResponse } from "../types/api";

interface UploadPanelProps {
  onIngestionComplete: () => void;
}

type UploadState = "idle" | "uploading" | "processing" | "done" | "failed";

export default function UploadPanel({ onIngestionComplete }: UploadPanelProps) {
  const [state, setState] = useState<UploadState>("idle");
  const [filename, setFilename] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  function clearPolling() {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    pollCountRef.current = 0;
  }

  async function handleUpload(file: File) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setErrorMsg("Only PDF files are supported");
      setState("failed");
      return;
    }
    setFilename(file.name);
    setErrorMsg("");
    setState("uploading");

    let job: IngestionJobResponse;
    try {
      job = await dociferApi.uploadPdf(file);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Upload failed");
      setState("failed");
      return;
    }

    if (job.status === "completed" || job.status === "done") {
      setState("done");
      onIngestionComplete();
      setTimeout(() => setState("idle"), 3000);
      return;
    }
    if (job.status === "failed") {
      setErrorMsg(job.error_message ?? "Ingestion failed");
      setState("failed");
      return;
    }

    setState("processing");
    intervalRef.current = setInterval(async () => {
      pollCountRef.current += 1;
      if (pollCountRef.current > 60) {
        clearPolling();
        setErrorMsg("Ingestion timed out");
        setState("failed");
        return;
      }
      try {
        const status = await dociferApi.ingestionJob(job.job_id);
        if (status.status === "completed" || status.status === "done") {
          clearPolling();
          setState("done");
          onIngestionComplete();
          setTimeout(() => setState("idle"), 3000);
        } else if (status.status === "failed") {
          clearPolling();
          setErrorMsg(status.error_message ?? "Ingestion failed");
          setState("failed");
        }
      } catch {
        // transient network error — keep polling
      }
    }, 2000);
  }

  function onFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
    e.target.value = "";
  }

  function onDragOver(e: React.DragEvent) {
    e.preventDefault();
    setIsDragOver(true);
  }

  function onDragLeave() {
    setIsDragOver(false);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleUpload(file);
  }

  return (
    <div className="upload-panel">
      {state === "idle" && (
        <div
          className={`upload-zone${isDragOver ? " is-drag-over" : ""}`}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <span>Drop a PDF or browse</span>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            style={{ display: "none" }}
            onChange={onFileInput}
          />
        </div>
      )}
      {(state === "uploading" || state === "processing") && (
        <div className="upload-spinner">
          <span className="spinner" />
          <span>{state === "uploading" ? "Uploading…" : "Processing…"}</span>
        </div>
      )}
      {state === "done" && (
        <div className="upload-done">
          <span>&#x2713; {filename} &mdash; Ready to query</span>
        </div>
      )}
      {state === "failed" && (
        <div className="upload-error">
          <span>{errorMsg || "Upload failed"}</span>
          <button onClick={() => setState("idle")}>Dismiss</button>
        </div>
      )}
    </div>
  );
}
