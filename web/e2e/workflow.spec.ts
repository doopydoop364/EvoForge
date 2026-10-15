import { test, expect, type Page } from "@playwright/test";
async function login(page: Page) {
  await page.goto("/");
  await page
    .getByLabel("API token", { exact: true })
    .fill("browser-test-token");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Backend connected")).toBeVisible();
}
async function nav(page: Page, name: string) {
  await page
    .getByRole("navigation")
    .getByRole("button", { name, exact: true })
    .click();
}
async function action(page: Page, name: string, value?: string) {
  await page.getByRole("button", { name, exact: true }).last().click();
  if (value) await page.getByLabel("Destination name").fill(value);
  await page
    .getByRole("button", { name: `Confirm ${name.toLowerCase()}`, exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
}
test("complete Coin lifecycle, actual frames, analytics, saved and model replays", async ({
  page,
  browser,
}) => {
  await login(page);
  await nav(page, "Games & Plugins");
  await expect(
    page.getByRole("heading", { name: "Coin prediction" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Snake", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Flappy-style" }),
  ).toBeVisible();
  await expect(page.locator("canvas")).toHaveCount(3);
  await page
    .getByRole("button", { name: "New experiment", exact: true })
    .click();
  await page.getByLabel("Experiment name").fill("browser-coin");
  await page.getByLabel("Game", { exact: true }).selectOption("coin");
  await page.getByLabel("Algorithm", { exact: true }).selectOption("evolution");
  await page.getByLabel("Population size").fill("4");
  await page.getByLabel("Elite count").fill("1");
  await page.getByLabel("PPO candidates").fill("0");
  await page.getByLabel("Evaluation episodes").fill("1");
  await page.getByLabel("Generations", { exact: true }).fill("10000");
  await page.getByLabel("Hidden widths").fill("8");
  await page
    .getByLabel("Game-specific JSON configuration")
    .fill('{"horizon":50}');
  await page
    .getByRole("button", { name: "Create experiment", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "browser-coin", exact: true }),
  ).toBeVisible();
  await action(page, "Start");
  await nav(page, "Spectator");
  await expect(page.locator("canvas")).not.toHaveCount(0);
  await expect(
    page.getByText(/saved frame|sampled frame/).first(),
  ).toBeVisible();
  await expect(page.locator(".agent-stats").first()).toContainText(
    "Generation",
  );
  await nav(page, "Experiments");
  await action(page, "Pause");
  await expect(
    page.getByRole("button", { name: "Resume", exact: true }),
  ).toBeVisible();
  const second = await browser.newContext();
  const other = await second.newPage();
  await login(other);
  await nav(other, "Experiments");
  await expect(
    other.getByRole("heading", { name: "browser-coin", exact: true }),
  ).toBeVisible();
  await expect(
    other.getByRole("button", { name: "Resume", exact: true }),
  ).toBeVisible();
  await second.close();
  await action(page, "Resume");
  await expect(
    page.getByRole("button", { name: "Pause", exact: true }),
  ).toBeVisible();
  await action(page, "Stop");
  await expect(
    page.getByRole("button", { name: "Start", exact: true }),
  ).toBeVisible();
  await nav(page, "Analytics");
  await expect(page.locator(".chart").first()).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Population fitness" }),
  ).toBeVisible();
  await nav(page, "Experiments");
  await action(page, "Duplicate", "browser-copy");
  await expect(
    page.getByRole("heading", { name: "browser-copy", exact: true }),
  ).toBeVisible();
  await action(page, "Rename", "browser-renamed");
  await expect(
    page.getByRole("heading", { name: "browser-renamed", exact: true }),
  ).toBeVisible();
  await action(page, "Archive");
  await expect(
    page.getByRole("button", { name: "Unarchive", exact: true }),
  ).toBeVisible();
  await action(page, "Unarchive");
  await expect(
    page.getByRole("button", { name: "Archive", exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Open experiment", { exact: true })
    .selectOption("browser-coin");
  await nav(page, "Spectator");
  await page.getByLabel("Mode", { exact: true }).selectOption("recorded");
  const options = page.getByLabel("Saved episode").locator("option");
  await expect.poll(() => options.count()).toBeGreaterThan(1);
  await page.getByLabel("Saved episode").selectOption({ index: 1 });
  await expect(
    page.getByRole("button", { name: "Play replay", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Play replay", exact: true }).click();
  await expect(page.locator("canvas")).toHaveCount(1);
  await page.getByLabel("Mode", { exact: true }).selectOption("champion");
  await page.getByLabel("Replay seed").fill("123");
  await page.getByRole("button", { name: "Load replay", exact: true }).click();
  await expect(page.getByText("· seed 123")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Play replay", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Mode", { exact: true }).selectOption("population");
  await page.getByLabel("Visible agents").selectOption("2");
  await page.getByRole("button", { name: "Load replay", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Play replay", exact: true }),
  ).toHaveCount(2);
  await nav(page, "Dashboard");
  await page.screenshot({
    path: "test-results/dashboard-desktop.png",
    fullPage: true,
  });
});
test("mobile layout, theme persistence, missing credentials, and secure sessions", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.getByRole("button", { name: "Toggle theme" }).click();
  const theme = await page.locator("html").getAttribute("data-theme");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme!);
  await expect(page.getByText("Backend connected")).toBeAttached();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([
    "evoforge-theme",
  ]);
  const cookies = await page.context().cookies();
  expect(cookies.find((c) => c.name === "evoforge_session")?.httpOnly).toBe(
    true,
  );
  await page.screenshot({
    path: "test-results/dashboard-mobile.png",
    fullPage: true,
  });
});
