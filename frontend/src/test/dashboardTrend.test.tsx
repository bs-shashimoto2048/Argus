/// <reference types="vite/client" />
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import stylesheet from "../styles.css?raw";
import { TrendChart } from "../components/TrendChart";
import { suggestedExportName } from "../components/ExportXlButton";
import { buildSeries, extractChartEvents, niceTicks, splitSegments } from "../utils/trend";
import type { ChartEvent } from "../utils/trend";
import { get, monitor, record, renderApp, route, standardMocks } from "./helpers";
import type { Call } from "./helpers";
import type { Monitor, ReadingRecord } from "../types";

beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-10-09T05:30:00Z")); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); delete (window as unknown as { showSaveFilePicker?: unknown }).showSaveFilePicker; });

const css = stylesheet.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].split(",").map((x: string) => x.trim()).includes(selector)).map((m) => m[2]);
const propertyValue = (body: string, property: string) => new RegExp(String.raw`(?:^|[;\s])${property}\s*:\s*([^;]+)`).exec(body)?.[1]?.trim();
const value = (selector: string, property: string) => { const hits = rules(selector).map((b) => propertyValue(b, property)).filter(Boolean); return hits[hits.length - 1]; };

const hour = (h: number) => `2026-10-09T${String(h).padStart(2, "0")}:00:00+09:00`;
const rec = (id: number, monitorId: number, h: number, usage: string | null, over: Partial<ReadingRecord> = {}) =>
  record({ id, monitor_id: monitorId, monitor_name: `メーター${monitorId}`, hour_bucket: hour(h), recorded_at: `2026-10-08T${String((h + 15) % 24).padStart(2, "0")}:00:20`, usage, value: String(1000 + id), is_corrected: false, correction_count: 0, original_value: null, corrected_at: null, corrected_by: null, raw_confidence: 0.9, inference_at: null, snapshot_consistent: true, ...over } as Partial<ReadingRecord> & { id: number });

const graphCalls = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/records?")).map((c) => new URL(c.url, "http://x").searchParams).filter((p) => p.get("limit") === "1000");
const historyCalls = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/records?")).map((c) => new URL(c.url, "http://x").searchParams).filter((p) => p.get("limit") === "500");

/** monitor_idの指定に応じて、記録を返す(グラフ・履歴の両方)。 */
function recordsFor(all: ReadingRecord[]) {
  return get("/api/records", (c: Call) => {
    const p = new URL(c.url, "http://x").searchParams;
    const ids = p.getAll("monitor_id").map(Number);
    const rows = (ids.length ? all.filter((r) => ids.includes(r.monitor_id)) : all).slice(Number(p.get("offset")), Number(p.get("offset")) + Number(p.get("limit")));
    const total = ids.length ? all.filter((r) => ids.includes(r.monitor_id)).length : all.length;
    return { items: rows, total, limit: Number(p.get("limit")), offset: Number(p.get("offset")) };
  });
}
const threeMonitors = [monitor({ id: 2, display_name: "エネセン内ガスメータ用２" }), monitor({ id: 3, display_name: "エネセン内ガスメータ用１" }), monitor({ id: 4, display_name: "食堂前機械室内メータ用" })];
const sampleRecords = [
  rec(1, 2, 8, "4"), rec(2, 2, 9, "6"), rec(3, 2, 10, null), rec(4, 2, 11, "5"), rec(5, 2, 12, "7"),
  rec(6, 3, 8, "10"), rec(7, 3, 9, "12", { value_source: "carried_forward" }), rec(8, 3, 10, "11", { is_corrected: true, correction_count: 1 }),
  rec(9, 4, 8, "1"), rec(10, 4, 9, "2"),
];
const polylines = () => [...document.querySelectorAll(".trend-svg polyline.trend-line")] as SVGPolylineElement[];

describe("Dashboard: 縦の並び(カード → 使用量推移グラフ → 計測履歴)", () => {
  it("DOM順がMonitorカード領域 → 使用量推移グラフ → 計測履歴", async () => {
    standardMocks([recordsFor(sampleRecords)]);
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    const page = document.querySelector(".dashboard-page") as HTMLElement;
    const order = [...page.children].map((e) => ["monitor-region", "trend-panel", "records-section"].find((c) => e.classList.contains(c))).filter(Boolean);
    expect(order).toEqual(["monitor-region", "trend-panel", "records-section"]);
    expect(page.querySelector(".monitor-region")!.contains(page.querySelector(".monitor-card"))).toBe(true);
  });
});

