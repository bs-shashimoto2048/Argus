/// <reference types="vite/client" />
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import stylesheet from "../styles.css?raw";
import { get, monitor, record, renderApp, standardMocks } from "./helpers";
import type { Call } from "./helpers";
import type { Inference, Monitor, ReadingRecord } from "../types";
import { formatJstClock } from "../components/Clock";
import { formatUsage, sortByTimeThenMonitor } from "../components/RecordsTable";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const css = stylesheet.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].split(",").map((x: string) => x.trim()).includes(selector)).map((m) => m[2]);
const propertyValue = (body: string, property: string) => new RegExp(String.raw`(?:^|[;\s])${property}\s*:\s*([^;]+)`).exec(body)?.[1]?.trim();
const value = (selector: string, property: string) => { const hits = rules(selector).map((b) => propertyValue(b, property)).filter(Boolean); return hits[hits.length - 1]; };
const declared = (selector: string, property: string) => rules(selector).some((b) => propertyValue(b, property) !== undefined);
const lastIndexOfRule = (selector: string) => { const m = [...css.matchAll(/([^{}]+)\{/g)].filter((x) => x[1].split(",").map((y: string) => y.trim()).includes(selector)); return m.length ? m[m.length - 1].index! : -1; };

// ================= 常時リアルタイム時計 =================
describe("常時リアルタイム時計(共通トップナビ)", () => {
  const clockText = () => screen.getByLabelText("現在時刻（JST）").textContent!;

  it("共通AppLayoutに表示され(全ルート)、ロゴ側(左)に置かれ、右側のメニューは従来どおり", async () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-09T04:08:42Z"));
    standardMocks();
    const { unmount } = renderApp("/history");
    const header = screen.getByRole("banner");
    expect([...header.children].map((c) => c.className.split(" ")[0])).toEqual(["app-nav-brand", "app-nav-clock", "app-nav-links"]); // [ロゴ][時計][メニュー(右)]
    expect(within(header).getByLabelText("現在時刻（JST）")).toBeInTheDocument();
    expect(within(header).getAllByRole("link").map((a) => a.textContent)).toEqual(["ARGUS遠方監視システム", "ダッシュボード", "モニター管理", "履歴・データ", "システム設定"]);
    unmount();
    renderApp("/settings");
    expect(screen.getByLabelText("現在時刻（JST）")).toBeInTheDocument();
  });

  it("YYYY/MM/DD HH:mm:ss(24時間表記) + JST、Asia/Tokyo基準(UTC 04:08:42 → JST 13:08:42)", () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-09T04:08:42Z"));
    standardMocks();
    renderApp("/");
    expect(clockText()).toBe("2026/10/09 13:08:42 JST");
    expect(clockText()).toMatch(/^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2} JST$/);
  });

  it("JSTの日付またぎ・24時間表記(UTC 15:00 → 翌日 00:00:00。24:00:00 にならない)", () => {
    expect(formatJstClock(new Date("2026-12-31T15:00:00Z"))).toBe("2027/01/01 00:00:00");
    expect(formatJstClock(new Date("2026-10-09T14:59:59Z"))).toBe("2026/10/09 23:59:59");
    expect(formatJstClock(new Date("2026-10-09T03:05:09Z"))).toBe("2026/10/09 12:05:09"); // ゼロ埋め
  });

  it("1秒ごとに更新される", async () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-09T04:08:42Z"));
    standardMocks();
    renderApp("/history");
    expect(clockText()).toBe("2026/10/09 13:08:42 JST");
    act(() => { vi.advanceTimersByTime(1000); });
    expect(clockText()).toBe("2026/10/09 13:08:43 JST");
    act(() => { vi.advanceTimersByTime(3000); });
    expect(clockText()).toBe("2026/10/09 13:08:46 JST");
    act(() => { vi.advanceTimersByTime(60000 - 4000 + 1000); });
    expect(clockText()).toBe("2026/10/09 13:09:43 JST");
  });

  it("Backend APIを毎秒呼ばない(時計の更新でfetchが増えない)", async () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-09T04:08:42Z"));
    const mocks = standardMocks();
    renderApp("/history");
    await act(async () => { await Promise.resolve(); });
    const before = mocks.fn.mock.calls.length;
    act(() => { vi.advanceTimersByTime(3000); }); // 時計は3回更新される(他のpollingは5秒以上)
    expect(clockText()).toBe("2026/10/09 13:08:45 JST");
    expect(mocks.fn.mock.calls.length).toBe(before);
  });

  it("アンマウントでタイマーが止まる(リークしない)", () => {
    vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-09T04:08:42Z"));
    standardMocks();
    const { unmount } = renderApp("/history");
    const timers = vi.getTimerCount();
    unmount();
    expect(vi.getTimerCount()).toBeLessThan(timers);
  });

  it("CSS: tabular-nums・控えめな表示(小さいfont・薄い文字色・背景なし)・separator・固定幅(min-width)・折り返さない", () => {
    expect(value(".app-nav-clock", "font-variant-numeric")).toBe("tabular-nums");
    expect(parseFloat(value(".app-nav-clock", "font-size")!)).toBeLessThan(parseFloat(value(".app-nav-logo", "font-size")!)); // ARGUSより小さい
    expect(value(".app-nav-clock", "color")).toBe("#94a3b8"); // 薄め(ナビのリンク #cbd5e1 より控えめ)
    expect(declared(".app-nav-clock", "background")).toBe(false); // 背景カードを付けない
    expect(declared(".app-nav-clock", "border-left")).toBe(true); // ARGUSとの separator
    expect(value(".app-nav-clock", "min-width")).toMatch(/em$/); // 桁幅固定で秒更新でも幅が揺れない
    expect(value(".app-nav-clock", "white-space")).toBe("nowrap");
    expect(value(".app-nav-clock", "flex")).toBe("0 0 auto");
  });

  it("CSS: 右側のメニューの位置を崩さない(margin-left:auto で右寄せのまま)。狭い幅ではfont・gapを縮小する", () => {
    expect(value(".app-nav-links", "margin-left")).toBe("auto");
    expect(value(".app-nav", "justify-content")).toBe("space-between");
    expect(css).toMatch(/@media \(max-width: 1100px\)\s*\{[^}]*\.app-nav-clock\s*\{[^}]*font-size/);
    expect(css).toMatch(/@media \(max-width: 900px\)\s*\{[^}]*\.app-nav-clock/);
  });
});

