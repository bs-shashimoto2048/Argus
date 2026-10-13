/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
import stylesheet from "../styles.css?raw";

const strip = (text: string) => text.replace(/\/\*[\s\S]*?\*\//g, "");
const css = strip(stylesheet);
const rules = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].split(",").map((x: string) => x.trim()).includes(selector)).map((m) => m[2]);
const value = (selector: string, property: string) => { const hits = rules(selector).map((b) => new RegExp(String.raw`(?:^|[;\s])${property}\s*:\s*([^;]+)`).exec(b)?.[1]?.trim()).filter(Boolean); return hits[hits.length - 1]; };
const px = (selector: string, property: string) => parseFloat(value(selector, property)!);

// 「Dashboard 密度調整(最終値)」ブロック(styles.css末尾)。ここがDashboardの余白・文字サイズ・映像/履歴の高さの最終値。
const marker = stylesheet.lastIndexOf("/*", stylesheet.indexOf("Dashboard 密度調整(最終値)"));
expect(marker).toBeGreaterThan(0);
const finalBlock = strip(stylesheet.slice(marker));

describe("Dashboard密度調整: 最終値ブロック", () => {
  it("最終ブロックのセレクタはすべてDashboard専用scope(.dashboard-page配下)で、他画面へ漏れない", () => {
    expect(marker).toBeGreaterThan(0);
    const selectors = [...finalBlock.matchAll(/([^{}]+)\{[^{}]*\}/g)].flatMap((m) => m[1].split(",").map((x) => x.trim()));
    expect(selectors.length).toBeGreaterThan(30);
    for (const selector of selectors) expect(selector, selector).toMatch(/^\.(page\.)?dashboard-page\b/);
  });

  it("Dashboardの映像高さ・履歴高さ・Monitor領域の値は、最終ブロックの1か所だけで決まる(同じselectorの後段上書きを残さない)", () => {
    const before = strip(stylesheet.slice(0, marker));
    for (const property of ["height", "max-height"]) {
      const earlier = [...before.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => /\.dashboard-page[^,{]*\.preview-wrap/.test(m[1]) && new RegExp(String.raw`(?:^|[;\s])${property}\s*:`).test(m[2]));
      expect(earlier, `旧 .dashboard-page .preview-wrap の ${property}`).toHaveLength(0);
    }
    expect(before).not.toMatch(/\.dashboard-page \.monitor-grid \{ min-height: 470px/); // 旧: 初回描画用の高さ確保(後段でmin-height:0に上書きされていた)
    expect(before).not.toMatch(/\.dashboard-page \.records-section \{ min-height: 330px/);
    expect(before).not.toMatch(/\.dashboard-page \.monitor-region \{ max-height/); // 最終ブロックで定義
    expect(before).not.toMatch(/\.dashboard-page \.records-area, \.dashboard-page \.records-area\.compact \{ flex: 1 1 0/);
    // 最終ブロックの定義が(複数あれば最後の1つではなく)ただ1つ
    expect(rules(".dashboard-page .monitor-region").filter((b) => /max-height/.test(b))).toHaveLength(1);
    expect(rules(".dashboard-page .monitor-card .card-body .preview-wrap")).toHaveLength(1);
    expect(rules(".dashboard-page .records-area.compact")).toHaveLength(1);
  });

  it("Monitor映像: 高さ上限は viewport比 clamp(165px, 23vh, 262px)、16:9、contain、幅は残り幅+数値と単位の最小幅(約25%)", () => {
    expect(value(".dashboard-page .monitor-card .card-body .preview-wrap", "max-height")).toBe("clamp(165px, 23vh, 262px)");
    expect(value(".dashboard-page .monitor-card .card-body .preview-wrap", "aspect-ratio")).toBe("16 / 9");
    expect(value(".monitor-card .card-body .video-image", "object-fit")).toBe("contain");
    expect(value(".dashboard-page .monitor-card .card-body", "grid-template-columns")).toBe("minmax(0, 1fr) clamp(132px, 25%, 180px)");
  });

  it("文字サイズ: 情報階層ごとに整理(Monitor名14 / badge10.5 / 信頼度14〜15 / 更新11〜12 / 取得状態10.5 / 履歴11.5〜12)。現在値は24〜28pxのまま", () => {
    expect(px(".dashboard-page .monitor-card .card-title", "font-size")).toBe(14);
    expect(px(".dashboard-page .monitor-card .status-badge", "font-size")).toBe(10.5);
    expect(value(".dashboard-page .monitor-card .card-body .card-value-primary strong", "font-size")).toBe("clamp(24px, 1.5vw, 28px)");
    expect(value(".dashboard-page .monitor-card .card-body .card-value-confidence strong", "font-size")).toBe("clamp(14px, 1vw, 15px)");
    expect(value(".dashboard-page .monitor-card .card-body .card-value-updated strong", "font-size")).toBe("clamp(11px, .8vw, 12px)");
    expect(px(".dashboard-page .monitor-card .card-meta", "font-size")).toBe(10.5);
    expect(px(".dashboard-page .summary-chip .chip-label", "font-size")).toBeGreaterThanOrEqual(12);
    expect(px(".dashboard-page .action-button, .dashboard-page .monitoring-control".split(",")[0], "font-size")).toBeLessThanOrEqual(13);
    expect(px(".dashboard-page .trend-legend", "font-size")).toBe(11.5);
    expect(px(".dashboard-page .trend-hint", "font-size")).toBe(11);
    expect(px(".dashboard-page .records-head h2", "font-size")).toBeGreaterThanOrEqual(14);
    expect(px(".dashboard-page .records-head h2", "font-size")).toBeLessThanOrEqual(15);
    expect(px(".dashboard-page .records-head p", "font-size")).toBe(12);
    expect(px(".dashboard-page .history-table th", "font-size")).toBe(11.5);
    expect(px(".dashboard-page .history-table td", "font-size")).toBe(12);
    expect(px(".dashboard-page .history-table .small-button", "font-size")).toBe(11.5);
  });

  it("余白: card-headは上下4〜6px、card-metaは上下2〜3px、通知なし(:empty)は高さを使わない、gapは5〜8px", () => {
    expect(value(".dashboard-page .monitor-card .card-head", "padding")).toBe("4px 10px");
    expect(value(".dashboard-page .monitor-card .card-meta", "padding")).toBe("2px 10px 3px");
    expect(value(".monitor-card .card-notices:empty", "padding")).toBe("0");
    expect(value(".dashboard-page .monitor-card .card-notices:empty", "padding")).toBe("0"); // 通常状態(通知なし)は高さ0
    expect(value(".dashboard-page .monitor-card .card-notices", "min-height") ?? value(".monitor-card .card-notices", "min-height")).toBe("0"); // 空の通知領域を残さない
    expect(value(".page.dashboard-page", "gap")).toBe("5px");
    expect(value(".dashboard-page .monitor-grid", "gap")).toBe("8px");
    expect(value(".dashboard-page .dashboard-toolbar", "gap")).toBe("6px 10px");
    expect(value(".dashboard-page .trend-panel", "padding")).toBe("4px 10px 3px");
    expect(value(".dashboard-page .records-section", "padding")).toBe("5px 10px 2px");
  });

  it("グラフのプロット領域(180px)と履歴の領域(clamp(230px, 28vh, 320px))は維持し、グローバルの履歴高さ・ページ幅は変えない", () => {
    expect(value(".trend-svg", "height")).toBe("180px");
    expect(value(".dashboard-page .records-area.compact", "height")).toBe("clamp(230px, 28vh, 320px)");
    expect(value(".records-area.compact", "height")).toBe("clamp(340px, 54vh, 660px)");
    expect(rules(".page").some((b) => b.includes("min(100% - 48px, 1440px)"))).toBe(true);
  });

  it("他画面の共通部品(.records-head / .history-table / .summary-chip / .action-button)のfont・spacingは、Dashboard専用ブロックの外では変わらない", () => {
    expect(value(".records-head h2", "font-size")).toBe("16px");
    expect(value(".records-head p", "font-size")).toBe("12.5px");
    expect(value(".history-table td", "padding-top")).toBe("3px");
    expect(value(".summary-chip", "height")).toBe("34px");
    expect(value(".action-button", "height")).toBe("40px");
  });
});