describe("Dashboard: Monitorカードは最大3列、4台以上はカード領域の中だけがスクロール", () => {
  it("CSS: 3列固定・カード領域は最大高さ+縦スクロール(ページは伸びない)", () => {
    expect(rules(".dashboard-page .monitor-grid").map((b) => propertyValue(b, "grid-template-columns"))).toContain("repeat(3, minmax(0, 1fr))"); // 狭い画面(900px以下)だけ1列
    expect(value(".dashboard-page .monitor-region", "overflow-y")).toBe("auto");
    expect(value(".dashboard-page .monitor-region", "max-height")).toMatch(/^clamp\(/);
    expect(value(".dashboard-page .monitor-region", "overflow-x")).toBe("hidden");
  });

  it("1〜3台は1行(スクロール表示の案内なし)", async () => {
    standardMocks([recordsFor([])]);
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    expect(document.querySelector(".card-count-hint")).toBeNull();
  });

  it("4台以上は「3 / 7台表示」を出し、カードは3列グリッドのまま全台が領域内にある", async () => {
    const seven = Array.from({ length: 7 }, (_, i) => monitor({ id: i + 2, display_name: `メーター${i + 2}` }));
    standardMocks([get("/api/monitors", { monitors: seven }), recordsFor([])]);
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(7));
    expect(document.querySelector(".card-count-hint")).toHaveTextContent("3 / 7台表示");
    const region = screen.getByTestId("monitor-region");
    expect(region.querySelectorAll(".monitor-card")).toHaveLength(7);
    expect(region.querySelector(".monitor-grid")).not.toBeNull();
  });

  it("表示順(display_order)のまま並べ、異常なMonitorを前へ出さない", async () => {
    const list = [monitor({ id: 5, display_name: "A", inference_status: "ok" }), monitor({ id: 3, display_name: "B", inference_status: "read_error" }), monitor({ id: 9, display_name: "C" }), monitor({ id: 2, display_name: "D", status: "error" })];
    standardMocks([get("/api/monitors", { monitors: list }), recordsFor([])]);
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(4));
    const names = [...document.querySelectorAll(".monitor-card")].map((c) => /[ABCD]/.exec(c.querySelector(".card-title")?.textContent ?? "")?.[0]);
    expect(names).toEqual(["A", "B", "C", "D"]);
    expect(document.querySelector(".card-count-hint")).toHaveTextContent("/ 4台表示");
  });
});

