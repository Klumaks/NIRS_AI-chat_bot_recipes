import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/manrope/400.css";
import "@fontsource/manrope/500.css";
import "@fontsource/manrope/600.css";
import "@fontsource/manrope/700.css";
import "./styles.css";
import { App } from "./App";
async function start() {
  if (import.meta.env.VITE_ENABLE_MOCKS === "true") {
    const { startMocks } = await import("./mocks/browser");
    await startMocks();
  } else if ("serviceWorker" in navigator) {
    // Remove only this project's MSW registration, never unrelated workers.
    const oldMockController =
      navigator.serviceWorker.controller?.scriptURL.endsWith(
        "/mockServiceWorker.js",
      );
    const registrations = await navigator.serviceWorker.getRegistrations();
    for (const registration of registrations) {
      const url =
        registration.active?.scriptURL ||
        registration.waiting?.scriptURL ||
        registration.installing?.scriptURL;
      if (url && new URL(url).pathname.endsWith("/mockServiceWorker.js"))
        await registration.unregister();
    }
    if (oldMockController) {
      window.location.reload();
      return;
    }
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
start().catch(() => {
  document.getElementById("root")!.textContent =
    "Не удалось запустить приложение. Перезагрузите страницу; для деморежима необходимы доступные IndexedDB и Service Worker.";
});
