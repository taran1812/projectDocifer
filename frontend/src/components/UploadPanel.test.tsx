import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import UploadPanel from "./UploadPanel";

vi.mock("../lib/api", () => ({
  dociferApi: {
    uploadPdf: vi.fn(),
    ingestionJob: vi.fn(),
  },
}));

import { dociferApi } from "../lib/api";

describe("UploadPanel — idle state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders upload zone with accessible label", () => {
    render(<UploadPanel onIngestionComplete={vi.fn()} />);
    expect(screen.getByText("Upload document")).toBeInTheDocument();
    expect(screen.getByText(/Drop a PDF here or browse/i)).toBeInTheDocument();
  });

  it("has hidden file input accepting only pdf", () => {
    render(<UploadPanel onIngestionComplete={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.accept).toBe(".pdf");
  });
});

describe("UploadPanel — upload flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows error for non-PDF files", async () => {
    render(<UploadPanel onIngestionComplete={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["content"], "doc.txt", { type: "text/plain" });
    // fireEvent bypasses the accept filter that userEvent respects
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(screen.getByText("Only PDF files are supported")).toBeInTheDocument()
    );
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("transitions to done and calls onIngestionComplete after successful upload", async () => {
    const onDone = vi.fn();
    vi.mocked(dociferApi.uploadPdf).mockResolvedValueOnce({
      job_id: "job-1",
      document_id: "doc-1",
      status: "indexed",
      artifact_path: "processed/doc.json",
      reused_existing: false,
      error_message: null,
    });

    render(<UploadPanel onIngestionComplete={onDone} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["%PDF-1.4"], "annual.pdf", { type: "application/pdf" });
    await userEvent.upload(input, file);

    await waitFor(() => expect(screen.getByText(/is ready to query/i)).toBeInTheDocument());
    expect(onDone).toHaveBeenCalledOnce();
  });

  it("shows error message when upload API call fails", async () => {
    vi.mocked(dociferApi.uploadPdf).mockRejectedValueOnce(new Error("Network error"));

    render(<UploadPanel onIngestionComplete={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["%PDF-1.4"], "annual.pdf", { type: "application/pdf" });
    await userEvent.upload(input, file);

    await waitFor(() => expect(screen.getByText("Network error")).toBeInTheDocument());
  });

  it("resets to idle state when Try again is clicked", async () => {
    render(<UploadPanel onIngestionComplete={vi.fn()} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["content"], "doc.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => screen.getByRole("button", { name: /try again/i }));
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(screen.getByText("Upload document")).toBeInTheDocument();
  });
});
