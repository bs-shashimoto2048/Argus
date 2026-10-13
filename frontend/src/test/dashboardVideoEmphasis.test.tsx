/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import stylesheet from "../styles.css?raw";
import { get, monitor, renderApp, standardMocks } from "./helpers";

const css = stylesheet.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].split(",").map((x: string) => x.trim()).includes(selector)).map((m) => m[2]);
const value = (selector: string, property: string) => { const hits = rules(selector).map((b) => new RegExp(String.raw`(?:^|[;\s])${property}\s*:\s*([^;]+)`).exec(b)?.[1]?.trim()).filter(Boolean); return hits[hits.length - 1]; };
const clampParts = (text: string) => /^clamp\((\d+)px,\s*(\d+)vh,\s*(\d+)px\)$/.exec(text)!.slice(1).map(Number);

// Dashboardは「Monitor映像・現在値 > 使用量推移 > 計測履歴」の優先順位。履歴を多く見せるために映像を小さくしない。
describe("Dashboardの画面配分(映像優先)", () => {
  it("Monitor映像の高さは、従来(最大170px→#64の220px)より大きく、固定値ではなくviewport比+カード幅に収まるclamp", () => {
    const height = value(".dashboard-page .monitor-card .card-body .preview-wrap", "height")!;
    expect(height.startsWith("clamp(172px, min(")).toBe(true);
    expect(height.endsWith(", 290px)")).toBe(true);
    expect(value(".dashboard-page .monitor-card .card-body .preview-wrap", "aspect-ratio")).toBe("16 / 9");
    // 1600x1000相当: 高さ=(1000-548)/2=226 / 幅の上限=((1600-56)/3-120)*9/16≈229 → 約226px。1920x1080は266px、1366x768は下限165px
    const byHeight = (h: number) => (h - 548) / 2;
    const byWidth = (w: number) => ((w - 56) / 3 - 110) * 9 / 16;
    expect(Math.min(290, Math.max(172, Math.min(byHeight(1000), byWidth(1600))))).toBeCloseTo(226, 0);
    expect(Math.min(290, Math.max(172, Math.min(byHeight(1080), byWidth(1920))))).toBeCloseTo(266, 0);
    expect(Math.min(290, Math.max(172, Math.min(byHeight(768), byWidth(1366))))).toBe(172);
  });

  it("映像は cropも引き伸ばしもせず(object-fit: contain)、画像70% / 数値30%の構成を維持する", () => {
    expect(value(".monitor-card .card-body .video-image", "object-fit")).toBe("contain");
    expect(value(".video-image", "object-fit")).toBe("contain");
    expect(value(".monitor-card .card-body", "grid-template-columns")).toBe("minmax(0, 7fr) minmax(0, 3fr)"); // 旧(全体既定)。Dashboardは映像=残り幅、数値=折り返さない最小幅
    expect(value(".dashboard-page .monitor-card .card-body", "grid-template-columns")).toBe("auto minmax(0, 1fr)"); // 映像 | 信頼度・更新(現在値は下段)
  });

  it("履歴は映像の分を引いた残り高さを使い(flex)、表の中だけがスクロールする。固定行数に拘らない", () => {
    expect(value(".dashboard-page .records-area.compact", "flex")).toBe("1 1 0");
    expect(value(".dashboard-page .records-area.compact", "height")).toBe("auto");
    expect(value(".dashboard-page .records-section", "flex")).toBe("1 1 auto");
    expect(value(".dashboard-page .records-section", "min-height")).toBe("0");
    expect(value(".dashboard-page .records-area .records-table-wrap", "overflow-y")).toBe("auto");
  });

  it("他の画面(Monitor Detail・履歴・データ)の履歴高さは変えない: .records-area.compact / .tall のグローバル定義は従来どおり", () => {
    expect(value(".records-area.compact", "height")).toBe("clamp(340px, 54vh, 660px)");
    expect(value(".records-area.tall", "height")).toMatch(/^clamp\(.*100vh/);
    expect(value(".detail-tab-body .records-area.tall", "height")).toMatch(/^clamp\(.*100vh/);
    expect(value(".monitors-page .records-area", "height")).toBe("auto");
    // Dashboard専用の上書きは .dashboard-page の下だけ(グローバルへ漏れない)
    for (const body of rules(".page.dashboard-page")) expect(body).toMatch(/width/);
    expect(rules(".page").some((b) => b.includes("min(100% - 48px, 1440px)"))).toBe(true); // 他の画面のページ幅は従来どおり(1440px)
  });

  it("Monitor領域: 1〜3台のカードが切れないよう高さの上限を引き上げ、4台以上は領域内だけスクロール(ページを台数で伸ばさない)", () => {
    const [min, vh, max] = clampParts(value(".dashboard-page .monitor-region", "max-height")!);
    expect(min).toBeGreaterThan(240); // 旧: clamp(240px, 36vh, 420px)
    expect(vh).toBeGreaterThan(36);
    expect(max).toBeGreaterThan(420);
    expect(vh * 10).toBeGreaterThan(300); // 1000px高でも、3台のカード(映像拡大後)が切れない上限
    expect(value(".dashboard-page .monitor-region", "overflow-y")).toBe("auto");
    expect(value(".dashboard-page .monitor-region", "overflow-x")).toBe("hidden");
  });

  it("カードの通知欄は映像の大きさに影響しない(映像は固定の高さ、カードはgridで高さが揃う)", () => {
    expect(value(".monitor-grid", "align-items")).toBe("stretch");
    expect(value(".dashboard-page .monitor-card .card-body .preview-wrap", "height")).toMatch(/^clamp\(/);
  });

  it("使用量推移グラフのプロット領域(180px)は変えない", async () => {
    standardMocks([get("/api/records", { items: [], total: 0, limit: 20, offset: 0 })]);
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    expect(value(".trend-svg", "height")).toBe("180px");
  });

  it("Monitor 1・3・7台: カードは全台が領域内に描画され、台数でDashboard全体の構造(領域・グラフ・履歴の順)は変わらない", async () => {
    for (const count of [1, 3, 7]) {
      const monitors = Array.from({ length: count }, (_, i) => monitor({ id: i + 2, display_name: `メーター${i + 2}` }));
      standardMocks([get("/api/monitors", { monitors }), get("/api/records", { items: [], total: 0, limit: 20, offset: 0 })]);
      const view = renderApp("/");
      await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(count));
      const region = screen.getByTestId("monitor-region");
      expect(region.querySelectorAll(".monitor-card")).toHaveLength(count);
      const page = document.querySelector(".dashboard-page") as HTMLElement;
      expect([...page.children].map((e) => ["monitor-region", "trend-panel", "records-section"].find((c) => e.classList.contains(c))).filter(Boolean)).toEqual(["monitor-region", "trend-panel", "records-section"]);
      view.unmount();
    }
  });
});
