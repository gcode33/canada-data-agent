import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// WCAG 2.2: 4.5:1 for text, 3:1 for non-text marks such as chart lines (A8 §12).
const css = readFileSync(fileURLToPath(new URL("../src/styles.css", import.meta.url)), "utf8");

function tokens(block: string): Record<string, string> {
  return Object.fromEntries([...block.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2]]));
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const light = tokens(css.split("@media (prefers-color-scheme: dark)")[0] ?? "");
const darkOverrides = tokens(css.split("@media (prefers-color-scheme: dark)")[1]?.split("}")[0] ?? "");
const dark = { ...light, ...darkOverrides };

it("parses the dark theme's own tokens (the U1 review found this read nothing)", () => {
  expect(Object.keys(darkOverrides).length).toBeGreaterThanOrEqual(13);
  expect(darkOverrides.bg).not.toBe(light.bg);
});

const TEXT: [string, string][] = [
  ["text", "bg"], ["text", "surface"], ["muted", "bg"], ["muted", "surface"],
  ["link", "bg"], ["link", "surface"], ["ok", "surface"], ["error", "surface"],
  ["banner-text", "banner-bg"],
];
const MARKS: [string, string][] = [["line-1", "surface"], ["line-2", "surface"], ["accent", "surface"]];

for (const [name, theme] of [["light", light], ["dark", dark]] as const) {
  describe(`${name} theme contrast`, () => {
    for (const [fg, bg] of TEXT) {
      it(`${fg} on ${bg} is at least 4.5:1`, () => {
        expect(contrast(theme[fg]!, theme[bg]!)).toBeGreaterThanOrEqual(4.5);
      });
    }
    for (const [fg, bg] of MARKS) {
      it(`${fg} on ${bg} is at least 3:1`, () => {
        expect(contrast(theme[fg]!, theme[bg]!)).toBeGreaterThanOrEqual(3);
      });
    }
  });
}
