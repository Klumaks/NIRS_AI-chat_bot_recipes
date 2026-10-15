import { test, expect } from "@playwright/test";
test("disabled MSW uses configured API and never falls back on network/server errors", async ({
  page,
}) => {
  const requests: string[] = [];
  await page.route("http://127.0.0.1:58999/api/v1/**", async (route) => {
    requests.push(route.request().url());
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        request_id: "api-test",
        error: { code: "UNAVAILABLE", message: "Сервер временно недоступен" },
      }),
    });
  });
  await page.goto("/chat");
  await expect(page.getByRole("alert")).toContainText(
    "Сервер временно недоступен",
  );
  expect(requests).toContain("http://127.0.0.1:58999/api/v1/auth/me");
  await expect(
    page.getByRole("button", { name: "Демо · доступ и сценарии" }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      async () => (await navigator.serviceWorker.getRegistrations()).length,
    ),
  ).toBe(0);
  await page.unroute("http://127.0.0.1:58999/api/v1/**");
  await page.route("http://127.0.0.1:58999/api/v1/**", (route) =>
    route.abort("connectionrefused"),
  );
  await page.getByRole("button", { name: "Попробовать снова" }).click();
  await expect(page.getByRole("alert")).toContainText("Сервис недоступен");
  await expect(
    page.getByRole("heading", { name: "Что приготовим сегодня?" }),
  ).toHaveCount(0);
});
