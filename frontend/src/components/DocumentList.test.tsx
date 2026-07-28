import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DocumentList } from "./DocumentList";
import type { DocumentSummary } from "../types/api";

function makeDoc(overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  return {
    document_id: "doc-1",
    doc_id: "DOC-1",
    content_hash: "abc123",
    filename: "report.pdf",
    is_uploaded: true,
    latest_ingestion_status: "indexed",
    modalities: {
      text: { status: "indexed", count: 10 },
      table: { status: "indexed", count: 2 },
      visual: { status: "not_indexed", count: 0 },
    },
    ...overrides,
  };
}

describe("DocumentList", () => {
  it("renders document filename", () => {
    render(
      <DocumentList
        documents={[makeDoc()]}
        selectedDocumentId={null}
        onSelect={vi.fn()}
        onRemove={vi.fn()}
        removingDocumentId={null}
      />
    );
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
  });

  it("shows Remove button for all documents regardless of is_uploaded", () => {
    const docs = [
      makeDoc({ document_id: "d1", filename: "uploaded.pdf", is_uploaded: true }),
      makeDoc({ document_id: "d2", filename: "builtin.pdf", is_uploaded: false }),
    ];

    render(
      <DocumentList
        documents={docs}
        selectedDocumentId={null}
        onSelect={vi.fn()}
        onRemove={vi.fn()}
        removingDocumentId={null}
      />
    );

    expect(screen.getByLabelText("Remove uploaded.pdf")).toBeInTheDocument();
    expect(screen.getByLabelText("Remove builtin.pdf")).toBeInTheDocument();
  });

  it("calls onRemove when Remove button clicked", async () => {
    const onRemove = vi.fn();
    const doc = makeDoc();

    render(
      <DocumentList
        documents={[doc]}
        selectedDocumentId={null}
        onSelect={vi.fn()}
        onRemove={onRemove}
        removingDocumentId={null}
      />
    );

    await userEvent.click(screen.getByLabelText("Remove report.pdf"));
    expect(onRemove).toHaveBeenCalledWith(doc);
  });

  it("disables Remove button and shows Removing text for the doc being removed", () => {
    const doc = makeDoc({ document_id: "doc-1" });

    render(
      <DocumentList
        documents={[doc]}
        selectedDocumentId={null}
        onSelect={vi.fn()}
        onRemove={vi.fn()}
        removingDocumentId="doc-1"
      />
    );

    const btn = screen.getByLabelText("Remove report.pdf");
    expect(btn).toBeDisabled();
    expect(btn).toHaveTextContent("Removing");
  });

  it("calls onSelect when document row clicked", async () => {
    const onSelect = vi.fn();
    const doc = makeDoc();

    render(
      <DocumentList
        documents={[doc]}
        selectedDocumentId={null}
        onSelect={onSelect}
        onRemove={vi.fn()}
        removingDocumentId={null}
      />
    );

    await userEvent.click(screen.getByText("report.pdf"));
    expect(onSelect).toHaveBeenCalledWith(doc);
  });

  it("renders empty list without crashing", () => {
    render(
      <DocumentList
        documents={[]}
        selectedDocumentId={null}
        onSelect={vi.fn()}
        onRemove={vi.fn()}
        removingDocumentId={null}
      />
    );
    expect(screen.getByText("0 indexed sources")).toBeInTheDocument();
  });
});
