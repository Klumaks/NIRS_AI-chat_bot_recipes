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
  await page.getByRole("button", { name: "Открыть рецепт" }).click();
  await expect(page).toHaveURL(/\/recipe\/1$/);
  const recipeUrl = page.url();
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
