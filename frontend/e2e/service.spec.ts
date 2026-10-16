import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
async function credentials(page: Page, role: "user" | "admin") {
  await page.getByRole("button", { name: "Демо · доступ и сценарии" }).click();
  const card = page
    .locator(".demo-access")
    .filter({ hasText: role === "admin" ? "Администратор" : "Пользователь" });
  const email = await card.getByLabel("Email", { exact: true }).inputValue();
  const password = await card
    .getByLabel("Пароль", { exact: true })
    .inputValue();
  await page.getByRole("button", { name: "Демо · доступ и сценарии" }).click();
  return { email, password };
}
async function login(page: Page, role: "user" | "admin" = "user") {
  await page.goto("/login");
  const c = await credentials(page, role);
  await page.getByLabel("Электронная почта").fill(c.email);
  await page.getByLabel("Пароль", { exact: true }).fill(c.password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  return c;
}
test("user flow, filters, history, repeat login and deletion", async ({
  page,
  isMobile,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);
  await page
    .getByRole("button", { name: "Курица, рис, лук", exact: true })
    .click();
  await expect(page.getByLabel("Ваши продукты")).toHaveValue(
    "Курица, рис, лук",
  );
  await expect(page).toHaveURL(/\/chat$/);
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(page).toHaveURL(/\/chat\/[\w-]+$/);
  const chatUrl = page.url();
  await expect(
    page.getByRole("heading", { name: "Рис с курицей и овощами", exact: true }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath("suggestions.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Фильтры", exact: true }).click();
  await page.getByLabel("Общее время, мин").fill("25");
  await page.getByRole("button", { name: "Применить", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Рис с курицей и овощами", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Куриный суп с рисом", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".recipe-card .missing")).toContainText("Вода");
  await page.getByRole("button", { name: "Открыть рецепт" }).click();
  await expect(page).toHaveURL(/\/recipe\/1$/);
  const recipeUrl = page.url();
  await expect(page.locator(".ingredients-panel")).toContainText("Вода");
  await expect(page.locator(".ingredients-panel")).toContainText("300 мл");
  await expect(
    page.getByLabel("Вопрос по рецепту", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: testInfo.outputPath("recipe.png"),
    fullPage: true,
  });
  await page
    .getByLabel("Вопрос по рецепту", { exact: true })
    .fill("Что делать на втором шаге?");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(page.locator(".message.assistant").last()).toContainText(
    "Добавьте промытый рис",
  );
  await page.reload();
  await expect(page.locator(".message.assistant").last()).toContainText(
    "Добавьте промытый рис",
  );
  await expect(page).toHaveURL(recipeUrl);
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  const c = await credentials(page, "user");
  await page.getByLabel("Электронная почта").fill(c.email);
  await page.getByLabel("Пароль", { exact: true }).fill(c.password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await page.goto(chatUrl);
  await expect(
    page.getByRole("button", { name: "Фильтры · применены" }),
  ).toBeVisible();
  if (isMobile)
    await page.getByRole("button", { name: "Открыть историю" }).click();
  const id = new URL(chatUrl).pathname.split("/").pop()!;
  const row = page
    .locator(".history-list li")
    .filter({ has: page.locator('a[href="/chat/' + id + '"]') });
  await row.getByRole("button", { name: /Удалить чат/ }).click();
  await page.getByRole("button", { name: "Отмена", exact: true }).click();
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: /Удалить чат/ }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Удалить", exact: true })
    .click();
  await expect(page).toHaveURL(/\/chat$/);
  expect(errors).toEqual([]);
});
test("admin creates an admin; activity and diagnostics have direct URLs", async ({
  page,
}, testInfo) => {
  await login(page, "admin");
  await page.goto("/admin/users");
  await expect(
    page.getByRole("cell", { name: "user@ai-chef.test", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("admin-users.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Создать аккаунт" }).click();
  const email = "admin-" + Date.now() + "@example.test";
  const password = "Test-" + crypto.randomUUID();
  await page
    .getByRole("dialog")
    .getByLabel("Email", { exact: true })
    .fill(email);
  await page.getByLabel("Начальный пароль").fill(password);
  await expect(page.getByRole("radio", { name: "Пользователь", exact: true })).toBeChecked();
  await page.getByRole("radio", { name: "Пользователь", exact: true }).press("ArrowDown");
  await expect(page.getByRole("radio", { name: "Администратор", exact: true })).toBeChecked();
  await page.getByRole("dialog").screenshot({ path: testInfo.outputPath("role-picker.png") });
  await page.getByRole("button", { name: "Создать", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: email, exact: true }),
  ).toBeVisible();
  await page.goto("/admin/activity");
  await expect(
    page.getByRole("heading", { name: "Активность", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Диагностика" }).first().click();
  await expect(
    page.getByRole("heading", { name: "Диагностика запроса" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Путь запроса" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await page.goto("/admin/users");
  await expect(
    page.getByRole("button", { name: "Создать аккаунт" }),
  ).toBeVisible();
});
test("user cannot open admin or another account chat; unknown route is 404", async ({
  page,
}) => {
  await login(page);
  await page.goto("/admin/users");
  await expect(page).toHaveURL(/\/403$/);
  await expect(
    page.getByRole("heading", { name: "Здесь нужны права администратора" }),
  ).toBeVisible();
  await page.goto("/chat/demo-other-chat");
  await expect(page.getByRole("alert")).toContainText("Чат не найден");
  await page.goto("/does-not-exist");
  await expect(
    page.getByRole("heading", { name: "Такой страницы нет" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
test("registration and API errors are visible", async ({ page }) => {
  await page.goto("/register");
  const email = "person-" + Date.now() + "@example.test";
  const password = "Test-" + crypto.randomUUID();
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByLabel("Повторите пароль").fill(password);
  await page
    .getByRole("button", { name: "Создать аккаунт", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Аккаунт создан" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Перейти ко входу" }).click();
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await page.getByRole("button", { name: "Демо · доступ и сценарии" }).click();
  await page
    .getByRole("combobox", { name: "Сценарий", exact: true })
    .selectOption("search-error");
  await page.getByRole("button", { name: "Демо · доступ и сценарии" }).click();
  await page.getByLabel("Ваши продукты").fill("курица");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Поиск временно недоступен",
  );
});

test("expired session returns to login instead of showing cached private data", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("button", { name: "Демо · доступ и сценарии" }).click();
  await page
    .getByRole("combobox", { name: "Сценарий", exact: true })
    .selectOption("expired");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByLabel("Ваши продукты")).toHaveCount(0);
});

test("chat navigation resumes the last opened recipe and keeps new selection separate", async ({ page, isMobile }) => {
  await login(page, "admin");
  const menu = async () => { if (isMobile) await page.getByRole("button", { name: "Открыть историю" }).click(); };
  await page.goto("/chat/demo-admin-chat");
  await page.getByRole("button", { name: "Открыть рецепт", exact: true }).first().click();
  await expect(page).toHaveURL(/\/chat\/demo-admin-chat\/recipe\/1$/);
  await expect(page.getByLabel("Вопрос по рецепту", { exact: true })).toBeVisible();
  const recipeUrl = page.url();
  await menu();
  await page.getByRole("link", { name: "Новый подбор", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByLabel("Ваши продукты")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Ваши продукты")).toBeVisible();
  await menu();
  await page.getByRole("link", { name: "Чат с ИИ-шефом", exact: true }).click();
  await expect(page).toHaveURL(recipeUrl);
  await expect(page.getByLabel("Вопрос по рецепту", { exact: true })).toBeVisible();
  await page.goto("/admin/users");
  await expect(page.getByRole("heading", { name: "Пользователи", exact: true })).toBeVisible();
  await menu();
  await page.getByRole("link", { name: "Чат с ИИ-шефом", exact: true }).click();
  await expect(page).toHaveURL(recipeUrl);
  await expect(page.getByLabel("Вопрос по рецепту", { exact: true })).toBeVisible();
  await menu();
  const row = page.locator(".history-list li").filter({ has: page.locator('a[href="/chat/demo-admin-chat"]') });
  await row.getByRole("button", { name: /Удалить чат/ }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  if (!isMobile) {
    await expect(page.getByRole("link", { name: "Чат с ИИ-шефом", exact: true })).toHaveAttribute("href", "/chat");
  } else {
    await page.getByRole("link", { name: "Чат с ИИ-шефом", exact: true }).click();
    await expect(page.getByLabel("Ваши продукты")).toBeVisible();
  }
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page, "user");
  await menu();
  await page.getByRole("link", { name: "Чат с ИИ-шефом", exact: true }).click();
  await expect(page).toHaveURL(/\/chat\/demo-chat-1$/);
});

test("admin mocks recover after browser service worker restart", async ({ page, context, isMobile }, testInfo) => {
  await login(page, "admin");
  const cdp = await context.newCDPSession(page);
  await cdp.send("ServiceWorker.enable");
  await cdp.send("ServiceWorker.stopAllWorkers");
  const menu = async () => { if (isMobile) await page.getByRole("button", { name: "Открыть историю" }).click(); };
  await menu();
  await page.getByRole("link", { name: "Пользователи", exact: true }).click();
  await expect(page.getByRole("cell", { name: "user@ai-chef.test", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Создать аккаунт" }).click();
  const email = "recovery-" + Date.now() + "@example.test";
  await page.getByRole("dialog").getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Начальный пароль").fill("DemoRecovery123!");
  await page.getByRole("button", { name: "Создать", exact: true }).click();
  await expect(page.getByRole("cell", { name: email, exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("recovered-users.png"), fullPage: true });
  await cdp.send("ServiceWorker.stopAllWorkers");
  await menu();
  await page.getByRole("link", { name: "Активность", exact: true }).click();
  await expect(page.getByRole("link", { name: "Диагностика" }).first()).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("recovered-activity.png"), fullPage: true });
});


test("admin adds and imports demo RAG data; user finds recipes and is denied admin access", async ({ page, isMobile }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error" && !/^Failed to load resource:.*(?:401|409)/.test(message.text())) errors.push(message.text()); });
  await login(page, "admin");
  if (isMobile) await page.getByRole("button", { name: "Открыть историю" }).click();
  await page.getByRole("link", { name: "Данные RAG", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/rag$/);
  await expect(page).toHaveTitle(/ИИ-шеф/);
  await expect(page.getByRole("heading", { name: "Данные RAG", exact: true })).toBeVisible();
  await page.getByLabel("Название", { exact: true }).fill("Гречка с грибами");
  await page.getByLabel("Источник (HTTP/HTTPS)").fill("https://example.test/grechka");
  await page.getByLabel("Продукт 1", { exact: true }).fill("Гречка");
  await page.getByLabel("Продукт 2", { exact: true }).fill("Грибы");
  await page.getByText("Дополнительные данные", { exact: true }).click();
  await page.getByLabel("Шаги (каждый с новой строки)").fill("Сварите гречку.\nПриготовьте грибы и смешайте.");
  await page.getByRole("button", { name: "Добавить рецепт", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Рецепт добавлен");
  await expect(page.getByRole("cell", { name: "Гречка с грибами", exact: true })).toBeVisible();
  const imported = { title: "Чечевица с сельдереем", ingredients: [{ name: "Чечевица" }, { name: "Сельдерей" }], url: "https://example.test/lentils" };
  await page.getByLabel("Файл JSONL").setInputFiles({ name: "recipes.jsonl", mimeType: "application/x-ndjson", buffer: Buffer.from(JSON.stringify(imported)) });
  await expect(page.getByRole("button", { name: "Подтвердить импорт" })).toBeDisabled();
  await page.getByRole("button", { name: "Проверить файл" }).click();
  await expect(page.getByText("Файл готов к импорту.")).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить импорт" }).click();
  await expect(page.getByText("Добавлено записей: 1. Версия demo-corpus-v3")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("cell", { name: "Чечевица с сельдереем", exact: true })).toBeVisible();
  await expect(page.getByText("9 записей · Версия demo-corpus-v3")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("rag-admin.png"), fullPage: true });
  await page.screenshot({ path: testInfo.outputPath("rag-admin-viewport.png"), fullPage: false });
  if (isMobile) {
    await page.getByRole("heading", { name: "Импорт JSONL", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath("rag-import-viewport.png"), fullPage: false });
  }
  await page.getByLabel("Файл JSONL").setInputFiles({ name: "invalid.jsonl", mimeType: "application/x-ndjson", buffer: Buffer.from(JSON.stringify(imported) + "\n{broken") });
  await page.getByRole("button", { name: "Проверить файл" }).click();
  await expect(page.getByText("Записей: 2 · Ошибок: 1 · Дубликатов: 1")).toBeVisible();
  await expect(page.getByText("Строка 2: Некорректный JSON")).toBeVisible();
  await expect(page.getByRole("button", { name: "Подтвердить импорт" })).toBeDisabled();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await login(page);
  await expect(page.getByText("Перечислите продукты через запятую или „и“")).toBeVisible();
  await page.getByLabel("Ваши продукты").fill("гречка и грибы");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Гречка с грибами", exact: true })).toBeVisible();
  await expect(page.locator(".product-chips .chip")).toHaveText(["гречка", "грибы"]);
  await expect(page.locator(".recipe-card")).toContainText("Время: нет данных");
  await page.getByRole("button", { name: "Открыть рецепт" }).click();
  await expect(page.getByText("Приготовьте грибы и смешайте.", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Приготовьте грибы и смешайте.", { exact: true })).toBeVisible();
  await page.goto("/chat");
  await page.getByLabel("Ваши продукты").fill("чечевица, сельдерей");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await page.getByRole("button", { name: "Открыть рецепт" }).click();
  await expect(page.getByRole("alert")).toContainText("нет проверенных шагов");
  await expect(page.getByRole("link", { name: "Открыть источник", exact: true })).toHaveAttribute("href", imported.url);
  await page.goto("/admin/rag");
  await expect(page).toHaveURL(/\/403$/);
  await expect(page.getByRole("link", { name: "Данные RAG", exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});


test("RAG editing and deletion preserve drafts, confirm actions and detect version conflicts", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/^Failed to load resource:.*(?:401|409)/.test(m.text())) errors.push(m.text()); });
  await login(page, "admin");
  await page.goto("/admin/rag");
  const original = "Рис с курицей и овощами";
  await page.getByRole("button", { name: `Редактировать ${original}`, exact: true }).click();
  await expect(page.getByLabel("Название", { exact: true })).toHaveValue(original);
  await expect(page.getByLabel("Количество 1", { exact: true })).toHaveValue("300 г");
  await expect(page.getByLabel("Калории, ккал")).toHaveValue("165");
  await page.getByLabel("Название", { exact: true }).fill("Несохранённое название");
  await page.getByRole("button", { name: "Отменить редактирование" }).click();
  await expect(page.getByRole("cell", { name: original, exact: true })).toBeVisible();
  await page.getByRole("button", { name: `Редактировать ${original}`, exact: true }).click();
  await page.getByLabel("Название", { exact: true }).fill("Рис с овощами — новая версия");
  const prepared = await page.evaluate(async () => {
    const r = (await (await fetch("/api/v1/admin/rag")).json()).items[0];
    return (await fetch(`/api/v1/admin/rag/recipes/${r.recipe_id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...r, expected_version: r.corpus_version }) })).status;
  });
  expect(prepared).toBe(200);
  await page.getByRole("button", { name: "Сохранить изменения" }).click();
  await expect(page.getByRole("alert")).toContainText("Запись уже изменена");
  await expect(page.getByLabel("Название", { exact: true })).toHaveValue("Рис с овощами — новая версия");
  await page.getByRole("button", { name: "Обновить список", exact: true }).click();
  await page.getByRole("button", { name: `Редактировать ${original}`, exact: true }).click();
  await page.getByLabel("Название", { exact: true }).fill("Рис с овощами — новая версия");
  await page.getByLabel("Калории, ккал").fill("");
  await page.getByRole("button", { name: "Сохранить изменения" }).click();
  await expect(page.getByText("Рецепт обновлён. Версия demo-corpus-v3")).toBeVisible();
  await page.reload();
  const title = "Рис с овощами — новая версия";
  await expect(page.getByRole("cell", { name: title, exact: true })).toBeVisible();
  await page.getByRole("button", { name: `Редактировать ${title}`, exact: true }).click();
  await expect(page.getByLabel("Калории, ккал")).toHaveValue("");
  await expect(page.getByLabel("Название", { exact: true })).toHaveValue(title);
  await page.screenshot({ path: testInfo.outputPath("rag-edit.png"), fullPage: false });
  await page.getByRole("button", { name: "Отменить редактирование" }).click();
  await page.getByRole("button", { name: `Удалить ${title}`, exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText(title);
  await page.getByRole("button", { name: "Отмена", exact: true }).click();
  await expect(page.getByRole("cell", { name: title, exact: true })).toBeVisible();
  await page.getByRole("button", { name: `Удалить ${title}`, exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath("rag-delete.png"), fullPage: false });
  await page.getByRole("dialog").getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(page.getByText("Рецепт удалён. Версия demo-corpus-v4")).toBeVisible();
  await expect(page.getByRole("cell", { name: title, exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: `Редактировать ${title}`, exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test("RAG deletion returns from the last page and shows an empty catalog", async ({ page }) => {
  await login(page, "admin");
  const status = await page.evaluate(async () => {
    const text = Array.from({ length: 14 }, (_, i) => JSON.stringify({ title: `Добавленный рецепт ${i + 1}`, ingredients: [{ name: "Гречка" }, { name: "Грибы" }], url: "https://example.test/recipe" })).join("\n");
    return (await fetch("/api/v1/admin/rag/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) })).status;
  });
  expect(status).toBe(201);
  await page.goto("/admin/rag");
  await page.getByRole("button", { name: "Далее", exact: true }).click();
  await expect(page.getByText("Показано 1 из 21")).toBeVisible();
  await page.getByRole("button", { name: "Удалить Добавленный рецепт 14", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(page.getByText("Показано 20 из 20")).toBeVisible();
  await expect(page.getByRole("button", { name: "Назад", exact: true })).toBeDisabled();
  const statuses = await page.evaluate(async () => {
    const data = await (await fetch("/api/v1/admin/rag")).json();
    const results = [];
    for (const r of data.items.slice(1)) results.push((await fetch(`/api/v1/admin/rag/recipes/${r.recipe_id}`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_version: r.corpus_version }) })).status);
    return results;
  });
  expect(statuses).toEqual(Array(19).fill(200));
  await page.getByRole("button", { name: "Обновить список", exact: true }).click();
  await expect(page.getByText("Показано 1 из 1")).toBeVisible();
  await page.getByRole("button", { name: "Удалить Рис с курицей и овощами", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(page.getByRole("heading", { name: "В каталоге пока нет рецептов" })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Показано 0 из 0")).toBeVisible();
});
