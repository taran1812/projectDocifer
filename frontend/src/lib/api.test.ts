import { describe, it, expect, vi, beforeEach } from "vitest";
import { ApiError, dociferApi } from "./api";

function makeResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ApiError", () => {
  it("carries status and details", () => {
    const err = new ApiError("bad request", 400, { detail: "invalid" });
    expect(err.name).toBe("ApiError");
    expect(err.status).toBe(400);
    expect(err.details).toEqual({ detail: "invalid" });
    expect(err.message).toBe("bad request");
    expect(err).toBeInstanceOf(Error);
  });
});

describe("dociferApi", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("health() hits /health", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(makeResponse(200, { status: "ok" }));

    const result = await dociferApi.health();
    expect(result).toEqual({ status: "ok" });
    const url = (fetchMock.mock.calls[0][0] as string);
    expect(url).toMatch(/\/health$/);
  });

  it("deleteDocument() uses DELETE method", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      makeResponse(200, { document_id: "abc", filename: "test.pdf", deleted: true })
    );

    await dociferApi.deleteDocument("abc");
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init?.method).toBe("DELETE");
  });

  it("throws ApiError on 4xx response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Not found" }), { status: 404 })
    );

    await expect(dociferApi.documents()).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
  });

  it("query() sends POST with body", async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(makeResponse(200, { answer: "42", citations: [] }));

    await dociferApi.query({
      question: "what?",
      scope: "all",
      max_documents: 3,
      max_evidence_per_document: 5,
      top_k: 5,
      retrieval_mode: "hybrid",
      evidence_mode: "auto",
      table_top_k: 3,
      visual_top_k: 3,
      verify_citations: false,
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init?.method).toBe("POST");
    const sent = JSON.parse(init?.body as string);
    expect(sent.question).toBe("what?");
  });
});