// ================= 計測履歴テーブルの視認性 =================
const monitors = [monitor({ id: 4, display_name: "Drum" }), monitor({ id: 2, display_name: "Digital A" }), monitor({ id: 3, display_name: "Digital B" })] as Monitor[]; // 表示順 4 → 2 → 3
const B = (hour: number) => `2026-10-09T${String(hour).padStart(2, "0")}:00:00+09:00`;
const mk = (id: number, monitorId: number, hour: number, over: Partial<ReadingRecord> = {}) => record({ id, monitor_id: monitorId, monitor_name: monitors.find((m) => m.id === monitorId)!.display_name, hour_bucket: B(hour), recorded_at: `2026-10-09T${String(hour - 9).padStart(2, "0")}:00:10`, ...over });
// サーバーは recorded_at DESC, id DESC で返す(同一時刻内はid順)
const items: ReadingRecord[] = [
  mk(33, 3, 13), mk(32, 2, 13, { usage: "0.0" }), mk(31, 4, 13, { usage: null, previous_value: null }),
  mk(23, 3, 12, { value_source: "carried_forward", validation_status: "decrease_detected", raw_value: "0215850" }), mk(22, 2, 12), mk(21, 4, 12, { baseline_conflict: true }),
  mk(13, 3, 11), mk(12, 2, 11, { display_status: "read_error" }), mk(11, 4, 11),
];
const handler = get("/api/records", (c: Call) => { const p = new URL(c.url, "http://x").searchParams; const ids = p.getAll("monitor_id").map(Number); const rows = ids.length ? items.filter((r) => ids.includes(r.monitor_id)) : items; return { items: rows, total: rows.length, limit: Number(p.get("limit")), offset: 0 }; });
const mocks = () => standardMocks([get("/api/monitors", { monitors }), handler]);
const dataRows = () => [...document.querySelectorAll(".history-table tbody tr[data-record-id]")] as HTMLElement[];
const idsOf = () => dataRows().map((r) => Number(r.dataset.recordId));