describe("使用量推移グラフ", () => {
  it("既定は使用量。Monitorごとに1本の折れ線(系列)と凡例を描く", async () => {
    standardMocks([recordsFor(sampleRecords)]);
    renderApp("/");
    await waitFor(() => expect(document.querySelector(".trend-svg")).not.toBeNull());
    expect(screen.getByRole("button", { name: "使用量" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "累積値" })).toHaveAttribute("aria-pressed", "false");
    expect(document.querySelectorAll(".trend-series")).toHaveLength(3); // モニター2・3・4
    const legend = within(screen.getByRole("list", { name: "凡例" }));
    expect(legend.getByText("エネセン内ガスメータ用２")).toBeInTheDocument();
    const colors = [...document.querySelectorAll(".trend-series")].map((g) => g.getAttribute("stroke"));
    expect(new Set(colors).size).toBe(3); // 系列ごとに色が違う
    expect(screen.getByRole("img", { name: /使用量の推移/ })).toBeInTheDocument();
  });

  it("グラフの高さは180〜220px、SVGの手描き(外部のグラフライブラリなし)", () => {
    const height = parseInt(value(".trend-svg", "height")!);
    expect(height).toBeGreaterThanOrEqual(180);
    expect(height).toBeLessThanOrEqual(220);
  });

  it("[使用量][累積値]の切替で系列の値(y座標)が変わる", async () => {
    standardMocks([recordsFor(sampleRecords)]);
    const user = userEvent.setup();
    renderApp("/");
    await waitFor(() => expect(polylines().length).toBeGreaterThan(0));
    const before = polylines().map((p) => p.getAttribute("points"));
    await user.click(screen.getByRole("button", { name: "累積値" }));
    expect(screen.getByRole("button", { name: "累積値" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("img", { name: /累積値の推移/ })).toBeInTheDocument();
    // 累積値は正式値(value)の系列: 欠損(usage=null)の行も値があるので、折れ線は途切れずつながる
    const after = polylines().map((p) => p.getAttribute("points"));
    expect(after).not.toEqual(before);
    expect(polylines().filter((p) => p.closest(".trend-series")?.getAttribute("data-monitor-id") === "2")).toHaveLength(1);
  });

  it("使用量がnullの点は線を途切れさせる(gap)。つなげて補間しない", async () => {
    standardMocks([recordsFor(sampleRecords)]);
    renderApp("/");
    await waitFor(() => expect(document.querySelector(".trend-series[data-monitor-id='2']")).not.toBeNull());
    const group = document.querySelector(".trend-series[data-monitor-id='2']") as Element;
    // 4,6 | null | 5,7 → 2区間(それぞれ2点)の折れ線
    expect(group.querySelectorAll("polyline.trend-line")).toHaveLength(2);
  });

  it("履歴と同じ条件を共有する: Monitor選択・期間の切替でグラフも同じ条件で取り直す(コントロールは1組)", async () => {
    const mocks = standardMocks([recordsFor(sampleRecords)]);
    const user = userEvent.setup();
    renderApp("/");
    await waitFor(() => expect(graphCalls(mocks.calls).length).toBeGreaterThan(0));
    expect(graphCalls(mocks.calls)[0].get("from")).toBe("2026-10-09T00:00:00+09:00"); // 今日
    expect(graphCalls(mocks.calls)[0].getAll("monitor_id")).toEqual([]);
    expect(screen.getAllByRole("combobox", { name: "モニター" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "過去7日" })).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "過去7日" }));
    await waitFor(() => expect(graphCalls(mocks.calls).pop()!.get("from")).toBe("2026-10-03T00:00:00+09:00"));
    expect(historyCalls(mocks.calls).pop()!.get("from")).toBe("2026-10-03T00:00:00+09:00");

    await user.selectOptions(screen.getByRole("combobox", { name: "モニター" }), "3");
    await waitFor(() => expect(graphCalls(mocks.calls).pop()!.getAll("monitor_id")).toEqual(["3"]));
    expect(historyCalls(mocks.calls).pop()!.getAll("monitor_id")).toEqual(["3"]);
    await waitFor(() => expect(document.querySelectorAll(".trend-series")).toHaveLength(1)); // 個別Monitorでは系列1本
    expect(document.querySelector(".trend-condition")).toHaveTextContent("エネセン内ガスメータ用１・過去7日");

    await user.click(screen.getByRole("button", { name: "任意期間" }));
    await waitFor(() => expect(graphCalls(mocks.calls).pop()!.get("to")).toBe("2026-10-10T00:00:00+09:00"));
  });

  it("1000件を超える期間は、全件が揃うまでページを進めて取得する(offset=1000, 2000...)", async () => {
    const many = Array.from({ length: 2300 }, (_, i) => rec(i + 1, 2, 8, "1", { hour_bucket: `2026-10-09T08:00:00+09:00` }));
    const mocks = standardMocks([recordsFor(many)]);
    renderApp("/");
    await waitFor(() => expect(graphCalls(mocks.calls).map((p) => p.get("offset"))).toEqual(["0", "1000", "2000"]));
  });

  it("記録が無い条件では空表示", async () => {
    standardMocks([recordsFor([])]);
    renderApp("/");
    expect(await screen.findByText("この条件に該当する計測記録はありません。", { selector: ".trend-empty" })).toBeInTheDocument();
  });
});

