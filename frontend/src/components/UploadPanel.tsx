import { useState, useRef, useEffect } from "react";
import { dociferApi } from "../lib/api";
import type { IngestionJobResponse } from "../types/api";

interface UploadPanelProps {
  onIngestionComplete: (job: IngestionJobResponse) => void;
}

type UploadState = "idle" | "uploading" | "processing" | "done" | "failed";
const ACCEPTED_PDF_TYPES = new Set(["application/pdf", "application/octet-stream"]);

function formatFileSize(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export default function UploadPanel({ onIngestionComplete }: UploadPanelProps) {
  const [state, setState] = useState<UploadState>("idle");
  const [filename, setFilename] = useState("");
  const [fileSize, setFileSize] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollCountRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
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
    clearPolling();
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (!file.name.toLowerCase().endsWith(".pdf") || !ACCEPTED_PDF_TYPES.has(file.type)) {
      setErrorMsg("Only PDF files are supported");
      setState("failed");
      return;
    }
    setFilename(file.name);
    setFileSize(formatFileSize(file.size));
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

    if (job.status === "completed" || job.status === "done" || job.status === "indexed") {
      setState("done");
      onIngestionComplete(job);
      timeoutRef.current = setTimeout(() => setState("idle"), 3000);
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
      if (pollCountRef.current >= 60) {
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
          onIngestionComplete(status);
          timeoutRef.current = setTimeout(() => setState("idle"), 3000);
        } else if (status.status === "failed") {
          clearPolling();
          setErrorMsg(status.error_message ?? "Ingestion failed");
          setState("failed");
        }
      } catch {
        // Transient network error; keep polling.
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
          role="button"
          tabIndex={0}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
          }}
        >
          <div className="upload-zone-copy">
            <strong>Upload document</strong>
            <span>Drop a PDF here or browse</span>
            <small>Large PDFs are accepted up to the backend limit.</small>
          </div>
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
          <span className="upload-progress-copy">
            <strong>{state === "uploading" ? "Uploading..." : "Processing..."}</strong>
            <small>
              {filename}
              {fileSize ? ` (${fileSize})` : ""}
            </small>
          </span>
        </div>
      )}
      {state === "done" && (
        <div className="upload-done">
          <span>{filename} is ready to query</span>
        </div>
      )}
      {state === "failed" && (
        <div className="upload-error">
          <span>{errorMsg || "Upload failed"}</span>
          <button onClick={() => setState("idle")} type="button">
            Try again
          </button>
        </div>
      )}
    </div>
  );
}