describe("計測履歴: 使用量の欠損表示", () => {
  it("使用量がnullのときは「-」(0.0は0.0のまま、0も0)", async () => {
    mocks();
    renderApp("/history");
    await waitFor(() => expect(dataRows()).toHaveLength(9));
    const usageOf = (id: number) => (document.querySelector(`tr[data-record-id="${id}"] td.c-usage`) as HTMLElement).textContent;
    expect(usageOf(31)).toBe("-"); // null → -
    expect(usageOf(32)).toBe("0.0"); // 0.0はそのまま(nullと区別)
    expect(usageOf(33)).toBe("4"); // 既定の値
    expect(formatUsage(null)).toBe("-");
    expect(formatUsage("")).toBe("-");
    expect(formatUsage("0.0")).toBe("0.0");
    expect(formatUsage("0")).toBe("0");
    // 前回値など他の列の欠損表示は従来どおり「--」(使用量だけを変更)
    expect((document.querySelector('tr[data-record-id="31"] td.c-prev') as HTMLElement).textContent).toBe("--");
  });

  it("Dashboard・Monitor Detailの履歴(同じテーブル)でも「-」", async () => {
    mocks();
    const { unmount } = renderApp("/");
    await waitFor(() => expect(dataRows()).toHaveLength(9));
    expect((document.querySelector('tr[data-record-id="31"] td.c-usage') as HTMLElement).textContent).toBe("-");
    unmount();
  });
});

describe("計測履歴: 縦罫線・データ列の区切り・数値の色分け", () => {
  it("CSS: ヘッダーと本文の両方に、薄いグレーの縦罫線(1px solid #d7dde7)", () => {
    expect(value(".history-table th, .history-table td".split(",")[0].trim(), "border-left")).toBe("1px solid #d7dde7");
    expect(value(".history-table td", "border-left")).toBe("1px solid #d7dde7");
    expect(value(".history-table th:first-child", "border-left")).toBe("0");
  });

  it("CSS: 「確定値」の左(モニター情報 → 数値データ)と「状態」の左(数値 → 状態・操作)は、通常より強い2px solid #c3cad5", () => {
    for (const selector of [".history-table th:nth-child(3)", ".history-table td:nth-child(3)", ".history-table th:nth-child(7)", ".history-table td:nth-child(7)"]) expect(value(selector, "border-left")).toBe("2px solid #c3cad5");
    expect(parseInt("2px")).toBeGreaterThan(parseInt(value(".history-table td", "border-left")!)); // 通常は1px
  });

  it("CSS: 数値列の色(確定値 #1d4ed8 / 前回値 #475569 / 使用量 #0f766e / 信頼度 #15803d / Raw補助 #b45309)", () => {
    expect(value(".history-table td.c-value .record-value", "color")).toBe("#1d4ed8");
    expect(value(".history-table td.c-prev", "color")).toBe("#475569");
    expect(value(".history-table td.c-usage", "color")).toBe("#0f766e");
    expect(value(".history-table td.c-conf", "color")).toBe("#15803d");
    expect(value(".history-table .record-raw", "color")).toBe("#b45309");
  });

  it("数値列(確定値・前回値・使用量・信頼度)は右寄せ・tabular-nums。モニター名・状態は左寄せのまま", async () => {
    mocks();
    renderApp("/history");
    await waitFor(() => expect(dataRows()).toHaveLength(9));
    const row = dataRows()[0];
    for (const cls of ["c-value", "c-prev", "c-usage", "c-conf"]) expect(row.querySelector(`td.${cls}`)).toHaveClass("num");
    expect(row.querySelector("td.cell-monitor")).not.toHaveClass("num");
    expect(value(".history-table .num", "text-align")).toBe("right");
    expect(value(".history-table .num", "font-variant-numeric")).toBe("tabular-nums");
    expect(value(".history-table th.num", "padding-right")).toBe("12px");
  });

  it("sticky ヘッダーは維持(縦罫線を追加してもヘッダー固定のまま)", () => {
    expect(value(".records-table th", "position")).toBe("sticky");
    expect(value(".records-table-wrap", "overflow")).toBe("auto");
  });
});

