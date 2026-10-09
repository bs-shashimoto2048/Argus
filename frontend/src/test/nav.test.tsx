/// <reference types="vite/client" />
import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import stylesheet from "../styles.css?raw";
import { renderApp, standardMocks } from "./helpers";

afterEach(() => { vi.unstubAllGlobals(); });

const css = stylesheet.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].split(",").map((x: string) => x.trim()).includes(selector)).map((m) => m[2]);
const propertyValue = (body: string, property: string) => new RegExp(String.raw`(?:^|[;\s])${property}\s*:\s*([^;]+)`).exec(body)?.[1];
const declared = (selector: string, property: string, valuePattern?: RegExp) => rules(selector).some((body) => {
  const found = propertyValue(body, property);
  return found !== undefined && (!valuePattern || valuePattern.test(found));
});

describe("上部ナビゲーション: ロゴは左、メニューは右", () => {
  it("ヘッダーの子要素は ロゴ(左) → メニュー(右) の順で、メニューが4項目ある", async () => {
    standardMocks();
    renderApp("/");
    const header = screen.getByRole("banner");
    const [brand, nav] = [...header.children];
    expect(brand).toHaveClass("app-nav-brand");
    expect(brand).toHaveTextContent("ARGUS");
    expect(brand).toHaveTextContent("遠方監視システム");
    expect(nav).toHaveClass("app-nav-links");
    expect(header.children).toHaveLength(2);
    expect(within(nav as HTMLElement).getAllByRole("link").map((a) => a.textContent)).toEqual(["ダッシュボード", "モニター管理", "履歴・データ", "システム設定"]);
  });

  it("activeなメニューが強調され、遷移で切り替わる", async () => {
    standardMocks();
    const user = userEvent.setup();
    renderApp("/");
    const nav = screen.getByRole("navigation", { name: "メインナビゲーション" });
    expect(within(nav).getByRole("link", { name: "ダッシュボード" })).toHaveClass("active");
    expect(within(nav).getByRole("link", { name: "モニター管理" })).not.toHaveClass("active");
    await user.click(within(nav).getByRole("link", { name: "履歴・データ" }));
    expect(within(nav).getByRole("link", { name: "履歴・データ" })).toHaveClass("active");
    expect(within(nav).getByRole("link", { name: "ダッシュボード" })).not.toHaveClass("active");
    expect(within(nav).getAllByRole("link").filter((a) => a.classList.contains("active"))).toHaveLength(1);
  });

  it("CSS: 左右に分離(space-between)・メニューは右寄せ(margin-left:auto)・ロゴは縮まない", () => {
    expect(declared(".app-nav", "display", /flex/)).toBe(true);
    expect(declared(".app-nav", "justify-content", /space-between/)).toBe(true);
    expect(declared(".app-nav-links", "margin-left", /auto/)).toBe(true);
    expect(declared(".app-nav-links", "justify-content", /flex-end/)).toBe(true);
    expect(declared(".app-nav-brand", "flex", /0 0 auto/)).toBe(true); // ロゴは縮まず左に固定
  });

  it("CSS: 狭い幅でも重ならない(折り返し可・項目は改行しない・gapを詰める)", () => {
    expect(declared(".app-nav", "flex-wrap", /wrap/)).toBe(true);
    expect(declared(".app-nav-links", "flex-wrap", /wrap/)).toBe(true);
    expect(declared(".app-nav-link", "white-space", /nowrap/)).toBe(true);
    expect(css).toMatch(/@media \(max-width: 900px\)[^{]*\{[^}]*\.app-nav/); // 狭い幅用の調整
  });

  it("CSS: active indicator・hover・focusの表現がある(ダークヘッダーは維持)", () => {
    expect(declared(".app-nav-link.active", "border-bottom-color")).toBe(true);
    expect(declared(".app-nav-link:hover", "background")).toBe(true);
    expect(declared(".app-nav-link:focus-visible", "outline")).toBe(true);
    expect(declared(".app-nav", "background", /#0f1b2d/)).toBe(true);
  });

  it("CSS: ページ全体に横スクロールを出さない", () => {
    expect(declared("body", "overflow-x", /hidden/)).toBe(true);
  });
});
