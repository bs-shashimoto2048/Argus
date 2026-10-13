import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clampView, panView, timeTicks, zoomView, MIN_VIEW_SPAN_MS } from "../utils/trend";
import { get, record, renderApp, standardMocks } from "./helpers";
import type { Call } from "./helpers";
import type { ReadingRecord } from "../types";

// 「今日」= 2026-10-09 JST。データは 00:00〜14:00 の15点(データ全体=14時間)。
beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-10-09T05:30:00Z")); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const HOUR = 3600_000;
const hourTime = (h: number) => Date.parse(`2026-10-09T${String(h).padStart(2, "0")}:00:00+09:00`);
const rec = (id: number, h: number, over: Partial<ReadingRecord> = {}) =>
  record({ id, monitor_id: 3, monitor_name: "エネセン内ガスメータ用１", hour_bucket: `2026-10-09T${String(h).padStart(2, "0")}:00:00+09:00`, recorded_at: "2026-10-08T15:00:20",
           value: String(100 + id), usage: id === 1 ? "0" : "1", ...over } as Partial<ReadingRecord> & { id: number });
const rows = Array.from({ length: 15 }, (_, h) => rec(h + 1, h));

function recordsFor(all: ReadingRecord[]) {
  return get("/api/records", (c: Call) => {
    const p = new URL(c.url, "http://x").searchParams;
    return { items: all.slice(Number(p.get("offset")), Number(p.get("offset")) + Number(p.get("limit"))), total: all.length, limit: Number(p.get("limit")), offset: Number(p.get("offset")) };
  });
}

