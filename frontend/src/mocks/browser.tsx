import { useState } from "react";
import { createRoot } from "react-dom/client";
import { setupWorker } from "msw/browser";
import { http, HttpResponse } from "msw";
import { installMockTransport } from "./transport";
import { handlers } from "./handlers";
import { initializeDemo, setMode } from "./store";
import type { DemoAccess, DemoMode } from "./store";
import { queryClient } from "../lib/query";
const modes: [DemoMode, string][] = [
  ["normal", "Обычный сценарий"],
  ["empty", "Нет подходящих блюд"],
  ["unknown", "Неизвестные параметры"],
  ["incomplete", "Рецепт без шагов"],
  ["unavailable", "Сохранённый рецепт недоступен"],
  ["search-error", "Ошибка поиска (503)"],
  ["llm-error", "Ошибка помощника (503)"],
  ["expired", "Сессия истекла (401)"],
];
function DemoPanel({ access }: { access: DemoAccess[] }) {
  const [open, setOpen] = useState(false);
  const [mode, setCurrent] = useState<DemoMode>("normal");
  const [busy, setBusy] = useState(false);
  async function change(value: DemoMode) {
    setBusy(true);
    await setMode(value);
    setCurrent(value);
    await queryClient.invalidateQueries();
    setBusy(false);
  }
  async function reset() {
    if (!confirm("Сбросить все демонстрационные аккаунты и чаты?")) return;
    await initializeDemo(true);
    document.cookie = "chef_session=; Max-Age=0; Path=/";
    location.assign("/login");
  }
  return (
    <>
      <div className="demo-banner">
        Демонстрационный режим · аккаунты, блюда, параметры и ответы — учебные
        примеры
      </div>
      <div className="demo-tools">
        <button
          className="demo-toggle"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
        >
          Демо · доступ и сценарии
        </button>
        {open && (
          <section className="demo-panel" aria-label="Настройки демонстрации">
            <h2>Учебный доступ</h2>
            <p>
              Скопируйте email и пароль в форму входа. Это постоянные учебные
              доступы из README; после перезагрузки они не меняются.
            </p>
            {access.map((a) => (
              <div className="demo-access" key={a.email}>
                <strong>
                  {a.role === "admin" ? "Администратор" : "Пользователь"}
                </strong>
                <label>
                  Email
                  <input
                    readOnly
                    value={a.email}
                    onFocus={(e) => e.target.select()}
                  />
                </label>
                <label>
                  Пароль
                  <input
                    readOnly
                    value={a.password}
                    onFocus={(e) => e.target.select()}
                  />
                </label>
                <button
                  onClick={() => {
                    void navigator.clipboard.writeText(a.password);
                  }}
                >
                  Копировать пароль
                </button>
              </div>
            ))}
            <label>
              Сценарий
              <select
                value={mode}
                disabled={busy}
                onChange={(e) => void change(e.target.value as DemoMode)}
              >
                {modes.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <p>
              Режимы выдачи применяются при новом подборе или применении
              фильтров. Это не настоящий BM25 или вызов модели.
            </p>
            <button className="button danger full" onClick={() => void reset()}>
              Сбросить демоданные
            </button>
          </section>
        )}
      </div>
    </>
  );
}
export async function startMocks() {
  const access = await initializeDemo();
  const healthUrl = new URL("/__ai-chef-mock-health__", window.location.origin).href;
  const worker = setupWorker(
    http.get(healthUrl, () => HttpResponse.json({ status: "ready" }, {
      headers: { "x-ai-chef-mock": "active", "cache-control": "no-store" },
    })),
    ...handlers,
  );
  const options: Parameters<typeof worker.start>[0] = {
    quiet: true,
    onUnhandledRequest(request, print) {
      const api = import.meta.env.VITE_API_BASE_URL || "/api/v1";
      if (new URL(request.url).pathname.startsWith(api)) print.error();
    },
  };
  await worker.start(options);
  installMockTransport(worker, options, healthUrl);
  document.documentElement.dataset.demo = "true";
  createRoot(document.getElementById("demo-root")!).render(
    <DemoPanel access={access} />,
  );
}
