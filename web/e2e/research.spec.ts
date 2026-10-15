import { test, expect, type Page } from "@playwright/test";
async function nav(page: Page, name: string) {
  await page
    .getByRole("navigation")
    .getByRole("button", { name, exact: true })
    .click();
}
async function login(page: Page) {
  await page.goto("/");
  await page
    .getByLabel("API token", { exact: true })
    .fill("browser-test-token");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Backend connected")).toBeVisible();
}
async function finishJob(page: Page, kind: string, protocol?: string) {
  await expect
    .poll(
      async () => {
        const jobs = await (
          await page.request.get("/api/v1/research/jobs")
        ).json();
        const job = jobs.find(
          (j: { kind: string; request: { protocol?: string } }) =>
            j.kind === kind && (!protocol || j.request.protocol === protocol),
        );
        if (job?.status === "failed") throw new Error(job.error);
        return job?.status;
      },
      { timeout: 30000 },
    )
    .toBe("completed");
}
test("complete research workspace with real training, annotations, analysis, backups and retention", async ({
  page,
}, testInfo) => {
  test.setTimeout(180000);
  await login(page);
  for (const [name, seed] of [
    ["research-alpha", 31],
    ["research-beta", 32],
  ] as const) {
    const created = await page.request.post("/api/v1/experiments", {
      data: {
        id: name,
        config: {
          game: "rps",
          mode: "evolution",
          seed,
          population: 4,
          elites: 1,
          ppo_candidates: 0,
          generations: 3,
          max_steps: 5,
          hidden: 4,
          eval_episodes: 1,
        },
      },
    });
    expect(created.status()).toBe(201);
    expect(
      (await page.request.post(`/api/v1/experiments/${name}/start`)).ok(),
    ).toBeTruthy();
    await expect
      .poll(
        async () =>
          (await (await page.request.get(`/api/v1/experiments/${name}`)).json())
            .status,
        { timeout: 30000 },
      )
      .toBe("COMPLETED");
  }
  await page.reload();
  await page
    .getByLabel("Open experiment", { exact: true })
    .selectOption("research-alpha");
  await nav(page, "Experiments");
  await page
    .getByLabel("Notes", { exact: true })
    .fill(
      "Hypothesis: compare behavior after mutation. <script>plain text</script>",
    );
  await page.getByLabel("Tags, separated by commas").fill("baseline, rps");
  await page.getByRole("button", { name: "Save notes and tags" }).click();
  await expect(page.getByText("Saved successfully.")).toBeVisible();
  await page.reload();
  await nav(page, "Experiments");
  await page
    .getByLabel("Open experiment", { exact: true })
    .selectOption("research-alpha");
  await expect(page.getByLabel("Notes", { exact: true })).toHaveValue(
    /Hypothesis/,
  );
  await page.getByLabel("Search experiments").fill("baseline");
  await expect(
    page.getByRole("button", { name: "Open research-alpha", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Open research-beta", exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("Search experiments").fill("");
  await nav(page, "Family Trees");
  await expect(
    page.getByRole("button", { name: "Agent 2:0, elite", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Family generation").fill("2");
  await page
    .getByRole("button", { name: "Agent 2:0, elite", exact: true })
    .click();
  await expect(page.getByText("Weights: Available")).toBeVisible();
  await page.getByRole("button", { name: "Bookmark this view" }).click();
  await page.getByLabel("Bookmark title").fill("Promising lineage");
  await page
    .getByRole("button", { name: "Save bookmark", exact: true })
    .click();
  await expect(page.getByText("Saved successfully.")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    animations: "disabled",
    path: testInfo.outputPath("family-tree.png"),
    fullPage: true,
  });
  await nav(page, "Research Bookmarks");
  await expect(
    page.getByRole("heading", { name: "Promising lineage" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open view" }).click();
  await expect(page.getByLabel("Family generation")).toHaveValue("2");
  await nav(page, "Genetic Comparison");
  await page.getByLabel("First agent", { exact: true }).fill("3:0");
  await page.getByLabel("Second agent", { exact: true }).fill("3:0");
  await page.getByRole("button", { name: "Compare weights" }).click();
  await expect(page.getByText("RMS difference 0").first()).toBeVisible();
  await page.getByRole("button", { name: "Run behavior probes" }).click();
  await finishJob(page, "behavior");
  await expect(page.getByText("100.0%")).toBeVisible();
  await nav(page, "Evolution Replay");
  await page.getByLabel("History generation").fill("1");
  await expect(
    page.getByRole("heading", { name: "Evaluated population" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Play history" }).click();
  await expect(
    page.getByRole("button", { name: "Pause history" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Pause history" }).click();
  await nav(page, "Tournament Lab");
  await page.getByLabel(/research-beta/).check();
  await page.getByLabel("Scenarios per champion").fill("3");
  await page.getByRole("button", { name: "Run tournament" }).click();
  await finishJob(page, "tournament");
  await expect(
    page.getByRole("columnheader", { name: "Mean fitness" }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page
    .getByLabel("Protocol", { exact: true })
    .selectOption("rps_head_to_head");
  await page.getByRole("button", { name: "Run tournament" }).click();
  await finishJob(page, "tournament", "rps_head_to_head");
  await expect(
    page
      .getByRole("paragraph")
      .filter({ hasText: "Fitness is net wins per throw" }),
  ).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    animations: "disabled",
    path: testInfo.outputPath("tournament.png"),
    fullPage: true,
  });
  await nav(page, "Benchmarks");
  await page.getByRole("button", { name: "Benchmark research-alpha" }).click();
  await finishJob(page, "benchmark");
  await expect(page.getByText("Median batch latency")).toBeVisible();
  await nav(page, "Backups");
  await page.getByRole("button", { name: "Back up research-alpha" }).click();
  await finishJob(page, "backup");
  await page.getByRole("button", { name: "Verify backup" }).click();
  await expect(
    page.getByText(/checksums and saved model parameters passed/),
  ).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download ZIP" }).click();
  const download = await downloadPromise;
  const downloaded = testInfo.outputPath("research-backup.zip");
  await download.saveAs(downloaded);
  await page.getByRole("button", { name: "Restore as new experiment" }).click();
  await page.getByLabel("Restored experiment name").fill("research-restored");
  await page
    .getByRole("button", { name: "Create restored experiment" })
    .click();
  await expect
    .poll(async () =>
      (
        await page.request.get("/api/v1/experiments/research-restored")
      ).status(),
    )
    .toBe(200);
  const restored = await (
    await page.request.get("/api/v1/experiments/research-restored/research")
  ).json();
  expect(restored.notes).toContain("Hypothesis");
  expect(restored.bookmarks[0].title).toBe("Promising lineage");
  await page.getByLabel("Import backup ZIP").setInputFiles(downloaded);
  await expect(page.getByRole("link", { name: "Download ZIP" })).toHaveCount(2);
  await nav(page, "Storage Manager");
  await page.getByLabel("Weight storage budget (MiB)").fill("0");
  await page.getByLabel(/I understand removed historical weights/).check();
  await page.getByRole("button", { name: "Apply retention" }).click();
  await expect(page.getByText("Saved successfully.")).toBeVisible();
  await nav(page, "Genetic Comparison");
  await page.getByRole("button", { name: "Compare weights" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Weights were not recorded",
  );
  await nav(page, "System Resources");
  await expect(page.getByText("Logical processors")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await nav(page, "Research Bookmarks");
  await expect(
    page.getByRole("heading", { name: "Promising lineage" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    animations: "disabled",
    path: testInfo.outputPath("mobile-notebook.png"),
    fullPage: true,
  });
});