const WIDTH = 900, PLOT_LEFT = 58, PLOT_W = WIDTH - 58 - 14;
const mockRect = (svg: Element) => { (svg as SVGElement).getBoundingClientRect = () => ({ left: 0, top: 0, width: WIDTH, height: 180, right: WIDTH, bottom: 180, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect; };
const svgEl = () => screen.getByTestId("trend-svg");
const num = (name: string) => Number(svgEl().getAttribute(name));
const view = () => ({ min: num("data-view-min"), max: num("data-view-max"), span: num("data-view-max") - num("data-view-min") });
const dataRange = () => ({ min: num("data-data-min"), max: num("data-data-max"), span: num("data-data-max") - num("data-data-min") });
const timeAtX = (x: number) => view().min + ((x - PLOT_LEFT) / PLOT_W) * view().span;
const yTicks = () => [...svgEl().querySelectorAll("text[text-anchor=end]")].map((t) => t.textContent);
const resetButton = () => screen.getByRole("button", { name: "全体表示" });

async function renderChart(all: ReadingRecord[] = rows) {
  const mocks = standardMocks([recordsFor(all)]);
  renderApp("/");
  await waitFor(() => expect(document.querySelector(".trend-svg")).not.toBeNull());
  mockRect(svgEl());
  return mocks;
}
const wheel = (deltaY: number, clientX = 450) => fireEvent.wheel(svgEl(), { deltaY, clientX });

describe("ズーム・パンの純粋関数", () => {
  it("clampView: 全体幅・最小幅・データ範囲内に収める", () => {
    expect(clampView({ min: -10 * HOUR, max: 100 * HOUR }, 0, 10 * HOUR)).toEqual({ min: 0, max: 10 * HOUR });
    expect(clampView({ min: 5 * HOUR, max: 5 * HOUR + 60_000 }, 0, 10 * HOUR).max - 5 * HOUR).toBe(MIN_VIEW_SPAN_MS);
    expect(clampView({ min: 9 * HOUR, max: 12 * HOUR }, 0, 10 * HOUR)).toEqual({ min: 7 * HOUR, max: 10 * HOUR });
  });
  it("zoomView: アンカーの時刻の相対位置を保つ", () => {
    const next = zoomView({ min: 0, max: 10 * HOUR }, 2 * HOUR, 0.5, 0, 10 * HOUR);
    expect(next.max - next.min).toBe(5 * HOUR);
    expect((2 * HOUR - next.min) / (next.max - next.min)).toBeCloseTo(0.2);
  });
  it("panView: 端で止まる", () => {
    expect(panView({ min: 2 * HOUR, max: 4 * HOUR }, 100 * HOUR, 0, 10 * HOUR)).toEqual({ min: 8 * HOUR, max: 10 * HOUR });
    expect(panView({ min: 2 * HOUR, max: 4 * HOUR }, -100 * HOUR, 0, 10 * HOUR)).toEqual({ min: 0, max: 2 * HOUR });
  });
  it("timeTicks: JSTの区切りに揃い、表示幅に応じて刻みが変わり、個数が上限以内", () => {
    const day = timeTicks(hourTime(0), hourTime(0) + 24 * HOUR, 7);
    expect(day.length).toBeLessThanOrEqual(7);
    expect(day.every((t) => (t - hourTime(0)) % HOUR === 0)).toBe(true);
    const two = timeTicks(hourTime(10), hourTime(12), 7);
    expect(two.length).toBeLessThanOrEqual(7);
    expect(two[1] - two[0]).toBeLessThan(day[1] - day[0]); // 2時間表示は1日表示より細かい刻み
    expect((two[1] - two[0]) % (15 * 60_000)).toBe(0);
  });
});

describe("TrendChart: X方向のズーム・パン", () => {
  it("1. 初期状態は全期間表示で、「全体表示」ボタンは無効", async () => {
    await renderChart();
    expect(view()).toEqual({ min: dataRange().min, max: dataRange().max, span: 14 * HOUR });
    expect(resetButton()).toBeDisabled();
    expect(svgEl().getAttribute("class")).not.toContain("zoomed");
  });

  it("2/3. wheel上で表示幅が狭くなり、wheel下で広がる(グラフ上のwheelはページスクロールを抑止する)", async () => {
    await renderChart();
    const notCancelled = wheel(-300);
    expect(notCancelled).toBe(false); // preventDefault済み
    const zoomedIn = view().span;
    expect(zoomedIn).toBeLessThan(14 * HOUR);
    wheel(200);
    expect(view().span).toBeGreaterThan(zoomedIn);
  });

  it("グラフの外のwheelは抑止しない", async () => {
    await renderChart();
    expect(fireEvent.wheel(screen.getByRole("heading", { name: "使用量推移" }), { deltaY: -300 })).toBe(true);
    expect(view().span).toBe(14 * HOUR);
  });

  it("4. 期間全体より縮小しない", async () => {
    await renderChart();
    wheel(5000);
    expect(view()).toMatchObject({ min: dataRange().min, max: dataRange().max });
    wheel(-300); wheel(100000);
    expect(view().span).toBe(14 * HOUR);
  });

  it("5. 1時間未満へは拡大しない", async () => {
    await renderChart();
    for (let i = 0; i < 30; i += 1) wheel(-1000);
    expect(view().span).toBe(MIN_VIEW_SPAN_MS);
  });

  it("6. カーソル位置の時刻を中心にズームする(カーソルの時刻が同じ画面位置に残る)", async () => {
    await renderChart();
    const x = 300;
    const before = timeAtX(x);
    wheel(-400, x);
    expect(view().span).toBeLessThan(14 * HOUR);
    expect(Math.abs(timeAtX(x) - before)).toBeLessThan(1000); // 中央固定ではなく、カーソル下の時刻が動かない
  });

  it("7. ドラッグでX方向へパンする(右へドラッグ=過去側へ。Y方向は無視)", async () => {
    await renderChart();
    wheel(-600, 450);
    const before = view();
    fireEvent.mouseDown(svgEl(), { button: 0, clientX: 400, clientY: 50 });
    expect(svgEl().getAttribute("class")).toContain("dragging");
    fireEvent.mouseMove(window, { clientX: 500, clientY: 150 });
    const afterRight = view();
    expect(afterRight.span).toBe(before.span);
    expect(afterRight.min).toBeLessThan(before.min);
    expect(before.min - afterRight.min).toBeCloseTo((100 / PLOT_W) * before.span, -2);
    fireEvent.mouseMove(window, { clientX: 300, clientY: 0 });
    expect(view().min).toBeGreaterThan(afterRight.min);
    fireEvent.mouseUp(window);
    expect(svgEl().getAttribute("class")).not.toContain("dragging");
  });

  it("ズームしていない時はドラッグしても動かない", async () => {
    await renderChart();
    fireEvent.mouseDown(svgEl(), { button: 0, clientX: 400 });
    fireEvent.mouseMove(window, { clientX: 600 });
    fireEvent.mouseUp(window);
    expect(view().span).toBe(14 * HOUR);
  });

  it("8. パンしてもデータ範囲を越えない(端で止まり、空白領域を作らない)", async () => {
    await renderChart();
    wheel(-800, 450);
    const span = view().span;
    fireEvent.mouseDown(svgEl(), { button: 0, clientX: 100 });
    fireEvent.mouseMove(window, { clientX: 5000 });
    expect(view().min).toBe(dataRange().min);
    fireEvent.mouseMove(window, { clientX: -50000 });
    expect(view().max).toBe(dataRange().max);
    expect(view().span).toBe(span);
    fireEvent.mouseUp(window);
  });

  it("9. Y軸の目盛りは、ズーム・パンの前後で変わらない", async () => {
    await renderChart(rows.map((r, i) => ({ ...r, usage: String(i % 5) })));
    const before = yTicks();
    expect(before.length).toBeGreaterThan(1);
    wheel(-800, 450);
    expect(yTicks()).toEqual(before);
    fireEvent.mouseDown(svgEl(), { button: 0, clientX: 100 });
    fireEvent.mouseMove(window, { clientX: 600 });
    fireEvent.mouseUp(window);
    expect(yTicks()).toEqual(before);
  });

  it("10. 全体表示ボタン・ダブルクリック・0キーで元の範囲に戻る", async () => {
    const user = userEvent.setup();
    await renderChart();
    wheel(-800);
    expect(resetButton()).toBeEnabled();
    await user.click(resetButton());
    expect(view().span).toBe(14 * HOUR);
    expect(resetButton()).toBeDisabled();
    wheel(-800);
    fireEvent.doubleClick(svgEl());
    expect(view().span).toBe(14 * HOUR);
    wheel(-800);
    fireEvent.keyDown(svgEl(), { key: "0" });
    expect(view().span).toBe(14 * HOUR);
  });

  it("11. 期間(フィルタ)を変えるとズームがリセットされる", async () => {
    const user = userEvent.setup();
    await renderChart();
    wheel(-800);
    expect(view().span).toBeLessThan(14 * HOUR);
    await user.click(screen.getByRole("button", { name: "過去7日" }));
    await waitFor(() => expect(document.querySelector(".trend-svg")).not.toBeNull());
    expect(view().span).toBe(dataRange().span);
    expect(resetButton()).toBeDisabled();
  });

  it("12. 値無しの赤×と修正済みマーカーは、表示範囲に追従する(範囲外は描かない)", async () => {
    const all = rows.map((r) => {
      if (r.id === 4) return { ...r, usage: null, value: null, numeric_value: null } as ReadingRecord; // 03:00 値無し
      if (r.id === 13) return { ...r, is_corrected: true, correction_count: 1 } as ReadingRecord; // 12:00 修正済み
      return r;
    });
    await renderChart(all);
    expect(document.querySelectorAll(".trend-missing")).toHaveLength(1);
    expect(document.querySelectorAll(".event-manual_corrected")).toHaveLength(1);
    const crossX = () => Number(/M([\d.]+)/.exec(document.querySelector(".trend-missing path")!.getAttribute("d")!)![1]) + 5;
    const fullX = crossX();
    // 右端(12時付近)へズーム: 03:00の×は範囲外、12:00の修正印は範囲内
    wheel(-700, 800); // 表示幅は約3.5時間
    expect(view().min).toBeGreaterThan(hourTime(3));
    expect(document.querySelectorAll(".trend-missing")).toHaveLength(0);
    expect(document.querySelectorAll(".event-manual_corrected")).toHaveLength(1);
    expect(screen.getByText(/値無しの記録があります/)).toBeInTheDocument(); // 警告は期間全体の有無で判定
    // 左端(03:00付近)へ移動: 逆になる
    fireEvent.mouseDown(svgEl(), { button: 0, clientX: 100 });
    fireEvent.mouseMove(window, { clientX: 5000 });
    fireEvent.mouseUp(window);
    expect(document.querySelectorAll(".trend-missing")).toHaveLength(1);
    expect(document.querySelectorAll(".event-manual_corrected")).toHaveLength(0);
    expect(crossX()).toBeCloseTo(PLOT_LEFT + ((hourTime(3) - view().min) / view().span) * PLOT_W, 0);
    expect(crossX()).not.toBeCloseTo(fullX, 0);
    fireEvent.doubleClick(svgEl());
    expect(document.querySelectorAll(".trend-missing")).toHaveLength(1);
    expect(document.querySelectorAll(".event-manual_corrected")).toHaveLength(1);
  });

  it("13. ズーム後のTooltipは、表示範囲内の最寄りの時刻を表示する", async () => {
    await renderChart();
    wheel(-1500, 450);
    const { min, max } = view();
    fireEvent.mouseMove(svgEl(), { clientX: 450, clientY: 50 });
    await waitFor(() => expect(document.querySelector(".trend-tooltip")).not.toBeNull());
    const text = document.querySelector(".trend-tooltip")!.textContent!;
    const hour = Number(/10\/09 (\d\d):00/.exec(text)![1]);
    expect(hourTime(hour)).toBeGreaterThanOrEqual(min - 1);
    expect(hourTime(hour)).toBeLessThanOrEqual(max + 1);
    expect(Math.abs(hourTime(hour) - timeAtX(450))).toBeLessThanOrEqual(HOUR / 2);
    expect(text).toContain("エネセン内ガスメータ用１");
    // 縦線もhoverした時刻の位置にある
    const line = [...svgEl().querySelectorAll("line")].find((l) => l.getAttribute("stroke-dasharray"))!;
    expect(Number(line.getAttribute("x1"))).toBeCloseTo(PLOT_LEFT + ((hourTime(hour) - min) / (max - min)) * PLOT_W, 0);
  });

  it("キーボード: ← → でパン、+ - でズーム、0で全体表示(グラフにfocusがある時だけ)", async () => {
    await renderChart();
    svgEl().focus();
    expect(document.activeElement).toBe(svgEl());
    fireEvent.keyDown(svgEl(), { key: "+" });
    const zoomed = view();
    expect(zoomed.span).toBeLessThan(14 * HOUR);
    const mid = zoomed.min;
    expect(fireEvent.keyDown(svgEl(), { key: "ArrowLeft" })).toBe(false); // 処理したキーはpreventDefault
    expect(view().min).toBeLessThanOrEqual(mid);
    fireEvent.keyDown(svgEl(), { key: "ArrowRight" });
    fireEvent.keyDown(svgEl(), { key: "ArrowRight" });
    expect(view().min).toBeGreaterThan(mid);
    const span = view().span;
    fireEvent.keyDown(svgEl(), { key: "-" });
    expect(view().span).toBeGreaterThan(span);
    fireEvent.keyDown(svgEl(), { key: "0" });
    expect(view().span).toBe(14 * HOUR);
    expect(fireEvent.keyDown(svgEl(), { key: "a" })).toBe(true); // 無関係なキーは奪わない
  });

  it("折れ線はplot領域でclipされ、ズーム・パンでAPIを再取得しない", async () => {
    const mocks = await renderChart();
    const clip = svgEl().querySelector("clipPath rect")!;
    expect(Number(clip.getAttribute("x"))).toBe(PLOT_LEFT);
    expect(svgEl().querySelector("g[clip-path]")!.querySelector("polyline.trend-line")).not.toBeNull();
    const calls = () => mocks.calls.filter((c: Call) => c.url.startsWith("/api/records?")).length;
    const before = calls();
    wheel(-800); wheel(300);
    fireEvent.mouseDown(svgEl(), { button: 0, clientX: 100 });
    fireEvent.mouseMove(window, { clientX: 400 });
    fireEvent.mouseUp(window);
    expect(calls()).toBe(before);
  });
});

describe("連続計測区間の最初のrecord(前回recordなし・usage=0)", () => {
  it("赤×も警告も出さず、Y=0の通常のプロットになり、履歴は前回値「--」・使用量0になる", async () => {
    const first = rec(1, 10, { previous_value: null, usage: "0", value: "372413.7" });
    await renderChart([first]);
    expect(document.querySelectorAll(".trend-missing")).toHaveLength(0);
    expect(screen.queryByText(/値無しの記録があります/)).toBeNull();
    const dot = svgEl().querySelector("circle.trend-dot") as SVGCircleElement; // 1点のみ=孤立点として描かれる
    expect(dot).not.toBeNull();
    const zeroLine = [...svgEl().querySelectorAll("text[text-anchor=end]")].find((t) => t.textContent === "0")!;
    expect(Number(dot.getAttribute("cy"))).toBeCloseTo(Number(zeroLine.getAttribute("y")) - 4, 0); // Y=0の目盛り位置
    const row = await screen.findByText("372413.7");
    const cells = row.closest("tr")!.querySelectorAll("td");
    expect(row.closest("tr")!.querySelector(".c-prev")!.textContent).toBe("--");
    expect(row.closest("tr")!.querySelector(".c-usage")!.textContent).toBe("0");
    expect(cells.length).toBeGreaterThan(3);
  });
});