describe("計測履歴: 時刻グループ(すべてのモニターのときだけ)", () => {
  it("同じ計測枠(取得時刻)の行を1グループとし、時刻の新しい順 → 同一時刻内はMonitorの表示順(4 → 2 → 3)", async () => {
    mocks();
    renderApp("/history");
    await waitFor(() => expect(dataRows()).toHaveLength(9));
    expect(idsOf()).toEqual([31, 32, 33, 21, 22, 23, 11, 12, 13]); // 13:00(Drum, Digital A, Digital B) → 12:00 → 11:00
    expect(document.querySelector(".history-table")).toHaveClass("grouped");
  });

  it("グループごとに交互の背景クラス(group-a / group-b)が付き、同一グループは同じ背景", async () => {
    mocks();
    renderApp("/history");
    await waitFor(() => expect(dataRows()).toHaveLength(9));
    const cls = (r: HTMLElement) => (r.classList.contains("group-a") ? "a" : r.classList.contains("group-b") ? "b" : "-");
    const seq = dataRows().map(cls);
    expect(new Set(seq.slice(0, 3)).size).toBe(1);
    expect(new Set(seq.slice(3, 6)).size).toBe(1);
    expect(new Set(seq.slice(6, 9)).size).toBe(1);
    expect(seq[0]).not.toBe(seq[3]);
    expect(seq[3]).not.toBe(seq[6]);
    expect(seq[0]).toBe(seq[6]); // A → B → A
    expect(value(".history-table.grouped tbody tr.group-a td", "background")).toBe("#ffffff");
    expect(value(".history-table.grouped tbody tr.group-b td", "background")).toBe("#f7fafc");
  });

  it("時刻が変わる先頭行にだけ強い上罫線(group-start / border-top: 2px solid #cbd5e1)。最初の行には付かない", async () => {
    mocks();
    renderApp("/history");
    await waitFor(() => expect(dataRows()).toHaveLength(9));
    expect(dataRows().map((r) => r.classList.contains("group-start"))).toEqual([false, false, false, true, false, false, true, false, false]);
    expect(value(".history-table.grouped tbody tr.group-start td", "border-top")).toBe("2px solid #cbd5e1");
  });

  it("警告・異常などの状態強調は、時刻グループの背景より優先される(carried_forward / 基準値競合 / 読取異常)", async () => {
    mocks();
    renderApp("/history");
    await waitFor(() => expect(dataRows()).toHaveLength(9));
    const row = (id: number) => document.querySelector(`tr[data-record-id="${id}"]`) as HTMLElement;
    expect(row(23)).toHaveClass("row-state-caution"); // carried_forward
    expect(row(23)).toHaveClass("row-carried");
    expect(row(21)).toHaveClass("row-state-danger"); // 基準値競合
    expect(row(12)).toHaveClass("row-state-danger"); // 読取異常
    expect(row(33)).not.toHaveClass("row-state-caution"); // 正常な行には状態の強調なし
    // 状態の背景ルールは、グループ背景ルールと同じ詳細度で、後に宣言されている(同じ詳細度なら後勝ち) → 優先される
    const grouped = ".history-table.grouped tbody tr.group-b td";
    for (const selector of [".history-table.grouped tbody tr.row-state-caution td", ".history-table.grouped tbody tr.row-state-danger td", ".history-table.grouped tbody tr.row-selected td"]) {
      expect(lastIndexOfRule(selector)).toBeGreaterThan(lastIndexOfRule(grouped));
      expect(selector.split(".").length).toBeGreaterThanOrEqual(grouped.split(".").length); // 詳細度(クラス数)が同等以上
    }
    expect(value(".history-table.grouped tbody tr.row-state-caution td", "background")).toBe("#fffaf0");
    expect(value(".history-table.grouped tbody tr.row-state-danger td", "background")).toBe("#fff3f3");
  });

  it("Monitorを1台だけ選択したときは、時刻グループの交互背景・時刻の区切りを付けない(縦罫線・数値色・状態強調は維持)", async () => {
    mocks();
    const user = userEvent.setup();
    renderApp("/history");
    await waitFor(() => expect(dataRows()).toHaveLength(9));
    const select = screen.getByRole("combobox", { name: "モニター" });
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(4));
    await user.selectOptions(select, "3");
    await waitFor(() => expect(dataRows()).toHaveLength(3));
    expect(document.querySelector(".history-table")).not.toHaveClass("grouped");
    for (const r of dataRows()) { expect(r.classList.contains("group-a") || r.classList.contains("group-b") || r.classList.contains("group-start")).toBe(false); }
    expect(dataRows()[0].querySelector("td.c-usage")).not.toBeNull(); // 数値色分けのクラスは維持
    expect(document.querySelector('tr[data-record-id="23"]')).toHaveClass("row-state-caution"); // 状態強調は維持
    expect(idsOf()).toEqual([33, 23, 13]); // 新しい順のまま
  });

  it("Dashboardの履歴(すべてのモニター)でも時刻グループ化される", async () => {
    mocks();
    renderApp("/");
    await waitFor(() => expect(dataRows()).toHaveLength(9));
    expect(document.querySelector(".dashboard-page .history-table")).toHaveClass("grouped");
    expect(dataRows().filter((r) => r.classList.contains("group-start"))).toHaveLength(2);
  });

  it("並べ替えのロジック: 時刻DESC → Monitor表示順(未知のMonitorは最後)", () => {
    const out = sortByTimeThenMonitor([mk(1, 3, 12), mk(2, 4, 11), mk(3, 2, 12), mk(4, 4, 12), record({ id: 5, monitor_id: 99, hour_bucket: B(12) })], [4, 2, 3]);
    expect(out.map((r) => r.id)).toEqual([4, 3, 1, 5, 2]);
  });
});

