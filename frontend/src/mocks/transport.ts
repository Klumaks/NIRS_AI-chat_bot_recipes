import type { setupWorker } from "msw/browser";
import { API_BASE } from "../api/client";

type Worker = ReturnType<typeof setupWorker>;
type StartOptions = Parameters<Worker["start"]>[0];

// Installed only by the dynamically loaded demo bootstrap.
// Keep recovery outside the API client and never retry an already sent POST.
export function installMockTransport(worker: Worker, options: StartOptions, healthUrl: string) {
  const nativeFetch = window.fetch.bind(window);
  const api = new URL(API_BASE, window.location.href);
  let checking: Promise<void> | undefined;

  async function isActive() {
    try {
      const response = await nativeFetch(healthUrl, {
        cache: "no-store",
        signal: AbortSignal.timeout(3000),
      });
      return response.headers.get("x-ai-chef-mock") === "active";
    } catch {
      return false;
    }
  }

  async function ensureActive() {
    if (!checking) {
      checking = (async () => {
        if (await isActive()) return;
        worker.stop();
        await worker.start(options);
        if (!(await isActive())) {
          throw new Error("Не удалось восстановить перехват HTTP-моков.");
        }
      })().finally(() => { checking = undefined; });
    }
    await checking;
  }

  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
    const isApi = url.origin === api.origin &&
      (url.pathname === api.pathname || url.pathname.startsWith(api.pathname.replace(/\/$/, "") + "/"));
    if (isApi) {
      const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined);
      signal?.throwIfAborted();
      await ensureActive();
      signal?.throwIfAborted();
    }
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined);
    const canRetry = isApi && method === "GET";
    let response: Response;
    try {
      response = await nativeFetch(input, init);
    } catch (error) {
      if (!canRetry || signal?.aborted) throw error;
      await ensureActive();
      signal?.throwIfAborted();
      return nativeFetch(input, init);
    }
    // A GET already in flight can outlive the worker being stopped.
    // Vite may return HTML or a plain 404. Neither is a mock JSON response. Retry this read once;
    // never retry writes whose completion may be unknown.
    if (canRetry && !response.headers.get("content-type")?.includes("application/json")) {
      await ensureActive();
      signal?.throwIfAborted();
      return nativeFetch(input, init);
    }
    return response;
  };

  return () => { window.fetch = nativeFetch; };
}
