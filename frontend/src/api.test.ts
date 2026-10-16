import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, request } from "./api";

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(body === undefined ? null : JSON.stringify(body), { status }));
}

describe("api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete window.__TOKEN__;
  });

  it("sends the session token with every request", async () => {
    window.__TOKEN__ = "secret";
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(200, []));
    await api.books();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/books");
    expect((init!.headers as Record<string, string>)["X-Token"]).toBe("secret");
  });

  it("turns an error answer into ApiError with the backend's message", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(409, { detail: "has labels", code: "needs_confirmation" }));
    const error = (await request("POST", "/api/datasets/1/capture", {}).catch((e) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("has labels");
    expect(error.needsConfirmation).toBe(true);
  });

  it("joins validation messages", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(422, { detail: [{ msg: "too short" }, { msg: "missing" }] }));
    const error = (await request("GET", "/x").catch((e) => e)) as ApiError;
    expect(error.message).toBe("too short; missing");
    expect(error.needsConfirmation).toBe(false);
  });

  it("sends an uploaded file as the body, its name in the address (C21)", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(200, { book: null, job: null }));
    const file = new File(["png"], "page 1.png", { type: "image/png" });
    await api.uploadPage("book", 4, file);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/books/4/upload?name=page%201.png");
    expect(init!.body).toBe(file);
    expect((init!.headers as Record<string, string>)["Content-Type"]).toBe("application/octet-stream");
    await api.uploadPage("dataset", 5, file);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/datasets/5/upload?name=page%201.png");
  });

  it("returns nothing for 204", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(204, undefined));
    expect(await api.deleteBook(3)).toBeUndefined();
  });
});