// ================= Monitor Detail 設定タブ =================
const inference: Inference = {
  method: "object_detection", engine: "cpp_onnx", model_id: "digital_production_v1.onnx", device: "cpu", video_fps: 5, inference_fps: 1, confidence: 0.25, iou: 0.45, image_size: 640,
  preprocessing: { gray: true, clahe: true, blur: 3 }, roi: { x: 0, y: 0, width: 0.5, height: 0.25 }, roi_mode: "filter_only", context_margin: 0.1, engine_options: {},
  reading: { enabled: true, mode: "majority", window_size: 5, required_matches: 3, min_confidence: null, expected_digits: 7, decimal_position: null, monotonic: true, max_rate_per_minute: null, max_consecutive_failures: 5, allow_rollover: false, rollover_max: null },
};
const detail = monitor({ id: 3, display_name: "エネセン内ガスメータ用１", name: "gas_1", inference, source: { source_type: "url", device_id: null, url: "http://192.168.25.212/view.shtml", username: "user", has_password: true } });
const detailMocks = () => standardMocks([
  get("/api/monitors/3", detail),
  get("/api/monitors/3/reading/diagnostics", { enabled: true, mode: "majority", consecutive_failures: 0, recent_raw: [], confirmed: { value: "1", confidence: 0.9, confirmed_at: null, raw_count: 5, agreement_count: 5, engine: "cpp_onnx", validation_status: "confirmed", raw_value: "1", raw_confidence: 0.9 } }),
  get("/api/monitors/3/runtime", { source_type: "url", state: "running", frame_width: 1920, frame_height: 1080, source_fps: 25, last_frame_timestamp: null, reconnect_count: 0, last_error: null, frame_age: 0.1, stale: false, inference_enabled: true, inference_result: "1", pipeline: null }),
  get("/api/url-history", { items: [] }),
  get("/api/system/inference", { torch: { available: false, version: null, cuda_available: false, cuda_version: null, device_count: 0, devices: [] }, ultralytics: { available: false }, easyocr: { available: false }, tesseract: { python_package: false, executable: false }, devices: [{ value: "cpu", label: "CPU" }] }),
  get("/api/system/models", { models: [] }),
]);
const section = (title: string) => screen.getByRole("heading", { name: title }).closest("section") as HTMLElement;
const header = (title: string) => section(title).querySelector("button.collapsible-header") as HTMLElement; // セクションの開閉ボタン(見出し)