describe("グラフのイベント構造(ChartEvent)", () => {
  it("carried_forward / baseline_conflict / manual_corrected を記録のフィールドから取り出す", () => {
    const events = extractChartEvents([
      rec(1, 2, 8, "1", { value_source: "carried_forward" }),
      rec(2, 3, 9, "1", { baseline_conflict: true }),
      rec(3, 4, 10, "1", { is_corrected: true, correction_count: 1 }),
      rec(4, 4, 11, "1"),
    ]);
    expect(events.map((e) => e.kind)).toEqual(["carried_forward", "baseline_conflict", "manual_corrected"]);
    expect(events[0]).toEqual({ kind: "carried_forward", monitor_id: 2, time: Date.parse(hour(8)), label: "前回確定値を保持" });
    expect(events.map((e) => e.monitor_id)).toEqual([2, 3, 4]);
  });

  it("既定のrendererは前回値保持・手動修正の印を描く(基準値競合は未描画)", async () => {
    standardMocks([recordsFor([...sampleRecords, rec(11, 4, 11, "3", { baseline_conflict: true })])]);
    renderApp("/");
    await waitFor(() => expect(document.querySelector(".trend-event")).not.toBeNull());
    expect(document.querySelectorAll(".trend-event.event-carried_forward")).toHaveLength(1);
    expect(document.querySelectorAll(".trend-event.event-manual_corrected")).toHaveLength(1);
    expect(document.querySelectorAll(".trend-event.event-baseline_conflict")).toHaveLength(0);
  });

  it("renderEvent hookで印の描画を差し替えられる(将来の基準値競合の印用)", async () => {
    const seen: ChartEvent[] = [];
    standardMocks([recordsFor([rec(1, 2, 8, "4"), rec(2, 2, 9, "5", { baseline_conflict: true })])]);
    render(<TrendChart monitors={threeMonitors as Monitor[]} filter={{ monitorIds: [], period: { mode: "today", startDate: "", endDate: "" } }} renderEvent={(event, pos) => { seen.push(event); return <rect data-testid="custom-marker" x={pos.x} y={pos.y} width={4} height={4} />; }} />);
    await waitFor(() => expect(screen.getByTestId("custom-marker")).toBeInTheDocument());
    expect([...new Set(seen.map((e) => e.kind))]).toEqual(["baseline_conflict"]);
  });
});

describe("グラフ用の純関数", () => {
  it("buildSeries: 表示順のMonitorごとに1系列。記録の無いMonitorは作らない。時刻順", () => {
    const series = buildSeries([rec(2, 3, 9, "2"), rec(1, 3, 8, "1"), rec(3, 2, 8, "5")], threeMonitors, "usage");
    expect(series.map((s) => s.monitor_id)).toEqual([2, 3]);
    expect(series[1].points.map((p) => p.y)).toEqual([1, 2]);
    expect(buildSeries([rec(1, 2, 8, "1", { value: "123.5" })], threeMonitors, "value")[0].points[0].y).toBe(123.5);
  });
  it("splitSegments: nullで区間が分かれ、孤立点は長さ1の区間", () => {
    expect(splitSegments([{ time: 1, y: 1 }, { time: 2, y: null }, { time: 3, y: 3 }, { time: 4, y: 4 }, { time: 5, y: null }, { time: 6, y: 6 }]).map((s) => s.length)).toEqual([1, 2, 1]);
  });
  it("niceTicks", () => {
    expect(niceTicks(0, 10, 4)).toEqual([0, 2.5, 5, 7.5, 10]);
    expect(niceTicks(5, 5)).toEqual([5, 6]);
  });
});

describe("計測履歴テーブル: 各列は折り返さない最小幅", () => {
  it("CSS: 表は内容幅(max-content)・table-layout:auto・全セルnowrap。モニター名の列が余りを吸収しない", () => {
    expect(value(".records-table", "width")).toBe("max-content");
    expect(value(".records-table", "table-layout")).toBe("auto");
    expect(value(".records-table th", "white-space")).toBe("nowrap");
    expect(value(".records-table td", "white-space")).toBe("nowrap");
    expect(value(".records-table .cell-monitor", "max-width")).toBe("none");
    expect(value(".records-table .cell-monitor", "width") ?? "auto").toBe("auto"); // モニター名の列に幅(余り)を割り当てない
  });
  it("維持: 縦罫線・数値列の色・時刻グループ・stickyヘッダー・内部スクロール", () => {
    expect(value(".history-table td", "border-left")).toBe("1px solid #d7dde7");
    expect(value(".history-table td.c-usage", "color")).toBe("#0f766e");
    expect(value(".history-table.grouped tbody tr.group-b td", "background")).toBe("#f7fafc");
    expect(value(".records-table th", "position")).toBe("sticky");
    expect(value(".records-table-wrap", "overflow")).toBe("auto");
  });
  it("1366x768相当: 履歴sectionの最小高さが確保され、表の領域は残りを使う", () => {
    expect(parseInt(value(".dashboard-page .records-section", "min-height")!)).toBeGreaterThanOrEqual(280);
    expect(value(".dashboard-page .records-area", "flex")).toBe("1 1 0");
  });
});

