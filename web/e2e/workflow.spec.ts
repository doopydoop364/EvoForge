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
  const renderWarnings: string[] = [];
  const loadedAssets = new Set<string>();
  page.on("console", (message) => {
    if (
      /could not be loaded|Failed to load|specified load parser/.test(
        message.text(),
      )
    )
      renderWarnings.push(message.text());
  });
  page.on("response", (response) => {
    if (
      response.url().includes("/api/v1/games/") &&
      response.url().includes("/assets/") &&
      response.ok()
    )
      loadedAssets.add(response.url());
  });
  await login(page);
  // The initial unauthenticated health check correctly returns 401.
  renderWarnings.length = 0;
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
  // A canvas alone also passes when every sprite is a placeholder. Verify the
  // extensionless assets actually reached the image loaders for all plugins.
  const manifests = await Promise.all(
    ["snake", "flappy", "coin"].map(async (game) =>
      (await page.request.get(`/api/v1/games/${game}/manifest`)).json(),
    ),
  );
  const expectedAssets = manifests.reduce(
    (count, manifest) => count + Object.keys(manifest.assets).length,
    0,
  );
  await expect.poll(() => loadedAssets.size).toBe(expectedAssets);
  expect(renderWarnings).toEqual([]);
  await expect(page.locator(".scene-warning")).toHaveCount(0);
  await page.screenshot({
    path: "test-results/game-previews.png",
    fullPage: true,
  });
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
  await expect(page.getByLabel("Display", { exact: true })).toHaveValue("text");
  await expect(page.locator("canvas")).toHaveCount(0);
  await page.getByLabel("Display", { exact: true }).selectOption("graphics");
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
    page.getByRole("button", { name: "Continue training", exact: true }),
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
  await expect(page.getByText("Saved frames", { exact: true })).toBeVisible();
  await expect(page.getByText(/No live training is running/)).toBeVisible();
  await page.getByLabel("Display", { exact: true }).selectOption("graphics");
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

test("completed runs require an extension and continue from their checkpoint", async ({
  page,
}) => {
  await login(page);
  const response = await page.request.post("/api/v1/experiments", {
    data: {
      id: "completed-test",
      config: {
        game: "coin",
        mode: "evolution",
        generations: 2,
        population: 4,
        elites: 1,
        ppo_candidates: 0,
        eval_episodes: 1,
        hidden: [8],
        game_config: { horizon: 4 },
      },
    },
  });
  expect(response.ok()).toBe(true);
  await page.reload();
  await page
    .getByLabel("Open experiment", { exact: true })
    .selectOption("completed-test");
  await nav(page, "Experiments");
  await action(page, "Start");
  const continueButton = page.getByRole("button", {
    name: "Continue training",
    exact: true,
  });
  await expect(continueButton).toBeDisabled();
  await expect(page.getByText(/Generation limit reached/)).toBeVisible();
  await page
    .getByRole("button", { name: "Extend training", exact: true })
    .click();
  await page.getByLabel("Additional generations").fill("3");
  await page
    .getByRole("button", { name: "Confirm extend", exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(continueButton).toBeEnabled();
  await continueButton.click();
  await expect(page.getByRole("dialog")).toContainText(
    "from its latest checkpoint up to 5 generations",
  );
  await page
    .getByRole("button", { name: "Confirm start", exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(continueButton).toBeDisabled();
  const metrics = await page.request.get(
    "/api/v1/experiments/completed-test/metrics",
  );
  expect(
    (await metrics.json()).map((row: { generation: number }) => row.generation),
  ).toEqual([0, 1, 2, 3, 4]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await nav(page, "Spectator");
  await expect(
    page.getByRole("button", { name: "Open champion replay" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/spectator-mobile.png",
    fullPage: true,
  });
});

test("failed game assets produce a visible warning and captured text", async ({
  page,
}) => {
  await login(page);
  await page.route("**/api/v1/games/snake/assets/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "image/svg+xml",
      body: "invalid svg",
    }),
  );
  await nav(page, "Games & Plugins");
  const snake = page
    .locator(".game-card")
    .filter({ has: page.getByRole("heading", { name: "Snake", exact: true }) });
  await expect(snake.getByRole("alert")).toContainText(
    "Some game graphics could not be loaded",
  );
  await expect(snake.locator("pre")).toContainText("H");
});

test("saved Geometry Dash frames stay text-only without asset requests", async ({
  page,
}) => {
  await login(page);
  const assetRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/games/geometrydash/manifest"))
      assetRequests.push(request.url());
  });
  await page
    .getByLabel("Open experiment", { exact: true })
    .selectOption("saved-geometry-text");
  await nav(page, "Spectator");
  await expect(page.getByLabel("Display", { exact: true })).toHaveValue("text");
  await expect(page.locator(".scene-text")).toHaveText(
    "--X-------\n" + "          \n".repeat(7) + ".....^....\n##########",
  );
  await expect(page.locator("canvas")).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(assetRequests).toEqual([]);
  await page.getByLabel("Display", { exact: true }).selectOption("graphics");
  await expect(
    page.getByText(
      "This recording has no graphical scene. Showing captured text.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(assetRequests).toEqual([]);
  await page.getByLabel("Display", { exact: true }).selectOption("text");
  await page.screenshot({
    path: "test-results/geometrydash-text.png",
    fullPage: true,
  });
});
