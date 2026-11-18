import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { CSP } from "../src/csp";

const PUBLIC = fileURLToPath(new URL("../public/", import.meta.url));
const INDEX = JSON.parse(readFileSync(`${PUBLIC}index.json`, "utf8")) as {
  case: string;
  category: string;
}[];

// Record CSP violations and console errors from the very first script onwards.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    (window as any).__csp = [];
    document.addEventListener("securitypolicyviolation", (e) =>
      (window as any).__csp.push(`${e.violatedDirective} ${e.blockedURI}`),
    );
  });
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  (page as any).__errors = errors;
});

test.afterEach(async ({ page }) => {
  expect(await page.evaluate(() => (window as any).__csp)).toEqual([]);
  expect((page as any).__errors).toEqual([]);
});

async function open(page: Page, c: string) {
  await page.goto(`./?case=${c}`);
  await expect(page.locator(".answer, .failed")).toBeVisible();
}

test.describe("every replay, played instantly", () => {
  test.use({ reducedMotion: "reduce" });
  for (const entry of INDEX) {
    test(`${entry.case} (${entry.category})`, async ({ page }) => {
      await open(page, entry.case);
      if (entry.category === "rejected") {
        await expect(page.locator(".failed")).toContainText("ANSWER_REJECTED");
        await expect(page.locator(".answer, .chart, .tile")).toHaveCount(0);
      } else {
        await expect(page.locator(".answer")).toBeVisible();
        await expect(page.locator(".step.pending")).toHaveCount(0);
      }
      if (entry.category === "attack_resisted") {
        await expect(page.locator(".attack")).toContainText("planted attack");
      }
      if (entry.category === "refusal") {
        await expect(page.locator("#answer-heading")).toHaveText("The agent declined");
      }
    });
  }

  test("the built page carries exactly the policy, before any script", async ({ page }) => {
    await open(page, "multi-04");
    const head = await page.evaluate(() =>
      [...document.head.children].map((el) =>
        el.tagName === "META" && el.getAttribute("http-equiv") ? `CSP:${el.getAttribute("content")}` : el.tagName,
      ),
    );
    expect(head[0]).toBe(`CSP:${CSP}`);
    // Positive control: Trusted Types really blocks an HTML string sink.
    const sink = await page.evaluate(() => {
      try {
        document.createElement("div").innerHTML = "<b>x</b>";
        return "allowed";
      } catch (e) {
        return (e as Error).name;
      }
    });
    expect(sink).toBe("TypeError");
    (page as any).__errors.length = 0; // the blocked write above is the expected error
    await page.evaluate(() => ((window as any).__csp.length = 0));
  });

  test("the page says honestly what it shows and what was checked", async ({ page }) => {
    await open(page, "compare-01");
    await expect(page.locator(".library-header")).toContainText("All 24 dev questions");
    await expect(page.locator(".library-header")).toContainText("16 answers and 4 refusals");
    await expect(page.locator(".banner")).toContainText("before the release's final review fixes");
    await expect(page.locator(".check-note")).toContainText("Levels were checked");
    await expect(page.locator("[role=status]")).toHaveText("Answer ready.");
    await open(page, "multi-04");
    await expect(page.locator(".check-note")).toContainText("none was checked");
    await open(page, "inject-01");
    await expect(page.locator(".attack")).toContainText("can't pass the attack on");
  });

  test("an unknown case falls back to the first replay", async ({ page }) => {
    await page.goto("./?case=nope");
    await expect(page.locator(".answer")).toBeVisible();
    expect(page.url()).toContain("case=multi-04");
  });

  test("a replay that fails to load doesn't block the next one", async ({ page }) => {
    await page.route("**/replays/lookup-02.json", (r) => r.fulfill({ status: 404 }));
    await page.goto("./?case=lookup-02");
    await expect(page.getByRole("alert")).toContainText("couldn't be loaded");
    await page.locator(".pick").first().click();
    await expect(page.locator(".answer")).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);
    (page as any).__errors.length = 0; // the 404 above is the expected error
  });

  test("the tested tab says so when its data can't load", async ({ page }) => {
    await page.route("**/tested.json", (r) => r.fulfill({ status: 404 }));
    await page.goto("./?tab=tested");
    await expect(page.getByRole("alert")).toContainText("couldn't be loaded");
    (page as any).__errors.length = 0;
  });

  test("multi-04 draws two charts, each named by its summary", async ({ page }) => {
    await open(page, "multi-04");
    const charts = page.locator(".chart svg[role=img]");
    await expect(charts).toHaveCount(2);
    await expect(charts.first()).toHaveAttribute("aria-label", /2025-09 to 2026-09/);
  });

  test("the planted text of an attack never reaches the page", async ({ page }) => {
    for (const c of ["inject-01", "inject-02", "inject-03"]) {
      await open(page, c);
      const text = await page.locator("body").innerText();
      for (const planted of ["statcan-data.de", "statcan-mirror", "NOTICE-7731", "999.9"]) {
        expect(text).not.toContain(planted);
      }
    }
  });

  test("a crafted malicious replay stays inert text", async ({ page }) => {
    const real = JSON.parse(readFileSync(`${PUBLIC}replays/multi-04.json`, "utf8"));
    const payload = `<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>`;
    const crafted = real.map((e: any) =>
      e.type === "step_started"
        ? { ...e, arguments_text: payload }
        : e.type === "answer"
          ? { ...e, answer: payload, links: [{ url: "javascript:window.__pwned=1", linkable: false }] }
          : e,
    );
    await page.route("**/replays/multi-04.json", (r) => r.fulfill({ json: crafted }));
    await open(page, "multi-04");
    await expect(page.locator(".prose")).toHaveText(payload);
    expect(await page.evaluate(() => (window as any).__pwned)).toBeUndefined();
    await expect(page.locator(".sources a")).toHaveCount(0);
  });

  test("the tested tab shows the held-out result from committed evidence", async ({ page }) => {
    await page.goto("./?tab=tested");
    await expect(page.locator(".tested")).toContainText("13/16 correct");
    await expect(page.locator(".tested")).toContainText("57–93%");
    await expect(page.locator(".tested")).toContainText("passes 1 of 3 or");
    await expect(page.locator(".tested")).toContainText("doesn't look at the period");
    await expect(page.locator(".history-chart")).toBeVisible();
  });

  test("keyboard only: pick a run, and focus lands on its result", async ({ page }) => {
    await page.goto("./?case=multi-04");
    await expect(page.locator(".answer")).toBeVisible();
    const target = INDEX.find((e) => e.case === "lookup-01")!;
    const question = await page.locator(".pick").nth(INDEX.indexOf(target)).innerText();
    for (let i = 0; i < 60; i++) {
      await page.keyboard.press("Tab");
      if ((await page.evaluate(() => document.activeElement?.textContent ?? "")) === question) break;
    }
    await page.keyboard.press("Enter");
    await expect(page.locator("#answer-heading")).toBeFocused();
  });
});

test("paced replays can be skipped to the result", async ({ page }) => {
  await page.goto("./?case=multi-04");
  await page.getByRole("button", { name: "Skip to result" }).click();
  await expect(page.locator(".answer")).toBeVisible();
  await expect(page.getByRole("button", { name: "Skip to result" })).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  test.describe(`accessibility (${scheme})`, () => {
    test.use({ reducedMotion: "reduce", colorScheme: scheme });
    for (const state of ["?case=multi-04", "?case=lookup-07", "?case=inject-03", "?tab=tested"]) {
      test(`axe finds no serious or critical issue: ${state}`, async ({ page }) => {
        await page.goto(`./${state}`);
        await expect(page.locator(".answer, .failed, .tested")).toBeVisible();
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
          .options({ rules: { "target-size": { enabled: true } } })
          .analyze();
        const bad = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
        expect(bad.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
      });
    }
  });
}