describe("Export (XL)", () => {
  const exportHandler = (calls?: Call[]) => route("POST", "/api/records/export/excel", (c) => { calls?.push(c); return new Response(new Blob(["PK-xlsx"]), { status: 200, headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "Content-Disposition": 'attachment; filename="Argus_MeterRecords_20261009.xlsx"', "X-Argus-Total-Rows": "1234" } }); });

  it("履歴ヘッダーの「任意期間」コントロールの右隣に[Export (XL)]がある", async () => {
    standardMocks([recordsFor(sampleRecords)]);
    renderApp("/");
    const group = await screen.findByRole("group", { name: "表示期間" });
    const button = screen.getByRole("button", { name: "Export (XL)" });
    expect(button.closest(".records-head")).not.toBeNull();
    const buttons = [...(button.closest(".records-controls") as HTMLElement).querySelectorAll("button")].map((b) => b.textContent);
    expect(buttons.slice(-2)).toEqual(["任意期間", "Export (XL)"]);
    expect(group.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("現在のMonitor・期間でPOST(save_to_server=false)し、showSaveFilePickerがあれば保存ダイアログへ書き込む", async () => {
    const posted: Call[] = [];
    const mocks = standardMocks([recordsFor(sampleRecords), exportHandler(posted)]);
    const written: Blob[] = [];
    const picker = vi.fn(async () => ({ createWritable: async () => ({ write: async (b: Blob) => { written.push(b); }, close: async () => {} }) }));
    (window as unknown as { showSaveFilePicker: unknown }).showSaveFilePicker = picker;
    const user = userEvent.setup();
    renderApp("/");
    await user.selectOptions(await screen.findByRole("combobox", { name: "モニター" }), "3");
    await user.click(screen.getByRole("button", { name: "過去7日" }));
    await user.click(screen.getByRole("button", { name: "Export (XL)" }));
    await waitFor(() => expect(written).toHaveLength(1));
    expect(picker).toHaveBeenCalledTimes(1);
    const options = (picker.mock.calls[0] as unknown as [{ suggestedName: string; types: { accept: Record<string, string[]> }[] }])[0];
    expect(options.suggestedName).toBe("argus_records_20261003_20261009.xlsx");
    expect(Object.values(options.types[0].accept)[0]).toEqual([".xlsx"]);
    expect(posted).toHaveLength(1);
    expect(posted[0].body).toEqual({ monitor_ids: [3], from: "2026-10-03T00:00:00+09:00", to: "2026-10-10T00:00:00+09:00", save_to_server: false });
    expect(mocks.calls.filter((c) => c.method === "POST")).toHaveLength(1);
    await waitFor(() => expect(document.querySelector(".export-xl-message")).toHaveTextContent("1,234行"));
  });

  it("showSaveFilePickerが無ければ、通常のダウンロード(<a download>)へフォールバックする", async () => {
    standardMocks([recordsFor(sampleRecords), exportHandler()]);
    const create = vi.fn(() => "blob:mock");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }));
    const clicks: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicks.push(this.download); });
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Export (XL)" }));
    await waitFor(() => expect(clicks).toEqual(["argus_records_20261009_20261009.xlsx"]));
    expect(create).toHaveBeenCalled();
    click.mockRestore();
  });

  it("保存ダイアログのキャンセル(AbortError)は何も表示せず、APIも呼ばない", async () => {
    const posted: Call[] = [];
    standardMocks([recordsFor(sampleRecords), exportHandler(posted)]);
    (window as unknown as { showSaveFilePicker: unknown }).showSaveFilePicker = vi.fn(async () => { throw new DOMException("cancel", "AbortError"); });
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Export (XL)" }));
    await waitFor(() => expect((window as unknown as { showSaveFilePicker: ReturnType<typeof vi.fn> }).showSaveFilePicker).toHaveBeenCalled());
    expect(posted).toHaveLength(0);
    expect(document.querySelector(".export-xl-message")).toBeNull();
  });

  it("出力に失敗したらエラーを表示する(対象なし=404)", async () => {
    standardMocks([recordsFor(sampleRecords), route("POST", "/api/records/export/excel", () => new Response(JSON.stringify({ detail: { code: "NO_RECORDS", message: "none" } }), { status: 404, headers: { "Content-Type": "application/json" } }))]);
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Export (XL)" }));
    await waitFor(() => expect(document.querySelector(".export-xl-message")).toHaveTextContent("記録がありません"));
  });

  it("提案ファイル名: argus_records_開始日_終了日.xlsx(toは排他的なので前日まで)", () => {
    expect(suggestedExportName({ from: "2026-10-03T00:00:00+09:00", to: "2026-10-10T00:00:00+09:00" })).toBe("argus_records_20261003_20261009.xlsx");
  });
});
