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

  it("Monitor映像: 高さ=viewportの残りの約半分(上限あり)かつカード幅に収まる16:9、contain。右の列(信頼度・更新)は映像の高さの範囲に置く", () => {
    const height = value(".dashboard-page .monitor-card .card-body .preview-wrap", "height")!;
    expect(height).toMatch(/^clamp\(172px, min\(calc\(\(100vh - \d+px\) \/ 2\), calc\(\(\(100vw - 56px\) \/ 3 - 110px\) \* 9 \/ 16\)\), 290px\)$/);
    expect(value(".dashboard-page .monitor-card .card-body .preview-wrap", "aspect-ratio")).toBe("16 / 9");
    expect(value(".monitor-card .card-body .video-image", "object-fit")).toBe("contain");
    expect(value(".dashboard-page .monitor-card .card-body", "grid-template-columns")).toBe("auto minmax(0, 1fr)"); // 映像(幅は16:9で決まる) | 信頼度・更新
    expect(value(".dashboard-page .monitor-card .card-body .card-values", "display")).toBe("contents"); // 現在値は下段(全幅)に出す
    expect(value(".dashboard-page .monitor-card .card-body .card-value-primary", "grid-column")).toBe("1 / -1");
    expect(value(".dashboard-page .monitor-card .card-body .card-value-primary", "display")).toBe("flex"); // 現在値の数値と単位を同じ行に
  });

  it("文字サイズ: Monitorカードは遠目でも読める大きさ(Monitor名18〜20 / badge14 / 現在値36〜42 / 単位17 / 信頼度18〜20 / 更新15〜16 / ラベル14 / 取得状態13.5)", () => {
    expect(value(".dashboard-page .monitor-card .card-title", "font-size")).toBe("clamp(18px, 1.2vw, 20px)");
    expect(value(".dashboard-page .monitor-card .card-title", "font-weight")).toBe("700");
    expect(px(".dashboard-page .monitor-card .status-badge", "font-size")).toBe(14);
    expect(value(".dashboard-page .monitor-card .card-body .card-value-primary strong", "font-size")).toBe("clamp(36px, 2.3vw, 42px)"); // 1366で36 / 1600で約37 / 1920で42
    expect(px(".dashboard-page .current-value-unit", "font-size")).toBe(17);
    expect(value(".dashboard-page .monitor-card .card-body .card-value-confidence strong", "font-size")).toBe("clamp(18px, 1.2vw, 20px)");
    expect(value(".dashboard-page .monitor-card .card-body .card-value-updated strong", "font-size")).toBe("clamp(15px, 1vw, 16px)");
    expect(px(".dashboard-page .monitor-card .card-body .card-values small", "font-size")).toBe(14); // 現在値・信頼度・更新のラベル
    expect(px(".dashboard-page .monitor-card .card-meta", "font-size")).toBe(13.5); // 取得状態
  });

  it("文字サイズ: 履歴・グラフ・toolbarも読める大きさ(履歴本文14.5 / 表ヘッダー13.5 / 詳細ボタン13.5 / 履歴タイトル17 / 説明13.5 / フィルタ14〜14.5 / 凡例・グラフタブ13〜13.5)", () => {
    expect(px(".dashboard-page .history-table td", "font-size")).toBe(14.5);
    expect(px(".dashboard-page .history-table th", "font-size")).toBe(13.5);
    expect(px(".dashboard-page .history-table .small-button", "font-size")).toBe(13.5);
    expect(px(".dashboard-page .records-head h2", "font-size")).toBe(17);
    expect(px(".dashboard-page .records-head p", "font-size")).toBe(13.5);
    expect(px(".dashboard-page .record-filters .filter-select select", "font-size")).toBe(14.5);
    expect(px(".dashboard-page .records-controls .segment", "font-size")).toBe(14);
    expect(px(".dashboard-page .trend-legend", "font-size")).toBe(13);
    expect(px(".dashboard-page .trend-head .segment", "font-size")).toBe(13.5);
    expect(px(".dashboard-page .trend-hint", "font-size")).toBe(12.5);
    expect(px(".dashboard-page .summary-chip .chip-label", "font-size")).toBeGreaterThanOrEqual(12);
    expect(value(".dashboard-page .history-table td", "padding")).toBe("0 12px"); // 文字を大きくした分、列に余裕を持たせる
  });

  it("余白: card-headは上下6px、通知なし(:empty)は高さを使わない、gap・paddingは小さく保つ", () => {
    expect(value(".dashboard-page .monitor-card .card-head", "padding")).toBe("6px 12px");
    expect(value(".monitor-card .card-notices:empty", "padding")).toBe("0");
    expect(value(".dashboard-page .monitor-card .card-notices:empty", "padding")).toBe("0"); // 通常状態(通知なし)は高さ0
    expect(value(".dashboard-page .monitor-card .card-notices", "min-height") ?? value(".monitor-card .card-notices", "min-height")).toBe("0"); // 空の通知領域を残さない
    expect(value(".page.dashboard-page", "gap")).toBe("5px");
    expect(value(".dashboard-page .monitor-grid", "gap")).toBe("8px");
    expect(value(".dashboard-page .trend-panel", "padding")).toBe("5px 12px 4px");
    expect(value(".dashboard-page .records-section", "padding")).toBe("6px 12px 3px");
  });

  it("グラフのプロット領域(180px)は維持。履歴は余った高さを使う(flex)。グローバルの履歴高さ・ページ幅は変えない", () => {
    expect(value(".trend-svg", "height")).toBe("180px");
    expect(value(".dashboard-page .records-section", "flex")).toBe("1 1 auto");
    expect(value(".dashboard-page .records-area.compact", "flex")).toBe("1 1 0"); // 映像の分を引いた残り高さ。固定行数に拘らない
    expect(value(".dashboard-page .records-area.compact", "height")).toBe("auto");
    expect(parseInt(value(".dashboard-page .records-area.compact", "min-height")!)).toBeGreaterThanOrEqual(190);
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