describe("Monitor Detail「設定」タブ: 2カラム・セクション整理・コンパクト化", () => {
  it("セクション構造: 左=基本情報・映像ソース・ROI・前処理 / 右=推論エンジン / モデル・読取安定化設定・保存関連・危険な操作(管理操作)", async () => {
    detailMocks();
    renderApp("/monitors/3?tab=settings");
    await screen.findByRole("heading", { name: "基本情報" });
    const [left, right] = [...document.querySelectorAll(".settings-columns > .settings-col")] as HTMLElement[];
    expect(left).toHaveClass("settings-col-left");
    expect(right).toHaveClass("settings-col-right");
    const heads = (col: HTMLElement) => [...col.querySelectorAll(":scope > section > button h3, :scope > section > h3, :scope > .settings-admin h3")].map((h) => h.textContent);
    expect(heads(left)).toEqual(["基本情報", "映像ソース", "ROI（関心領域）", "前処理"]);
    expect(heads(right)).toEqual(["推論エンジン / モデル", "読取安定化設定", "保存", "危険な操作"]);
    expect(within(right).getByLabelText("保存関連")).toBeInTheDocument();
  });

  it("管理操作(危険な操作)は通常の設定・保存ボタンと分離された領域(.settings-admin)にあり、既定で閉じている", async () => {
    detailMocks();
    const user = userEvent.setup();
    renderApp("/monitors/3?tab=settings");
    await screen.findByRole("heading", { name: "危険な操作" });
    const admin = document.querySelector(".settings-admin") as HTMLElement;
    expect(admin).not.toBeNull();
    expect(within(admin).getByRole("button", { name: /^危険な操作/ })).toHaveAttribute("aria-expanded", "false");
    expect(within(admin).queryByRole("button", { name: "このモニターを削除" })).not.toBeInTheDocument(); // 閉じている間は操作できない
    expect(admin.contains(screen.getByRole("button", { name: "設定を保存" }))).toBe(false); // 保存ボタンと混ざらない
    expect(admin.contains(screen.getByRole("button", { name: "基本情報を保存" }))).toBe(false);
    await user.click(within(admin).getByRole("button", { name: /^危険な操作/ }));
    expect(within(admin).getByRole("button", { name: "このモニターを削除" })).toBeInTheDocument();
    expect(value(".settings-admin", "border-top")).toMatch(/dashed/); // 区切り線で通常設定と分ける
  });

  it("アコーディオン: 主要(基本情報・映像ソース・推論エンジン/モデル)は開き、前処理・ROI・読取安定化設定・危険な操作は閉じる。閉じていても現在値の概要が分かる", async () => {
    detailMocks();
    const user = userEvent.setup();
    renderApp("/monitors/3?tab=settings");
    await screen.findByRole("heading", { name: "基本情報" });
    for (const title of ["基本情報", "映像ソース", "推論エンジン / モデル"]) expect(header(title)).toHaveAttribute("aria-expanded", "true");
    for (const title of ["前処理", "ROI（関心領域）", "読取安定化設定", "危険な操作"]) expect(header(title)).toHaveAttribute("aria-expanded", "false");
    // 閉じた状態の概要(summary)
    expect(within(section("読取安定化設定")).getByText("有効 / majority / 3一致 / 単調増加")).toBeInTheDocument();
    expect(within(section("ROI（関心領域）")).getByText("幅50% × 高さ25%")).toBeInTheDocument();
    expect(within(section("前処理")).getByText("3項目を設定")).toBeInTheDocument();
    expect(within(section("映像ソース")).getByText(/URL 192\.168\.25\.212/)).toBeInTheDocument();
    expect(within(section("推論エンジン / モデル")).getByText("cpp_onnx / digital_production_v1.onnx")).toBeInTheDocument();
    expect(within(section("基本情報")).getByText("エネセン内ガスメータ用１ / Monitor ID 3")).toBeInTheDocument();
    // 開くと中身(設定項目)が現れる。機能は削除されていない
    expect(within(section("読取安定化設定")).getByLabelText(/判定ウィンドウ/)).not.toBeVisible(); // 閉じている間は非表示
    await user.click(header("読取安定化設定"));
    expect(header("読取安定化設定")).toHaveAttribute("aria-expanded", "true");
    expect(within(section("読取安定化設定")).getByLabelText(/判定ウィンドウ/)).toBeVisible();
    expect(within(section("読取安定化設定")).getByLabelText(/必要一致数/)).toBeVisible();
  });

  it("セクションを開閉しても、列とタブの構造(横位置を決めるDOM)は変わらない", async () => {
    detailMocks();
    const user = userEvent.setup();
    renderApp("/monitors/3?tab=settings");
    await screen.findByRole("heading", { name: "基本情報" });
    const structure = () => [...document.querySelectorAll(".settings-col")].map((c) => [...c.children].map((e) => e.getAttribute("aria-label") ?? e.querySelector("h3")?.textContent).join("|")).join("//") + document.querySelectorAll(".detail-tab").length;
    const before = structure();
    await user.click(header("読取安定化設定"));
    await user.click(header("前処理"));
    await user.click(header("ROI（関心領域）"));
    expect(structure()).toBe(before);
    expect(document.querySelectorAll(".settings-columns > .settings-col")).toHaveLength(2);
  });

  it("全設定項目が残っている(映像ソース・推論エンジン/モデル・前処理・ROI・読取安定化設定・保存)", async () => {
    detailMocks();
    const user = userEvent.setup();
    renderApp("/monitors/3?tab=settings");
    await screen.findByRole("heading", { name: "基本情報" });
    await user.click(header("前処理"));
    await user.click(header("ROI（関心領域）"));
    await user.click(header("読取安定化設定"));
    expect(screen.getByLabelText(/内部名/)).toHaveValue("gas_1");
    expect(screen.getByLabelText("表示名")).toBeInTheDocument();
    expect(screen.getByLabelText("設置場所")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "接続確認" })).toBeInTheDocument();
    expect(screen.getByLabelText(/^URL/)).toBeInTheDocument();
    expect(screen.getByLabelText("映像FPS")).toHaveValue(5);
    expect(screen.getByLabelText("推論FPS")).toHaveValue(1);
    expect(screen.getByRole("button", { name: "前処理を編集" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ROIを編集" })).toBeInTheDocument();
    expect(screen.getByLabelText(/最大変化率/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "設定を保存" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "基本情報を保存" })).toBeInTheDocument();
  });

  it("CSS: 2カラムのgrid(minmax(0,1fr) × 2)・狭い幅では1列・compactな余白/入力高・2〜3列の本文grid", () => {
    expect(value(".settings-columns", "display")).toBe("grid");
    expect(rules(".settings-columns").some((b) => propertyValue(b, "grid-template-columns") === "minmax(0, 1fr) minmax(0, 1fr)")).toBe(true); // 横にはみ出さない(minmax(0,...))
    expect(css).toMatch(/@media \(max-width: 980px\)\s*\{\s*\.settings-columns\s*\{\s*grid-template-columns:\s*minmax\(0, 1fr\)/);
    expect(value(".settings-col", "display")).toBe("flex");
    expect(value(".settings-tab .collapsible-body", "padding")).toMatch(/12px/);
    expect(value(".settings-tab .panel select", "height")).toBe("30px"); // inputの高さを揃える
    expect(rules(".settings-tab .source-body").some((b) => propertyValue(b, "grid-template-columns") === "repeat(2, minmax(0, 1fr))")).toBe(true);
    expect(rules(".settings-tab .inference-body").some((b) => propertyValue(b, "grid-template-columns") === "repeat(2, minmax(0, 1fr))")).toBe(true);
    expect(rules(".settings-tab .basic-grid").some((b) => propertyValue(b, "grid-template-columns") === "repeat(3, minmax(0, 1fr))")).toBe(true);
    expect(declared(".section-summary", "text-overflow")).toBe(true); // 概要は1行で省略(横に伸びない)
    expect(value("body", "overflow-x")).toBe("hidden");
  });

  it("基本情報は内部名・表示名・設置場所を1行(3列grid)に、長い説明は折りたたみ(内部名について)へ", async () => {
    detailMocks();
    renderApp("/monitors/3?tab=settings");
    await screen.findByRole("heading", { name: "基本情報" });
    expect(document.querySelector(".basic-grid")!.children).toHaveLength(3);
    const hint = document.querySelector("details.settings-hint") as HTMLDetailsElement;
    expect(hint.open).toBe(false);
    expect(within(hint).getByText("内部名について")).toBeInTheDocument();
  });

  it("映像ソースのカメラ検出は従来どおり明示操作のみ(設定タブを開いただけでは/api/camerasを呼ばない)", async () => {
    const m = detailMocks();
    renderApp("/monitors/3?tab=settings");
    await screen.findByRole("heading", { name: "映像ソース" });
    expect(m.calls.filter((c) => c.url.startsWith("/api/cameras"))).toHaveLength(0);
  });
});

describe("(参考)計測履歴のスクロールイベント", () => {
  it("スクロール領域が存在する", async () => {
    mocks();
    renderApp("/");
    await waitFor(() => expect(dataRows()).toHaveLength(9));
    fireEvent.scroll(screen.getByTestId("records-scroll"));
    expect(screen.getByTestId("records-scroll")).toBeInTheDocument();
  });
});
