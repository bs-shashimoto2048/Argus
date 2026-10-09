/// <reference types="vite/client" />
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import stylesheet from "../styles.css?raw";
import { get, json, monitor, record, renderApp, route, standardMocks } from "./helpers";
import type { Call } from "./helpers";
import type { BaselineStatus, Inference, Monitor } from "../types";

beforeEach(() => { localStorage.clear(); vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-10-09T05:30:00Z")); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const css = stylesheet.replace(/\/\*[\s\S]*?\*\//g, "");
/** CSSの最後に書かれた(=有効な)宣言ブロックのうち、selectorを含むものの本文を返す。 */
const rules = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].split(",").map((x: string) => x.trim()).includes(selector)).map((m) => m[2]);
const declared = (selector: string, property: string) => rules(selector).some((body) => new RegExp(`(^|[;\\s])${property}\\s*:`).test(body));
const value = (selector: string, property: string) => { const hits = rules(selector).map((b) => new RegExp(`(?:^|[;\\s])${property}\\s*:\\s*([^;]+)`).exec(b)?.[1]?.trim()).filter(Boolean); return hits[hits.length - 1]; };

const recordsHandler = (items = [record({ id: 1 })]) => get("/api/records", (c: Call) => { const p = new URL(c.url, "http://x").searchParams; return { items, total: items.length, limit: Number(p.get("limit")), offset: Number(p.get("offset")) }; });
const recordCalls = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/records?")).map((c) => new URL(c.url, "http://x").searchParams);

describe("Dashboard: 計測履歴のフィルタ(即時反映)", () => {
  it("Monitorプルダウン: 選択した瞬間に再取得し、適用ボタンはない", async () => {
    const mocks = standardMocks([recordsHandler()]);
    const user = userEvent.setup();
    renderApp("/");
    const select = await screen.findByRole("combobox", { name: "モニター" });
    await waitFor(() => expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["すべてのモニター", "エネセン内ガスメータ用２", "エネセン内ガスメータ用１", "食堂前機械室内メータ用"]));
    const before = recordCalls(mocks.calls).length;
    await user.selectOptions(select, "3");
    await waitFor(() => expect(recordCalls(mocks.calls).length).toBeGreaterThan(before));
    expect(recordCalls(mocks.calls).pop()!.getAll("monitor_id")).toEqual(["3"]);
    expect(screen.queryByRole("button", { name: "適用" })).not.toBeInTheDocument();
  });

  it("表示期間は今日 / 過去7日 / 任意期間の3択。選択した瞬間に切り替わり、選択中が明示される", async () => {
    const mocks = standardMocks([recordsHandler()]);
    const user = userEvent.setup();
    renderApp("/");
    const group = await screen.findByRole("group", { name: "表示期間" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual(["今日", "過去7日", "任意期間"]);
    expect(within(group).getByRole("button", { name: "今日" })).toHaveAttribute("aria-pressed", "true");
    expect(within(group).getByRole("button", { name: "今日" })).toHaveClass("active");
    await user.click(within(group).getByRole("button", { name: "過去7日" }));
    await waitFor(() => expect(recordCalls(mocks.calls).pop()!.get("from")).toBe("2026-10-03T00:00:00+09:00"));
    expect(within(group).getByRole("button", { name: "過去7日" })).toHaveClass("active");
    expect(within(group).getByRole("button", { name: "今日" })).not.toHaveClass("active");
    await user.click(within(group).getByRole("button", { name: "今日" }));
    await waitFor(() => expect(recordCalls(mocks.calls).pop()!.get("from")).toBe("2026-10-09T00:00:00+09:00"));
  });

  it("期間選択BOX(任意期間)は「任意期間」のときだけ表示する", async () => {
    standardMocks([recordsHandler()]);
    const user = userEvent.setup();
    renderApp("/");
    await screen.findByRole("group", { name: "表示期間" });
    expect(screen.queryByRole("group", { name: "期間選択" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "過去7日" }));
    expect(screen.queryByRole("group", { name: "期間選択" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "任意期間" }));
    expect(screen.getByRole("group", { name: "期間選択" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "今日" }));
    expect(screen.queryByRole("group", { name: "期間選択" })).not.toBeInTheDocument();
  });

  it("任意期間: 開始日・終了日が確定した時点で即時更新し、toは終了日の翌日0:00 JST", async () => {
    const mocks = standardMocks([recordsHandler()]);
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "任意期間" }));
    fireEvent.change(screen.getByLabelText("開始日"), { target: { value: "2026-08-20" } });
    fireEvent.change(screen.getByLabelText("終了日"), { target: { value: "2026-08-26" } });
    await waitFor(() => expect(recordCalls(mocks.calls).pop()!.get("from")).toBe("2026-08-20T00:00:00+09:00"));
    expect(recordCalls(mocks.calls).pop()!.get("to")).toBe("2026-08-27T00:00:00+09:00");
  });
});

describe("Dashboard: レイアウト", () => {
  it("ページタイトル「ダッシュボード」がない", async () => {
    standardMocks();
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    expect(screen.queryByRole("heading", { name: "ダッシュボード" })).not.toBeInTheDocument();
    expect(document.querySelector(".dashboard-page h1")).toBeNull();
  });

  it("Monitoring表示は[モニター追加]の右隣(同じ操作グループ)にあり、●Monitoring / FPS / ⚙を持つ", async () => {
    standardMocks();
    renderApp("/");
    const group = await screen.findByRole("group", { name: "ダッシュボード操作" });
    const children = [...group.children] as HTMLElement[];
    expect(children).toHaveLength(2);
    expect(children[0]).toHaveTextContent("＋ モニター追加");
    expect(children[1]).toHaveClass("monitoring-control");
    expect(children[0].nextElementSibling).toBe(children[1]); // 右隣
    expect(within(children[1]).getByText("Monitoring")).toBeInTheDocument();
    expect(children[1]).toHaveTextContent("1 FPS");
    expect(within(children[1]).getByRole("button", { name: "Dashboard設定" })).toBeInTheDocument();
    await waitFor(() => expect(children[1].querySelector(".monitoring-status")).toHaveClass("live")); // 稼働中のMonitorがあれば緑のindicator
  });

  it("⚙で既存のDashboard設定が開き、FPS設定が表示に反映される", async () => {
    standardMocks();
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Dashboard設定" }));
    const dialog = screen.getByRole("dialog", { name: "Dashboard設定" });
    await user.selectOptions(within(dialog).getAllByRole("combobox")[0], "5");
    await user.click(within(dialog).getByRole("button", { name: "×" }));
    expect(screen.getByText("5 FPS")).toBeInTheDocument();
  });

  it("[モニター追加]とMonitoring表示は同じ高さ・角丸・フォントサイズ(同一ルールで定義)", () => {
    for (const property of ["height", "border-radius", "font-size"]) {
      expect(value(".action-button", property)).toBeDefined();
      expect(value(".action-button", property)).toBe(value(".monitoring-control", property));
    }
    expect(value(".action-button", "height")).toBe("40px");
    expect(declared(".monitoring-control", "border")).toBe(true);
    expect(declared(".monitoring-control:focus-within", "box-shadow")).toBe(true); // focus表現
    expect(declared(".monitoring-control:hover", "border-color")).toBe(true); // hover表現
  });
});

describe("履歴表: ヘッダー固定・スクロール", () => {
  it("表はスクロール領域の中に1つのtable(thead + colgroup)として描画され、列がずれない", async () => {
    standardMocks([recordsHandler([record({ id: 1 }), record({ id: 2 })])]);
    renderApp("/");
    await screen.findByText("2件中 1〜2件");
    const area = document.querySelector(".records-area") as HTMLElement;
    const wrap = area.querySelector(".records-table-wrap") as HTMLElement;
    expect(wrap).not.toBeNull();
    const tables = wrap.querySelectorAll("table");
    expect(tables).toHaveLength(1); // ヘッダーと本体が別tableにならない(列位置がずれない)
    expect(tables[0].querySelectorAll("colgroup col")).toHaveLength(9);
    expect(tables[0].querySelectorAll("thead th")).toHaveLength(9);
    expect(tables[0].querySelectorAll("tbody tr")).toHaveLength(2);
  });

  it("Dashboardは固定高さ・履歴・データ画面は画面に応じた高さの領域になる(件数で伸びない)", async () => {
    standardMocks([recordsHandler()]);
    const { unmount } = renderApp("/");
    await screen.findByText("1件中 1〜1件");
    expect(document.querySelector(".records-area")).toHaveClass("compact");
    unmount();
    renderApp("/history");
    await screen.findByText("1件中 1〜1件");
    expect(document.querySelector(".records-area")).toHaveClass("tall");
  });

  it("読込中・0件・通常で同じ領域(records-area)内に描画され、高さが変わらない", async () => {
    standardMocks([recordsHandler([])]);
    renderApp("/");
    const area = document.querySelector(".records-area") as HTMLElement;
    expect(area).toHaveTextContent("読み込み中…");
    expect(await within(area).findByText("この条件に該当する計測記録はありません。")).toBeInTheDocument();
    expect(document.querySelectorAll(".records-area")).toHaveLength(1);
  });

  it("CSS: ヘッダーはsticky固定、本文領域のみ縦スクロール、必要時のみ表の中で横スクロール、列幅固定", () => {
    expect(value(".records-table th", "position")).toBe("sticky");
    expect(value(".records-table th", "top")).toBe("0");
    expect(value(".records-table-wrap", "overflow")).toBe("auto");
    expect(value(".records-table-wrap", "scrollbar-gutter")).toBe("stable"); // scrollbar表示でも列幅が変わらない
    expect(value(".records-table", "table-layout")).toBe("fixed");
    expect(declared(".records-table", "min-width")).toBe(true); // 狭い画面では表の内部だけが横スクロール
    expect(value(".records-area.compact", "height")).toMatch(/px$/);
    expect(value(".records-area.tall", "height")).toMatch(/clamp\(/);
    expect(value("body", "overflow-x")).toBe("hidden"); // ページ全体には横スクロールを出さない
  });
});

describe("画面揺れ防止(CSS)", () => {
  it("ページのscrollbar出現で横揺れしない(scrollbar-gutter: stable)", () => {
    expect(value("html", "scrollbar-gutter")).toBe("stable");
  });
  it("数値はtabular-nums", () => {
    for (const selector of [".records-table td", ".card-values strong", ".status-item strong", ".drawer-fields dd"]) expect(declared(selector, "font-variant-numeric")).toBe(true);
    expect(value(".records-table td", "font-variant-numeric")).toBe("tabular-nums");
  });
  it("Monitorカードは通知欄の高さを確保し、バッジの有無・値の桁数で高さが動かない", async () => {
    expect(value(".monitor-card .card-notices", "min-height")).toMatch(/px$/);
    expect(declared(".monitor-card .card-values", "min-height")).toBe(true);
    expect(value(".monitor-card", "align-self")).toBe("stretch");
    expect(declared(".preview-wrap", "height")).toBe(true); // ライブ画像は固定高さ
    expect(value(".video-image", "object-fit")).toBe("contain");
    standardMocks([get("/api/records", { items: [record({ id: 9, monitor_id: 3, value_source: "carried_forward", raw_value: "0215852", validation_status: "decrease_detected" })], total: 1, limit: 100, offset: 0 })]);
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    // バッジの有無に関わらず、通知欄は全カードに存在する
    await waitFor(() => expect(document.querySelectorAll(".monitor-card .card-notices")).toHaveLength(3));
  });
  it("記録画像(Drawer)は固定の縦横比で、読込前後でサイズが変わらない", () => {
    expect(value(".drawer-image", "aspect-ratio")).toBe("16 / 9");
    expect(value(".drawer-image img", "object-fit")).toBe("contain");
  });
});

// ---- Monitor Detail ----------------------------------------------------------------------------

const inference: Inference = {
  method: "object_detection", engine: "cpp_onnx", model_id: "digital_production_v1.onnx", device: "cpu", video_fps: 5, inference_fps: 1, confidence: 0.25, iou: 0.45, image_size: 640,
  preprocessing: {}, roi: { x: 0, y: 0, width: 1, height: 1 }, roi_mode: "filter_only", context_margin: 0.1, engine_options: {},
  reading: { enabled: true, mode: "majority", window_size: 5, required_matches: 3, min_confidence: null, expected_digits: 7, decimal_position: null, monotonic: true, max_rate_per_minute: null, max_consecutive_failures: 5, allow_rollover: false, rollover_max: null },
};
const detailMonitor: Monitor = monitor({
  id: 3, display_name: "エネセン内ガスメータ用１", name: "gas_1", location: "エネルギーセンター", inference, current_value: "215852", confidence: 0.916,
  source: { source_type: "camera", device_id: 1, url: null, username: null, has_password: false },
  reading_baseline: { value: "215852", state: "active", confirmed_at: "2026-10-09T01:26:22", conflict: false, conflict_status: null, conflict_candidate: null, conflict_since: null, conflict_seconds: 0 },
});
const baselineStatus: BaselineStatus = {
  monitor_id: 3, baseline: { value: "215858", numeric_value: "215858", confirmed_at: "2026-10-08T23:00:36Z", age_seconds: 8720, source: "confirmed", state: "active", epoch: 3, decimal_position: null, expected_digits: null },
  conflict: { status: "decrease_detected", candidate: "215852", count: 100, started_at: "2026-10-08T23:00:37Z", last_at: "2026-10-09T01:25:57Z", duration_seconds: 8719, active: true, alert: true },
  candidate: { value: "215852", agreement_count: 5 }, latest_raw: "0215852", current_confirmed: "215858",
  reading: { enabled: true, monotonic: true, allow_rollover: false, max_rate_per_minute: null, decimal_position: null, expected_digits: 7 }, alert_seconds: 300, runtime_active: true,
};

function detailMocks(extra: ReturnType<typeof route>[] = []) {
  return standardMocks([
    get("/api/monitors/3", detailMonitor),
    get("/api/monitors/3/reading/diagnostics", { enabled: true, mode: "majority", consecutive_failures: 0, recent_raw: [], confirmed: { value: "215852", confidence: 0.9, confirmed_at: null, raw_count: 5, agreement_count: 5, engine: "cpp_onnx", validation_status: "confirmed", raw_value: "0215852", raw_confidence: 0.9 }, conflict: { status: "decrease_detected", candidate: "215852", count: 100, started_at: "2026-10-08T23:00:37Z", last_at: "2026-10-09T01:25:57Z", duration_seconds: 8719, active: true, alert: true }, baseline: { value: "215858", numeric_value: "215858", epoch: 3, confirmed_at: "2026-10-08T23:00:36Z" } }),
    get("/api/monitors/3/runtime", { source_type: "camera", state: "running", frame_width: 1920, frame_height: 1080, source_fps: 4.9, last_frame_timestamp: null, reconnect_count: 0, last_error: null, frame_age: 0.2, stale: false, inference_enabled: true, inference_result: "0215852", pipeline: null }),
    get("/api/monitors/3/reading/baseline", baselineStatus),
    get("/api/monitors/3/reading/baseline/events", { events: [] }),
    get("/api/url-history", { items: [] }),
    get("/api/system/inference", { torch: { available: false, version: null, cuda_available: false, cuda_version: null, device_count: 0, devices: [] }, ultralytics: { available: false }, easyocr: { available: false }, tesseract: { python_package: false, executable: false }, devices: [{ value: "cpu", label: "CPU" }] }),
    get("/api/system/models", { models: [] }),
    get("/api/cameras", { cameras: [{ device_id: 0, label: "Camera 0" }, { device_id: 1, label: "Camera 1" }] }),
    ...extra,
  ]);
}
const camerasCalls = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/cameras"));

describe("Monitor Detail: タブ(日本語表記)", () => {
  it("タブ名は 監視 / 履歴 / 設定 / 診断 (英語のタブ名は画面に出ない)。既定は「監視」", async () => {
    detailMocks();
    renderApp("/monitors/3");
    const tabs = await screen.findByRole("tablist", { name: "モニター詳細" });
    expect(within(tabs).getAllByRole("tab").map((t) => t.textContent)).toEqual(["監視", "履歴", "設定", "診断"]);
    expect(within(tabs).getByRole("tab", { name: "監視" })).toHaveAttribute("aria-selected", "true");
    for (const english of ["Monitoring", "History", "Settings", "Diagnostics"]) expect(within(tabs).queryByText(english)).not.toBeInTheDocument();
  });

  it("?tab= のキーは従来のまま(monitoring / history / settings / diagnostics)で直接開ける", async () => {
    detailMocks([recordsHandler()]);
    renderApp("/monitors/3?tab=diagnostics");
    expect(await screen.findByRole("tab", { name: "診断" })).toHaveAttribute("aria-selected", "true");
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "履歴" }));
    expect(await screen.findByText("1件中 1〜1件")).toBeInTheDocument();
  });

  it("breadcrumbは日本語のまま、Monitor IDは補助表示として残る", async () => {
    detailMocks();
    renderApp("/monitors/3");
    expect(await screen.findByText(/モニター管理 \/ メーター詳細/)).toBeInTheDocument();
    expect(screen.getByText(/Monitor ID: 3/)).toBeInTheDocument();
  });

  it("監視: 主要な項目名が日本語で、live image・確定値・Raw・信頼度・状態・推論エンジン・モデル・最終更新・読取基準値・基準値競合を表示し、危険な操作は置かない", async () => {
    detailMocks();
    renderApp("/monitors/3");
    const panel = await screen.findByRole("tabpanel");
    expect(await within(panel).findByText("現在値（確定）")).toBeInTheDocument();
    for (const label of ["信頼度", "状態", "前回値", "前回の信頼度", "確定日時", "差分"]) expect(within(panel).getAllByText(label).length).toBeGreaterThan(0);
    expect(within(panel).getAllByText("215852").length).toBeGreaterThan(0);
    expect(within(panel).getByText("91.6%")).toBeInTheDocument();
    const summary = within(panel).getByLabelText("読取の詳細");
    for (const label of ["最新推論値（未確定）", "推論エンジン", "モデル", "最終更新", "読取基準値", "基準値競合"]) expect(within(summary).getByText(label)).toBeInTheDocument();
    expect(within(summary).getByText("0215852")).toBeInTheDocument(); // 内部値は原文のまま
    expect(within(summary).getByText("cpp_onnx")).toBeInTheDocument();
    expect(within(summary).getByText("digital_production_v1.onnx")).toBeInTheDocument();
    expect(within(summary).getByText("215852（有効）")).toBeInTheDocument();
    expect(within(summary).getByText("なし")).toBeInTheDocument();
    expect(panel.querySelector("img.video-image")).not.toBeNull(); // live image
    // 英語の項目名(Raw / engine / model / baseline / conflict 等)をUIの見出しとして出さない
    for (const english of ["engine", "model", "baseline", "conflict", "confidence", "Raw（最新・未確定）"]) expect(within(summary).queryByText(english)).not.toBeInTheDocument();
    for (const text of ["このモニターを削除", "基準値を指定して再設定", "設定を保存"]) expect(within(panel).queryByText(text)).not.toBeInTheDocument();
  });

  it("監視: 映像枠にcompactなレイアウトクラスが付き、タブ切替・画像切替でも枠の構造は変わらない", async () => {
    detailMocks();
    const user = userEvent.setup();
    renderApp("/monitors/3");
    const panel = await screen.findByRole("tabpanel");
    expect(panel.querySelector(".mon-layout")).not.toBeNull();
    expect(panel.querySelector(".video-panel.compact")).not.toBeNull();
    expect(panel.querySelectorAll(".video-frame")).toHaveLength(1);
    await user.click(within(panel).getByRole("tab", { name: "推論オーバーレイ" }));
    expect(panel.querySelectorAll(".video-frame")).toHaveLength(1); // 枠は1つのまま(高さが変わらない)
    expect(panel.querySelector(".overlay-legend-slot")).not.toBeNull(); // 凡例の欄は常に確保
    await user.click(within(panel).getByRole("tab", { name: "モニター映像" }));
    expect(panel.querySelectorAll(".video-frame")).toHaveLength(1);
    // 診断 → 監視 と往復しても構造が崩れない
    await user.click(screen.getByRole("tab", { name: "診断" }));
    expect(screen.queryByLabelText("読取の詳細")).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "監視" }));
    expect(screen.getByLabelText("読取の詳細")).toBeInTheDocument();
    expect(document.querySelectorAll(".detail-tab-body")).toHaveLength(1);
  });

  it("CSS: 監視の映像は最大高さ・縦横比・object-fit・最大幅の制約がある(画面を占有しない)", () => {
    expect(value(".video-frame", "aspect-ratio")).toBe("16 / 9");
    expect(value(".video-frame", "max-height")).toBe("var(--video-max-h)");
    expect(value(".video-frame", "--video-max-h")).toMatch(/^clamp\(300px, 46vh, 520px\)$/);
    expect(value(".video-frame", "width")).toMatch(/^min\(100%, calc\(var\(--video-max-h\)/); // 横幅いっぱいに拡大しすぎない
    expect(value(".primary-video .video-frame .video-image", "object-fit")).toBe("contain");
    expect(value(".primary-video .video-frame .video-image", "height")).toBe("100%");
    expect(declared(".mon-current-value strong", "font-variant-numeric") || declared(".status-item strong", "font-variant-numeric")).toBe(true);
    // タブ化後に、ページを100vhへ固定して下を隠す旧ルールが残っていない(設定・診断の下部へ到達できる)
    expect(value(".monitor-detail-page", "overflow")).not.toBe("hidden");
  });

  it("履歴: このMonitorの履歴(Monitor選択なし)・期間3択・記録画像Drawer(項目名は日本語)", async () => {
    const mocks = detailMocks([recordsHandler([record({ id: 5, monitor_id: 3, monitor_name: "エネセン内ガスメータ用１", value_source: "carried_forward", validation_status: "decrease_detected" })])]);
    const user = userEvent.setup();
    renderApp("/monitors/3");
    await user.click(await screen.findByRole("tab", { name: "履歴" }));
    await screen.findByText("1件中 1〜1件");
    expect(screen.queryByRole("combobox", { name: "モニター" })).not.toBeInTheDocument();
    expect(recordCalls(mocks.calls).pop()!.getAll("monitor_id")).toEqual(["3"]);
    await user.click(screen.getByRole("button", { name: "過去7日" }));
    await waitFor(() => expect(recordCalls(mocks.calls).pop()!.get("from")).toBe("2026-10-03T00:00:00+09:00"));
    expect(recordCalls(mocks.calls).pop()!.getAll("monitor_id")).toEqual(["3"]);
    await user.click(screen.getByRole("button", { name: "任意期間" }));
    expect(screen.getByRole("group", { name: "期間選択" })).toBeInTheDocument();
    const row = document.querySelector('tr[data-record-id="5"]') as HTMLElement;
    await user.click(within(row).getByRole("button", { name: /詳細/ }));
    const drawer = await screen.findByRole("dialog", { name: "計測記録の詳細" });
    expect(within(drawer).getByRole("img", { name: "記録時の元画像" })).toHaveAttribute("src", "/api/records/5/image/original");
    for (const label of ["読取判定", "値の由来", "表示状態", "基準値競合", "推論エンジン", "モデル", "最新推論値（Raw）"]) expect(within(drawer).getByText(label)).toBeInTheDocument();
    expect(within(drawer).getByText("decrease_detected")).toBeInTheDocument(); // 内部値は原文
    expect(within(drawer).getByText("前回確定値を保持(carried_forward)")).toBeInTheDocument();
    for (const english of ["validation_status", "value_source", "display_status", "baseline_conflict", "engine", "model_id"]) expect(within(drawer).queryByText(english)).not.toBeInTheDocument();
  });

  it("設定: 見出しが日本語(基本情報・映像ソース・推論エンジン / モデル・前処理・ROI・読取安定化設定・危険な操作)で、保存ボタンもある", async () => {
    detailMocks();
    const user = userEvent.setup();
    renderApp("/monitors/3");
    await user.click(await screen.findByRole("tab", { name: "設定" }));
    const panel = screen.getByRole("tabpanel");
    for (const heading of ["基本情報", "映像ソース", "推論エンジン / モデル", "前処理", "ROI（関心領域）", "読取安定化設定", "危険な操作"]) expect(within(panel).getByRole("heading", { name: heading })).toBeInTheDocument();
    for (const english of ["Source", "Engine / Model", "Preprocessing", "Reading Settings", "Danger Zone", "カメラ / 映像URL", "推論設定（次フェーズ）"]) expect(within(panel).queryByRole("heading", { name: english })).not.toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "前処理を編集" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "ROIを編集" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "設定を保存" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "基本情報を保存" })).toBeInTheDocument();
    expect(within(panel).getByDisplayValue("gas_1")).toBeInTheDocument();
    expect(within(panel).queryByText("基準値を指定して再設定")).not.toBeInTheDocument(); // 基準値の管理操作は通常の設定に置かない
  });

  it("診断: 項目名が日本語(稼働状態・推論エンジン / モデル・推論の状態・読取判定・読取基準値・基準値競合・推論入力画像・推論オーバーレイ)で、内部値は原文のまま", async () => {
    detailMocks();
    const user = userEvent.setup();
    renderApp("/monitors/3");
    await user.click(await screen.findByRole("tab", { name: "診断" }));
    const panel = screen.getByRole("tabpanel");
    for (const name of ["稼働状態", "推論エンジン / モデル", "推論の状態", "読取判定", "読取基準値", "基準値競合", "推論入力画像", "推論オーバーレイ"]) expect(await within(panel).findByLabelText(name)).toBeInTheDocument();
    const runtimeCard = within(panel).getByLabelText("稼働状態");
    expect(within(runtimeCard).getByText("running")).toBeInTheDocument();
    expect(within(runtimeCard).getByText(/4\.9 fps \/ 最新フレーム 0\.2秒前/)).toBeInTheDocument();
    const engineCard = within(panel).getByLabelText("推論エンジン / モデル");
    expect(within(engineCard).getByText("cpp_onnx")).toBeInTheDocument();
    expect(within(engineCard).getByText("digital_production_v1.onnx")).toBeInTheDocument();
    const stateCard = within(panel).getByLabelText("推論の状態");
    expect(within(stateCard).getAllByText("なし")).toHaveLength(2); // 推論エラー / 過去のエラー履歴
    expect(within(stateCard).getByText("推論処理時間")).toBeInTheDocument();
    const reading = within(panel).getByLabelText("読取判定");
    expect(within(reading).getByText("0215852", { exact: false })).toBeInTheDocument();
    expect(within(reading).getByText("confirmed")).toBeInTheDocument(); // 読取判定の内部値
    expect(within(panel).getByLabelText("基準値競合")).toHaveTextContent("decrease_detected");
    for (const english of ["Runtime", "Engine / Model", "Inference input", "Overlay", "validation status", "Raw値:"]) expect(within(panel).queryByText(english)).not.toBeInTheDocument();
  });

  it("診断: 詳細はアコーディオン(既定で閉)、管理操作に到達でき、基準値の再設定が分離されている", async () => {
    detailMocks();
    const user = userEvent.setup();
    renderApp("/monitors/3?tab=diagnostics");
    const admin = await screen.findByLabelText("管理操作");
    expect(admin.tagName).toBe("DETAILS");
    expect((admin as HTMLDetailsElement).open).toBe(false);
    expect(document.querySelector("details.diag-accordion")).not.toBeNull();
    await user.click(within(admin).getByText("管理操作（読取基準値の再設定・リセット）"));
    expect((admin as HTMLDetailsElement).open).toBe(true);
    expect(await within(admin).findByText("基準値を指定して再設定")).toBeInTheDocument();
    expect(within(admin).getByText("基準値をリセット")).toBeInTheDocument();
  });

  it("診断: 画像の枠にサイズ制約(16:9・最大高さ・object-fit)がある。grid/カード構成のCSSがある", () => {
    expect(value(".diag-frame", "aspect-ratio")).toBe("16 / 9");
    expect(value(".diag-frame", "max-height")).toMatch(/^clamp\(130px, 20vh, 220px\)$/);
    expect(value(".diag-frame", "overflow")).toBe("hidden");
    expect(value(".diag-frame .video-image", "object-fit")).toBe("contain");
    expect(rules(".diag-grid").some((body) => /grid-template-columns:\s*repeat\(3, minmax\(0, 1fr\)\)/.test(body))).toBe(true); // 3列(狭い画面では2列/1列に切替)
    expect(declared(".diag-card", "padding")).toBe(true);
  });

  it("診断: 画像は2枚(推論入力画像・推論オーバーレイ)とも固定枠(.diag-frame)の中に描画される", async () => {
    detailMocks();
    renderApp("/monitors/3?tab=diagnostics");
    await screen.findByLabelText("推論入力画像");
    expect(document.querySelectorAll(".diag-frame")).toHaveLength(2);
    for (const frame of document.querySelectorAll(".diag-frame")) expect(frame.querySelector("img.video-image")).not.toBeNull();
    expect(document.querySelector(".diag-grid")).not.toBeNull();
  });
});

describe("Monitor Detail: /api/cameras", () => {
  it("Detailを開いただけ・全タブを巡回しても /api/cameras は呼ばない。現在のsourceはscanなしで表示される", async () => {
    const mocks = detailMocks();
    const user = userEvent.setup();
    renderApp("/monitors/3");
    await screen.findByRole("tablist", { name: "モニター詳細" });
    for (const name of ["履歴", "設定", "診断", "監視", "設定"]) {
      await user.click(screen.getByRole("tab", { name: name }));
    }
    expect(screen.getByText("現在の設定: Camera 1")).toBeInTheDocument(); // scan無しで現在値を表示
    expect(camerasCalls(mocks.calls)).toHaveLength(0);
  });

  it("「カメラ選択(検出)」を押したときだけ /api/cameras を呼び、再スキャンでもう一度呼ぶ", async () => {
    const mocks = detailMocks();
    const user = userEvent.setup();
    renderApp("/monitors/3?tab=settings");
    expect(camerasCalls(mocks.calls)).toHaveLength(0);
    await user.click(await screen.findByRole("button", { name: "カメラ選択（検出）" }));
    await waitFor(() => expect(camerasCalls(mocks.calls)).toHaveLength(1));
    const select = await screen.findByRole("combobox", { name: "接続カメラ" });
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Camera 0", "Camera 1"]);
    expect(select).toHaveValue("1"); // 現在の設定が選択状態
    await user.click(screen.getByRole("button", { name: "再スキャン" }));
    await waitFor(() => expect(camerasCalls(mocks.calls)).toHaveLength(2));
  });

  it("検出に失敗しても現在の設定は保持され、エラーを表示する", async () => {
    detailMocks([route("GET", "/api/cameras", () => json({ detail: "busy" }, 500))]);
    const user = userEvent.setup();
    renderApp("/monitors/3?tab=settings");
    await user.click(await screen.findByRole("button", { name: "カメラ選択（検出）" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("カメラを検出できませんでした");
    expect(screen.getByText("現在の設定: Camera 1")).toBeInTheDocument();
  });
});

describe("基準値の管理操作(reset / rebase)", () => {
  const open = async () => {
    const mocks = detailMocks();
    const user = userEvent.setup();
    renderApp("/monitors/3?tab=diagnostics");
    const admin = await screen.findByLabelText("管理操作");
    await user.click(within(admin).getByText("管理操作（読取基準値の再設定・リセット）")); // アコーディオンを開く
    await within(admin).findByText("基準値を指定して再設定");
    return { mocks, user, admin };
  };

  it("rebase: 現baseline・最新Raw・合意候補・入力値・理由を確認するダイアログを経て、確認後にのみ実行する", async () => {
    const { mocks, user, admin } = await open();
    const rebaseButton = within(admin).getByRole("button", { name: "基準値を指定して再設定" });
    expect(rebaseButton).toBeDisabled(); // 理由・操作者が空の間は押せない
    await user.type(within(admin).getByLabelText(/実メーターで確認した値/), "215852");
    await user.type(within(admin).getByLabelText(/理由/), "実表示を確認");
    await user.type(within(admin).getByLabelText(/操作者/), "tester");
    await user.click(rebaseButton);
    const dialog = await screen.findByRole("alertdialog", { name: "基準値の再設定の確認" });
    expect(within(dialog).getByText("215858")).toBeInTheDocument(); // 現baseline
    expect(within(dialog).getByText("0215852")).toBeInTheDocument(); // 最新Raw
    expect(within(dialog).getByText("215852（一致 5）")).toBeInTheDocument(); // 合意候補
    expect(within(dialog).getByText("215852", { selector: "dd" })).toBeInTheDocument(); // 入力値
    expect(within(dialog).getByText("実表示を確認")).toBeInTheDocument();
    expect(mocks.calls.some((c) => c.url.endsWith("/rebase"))).toBe(false); // 確認前は実行しない
    await user.click(within(dialog).getByRole("button", { name: "キャンセル" }));
    expect(mocks.calls.some((c) => c.url.endsWith("/rebase"))).toBe(false);
  });

  it("rebase: 確認後にPOSTし、成功メッセージを表示する(force未指定)", async () => {
    const { mocks, user, admin } = await open();
    mocks.on(route("POST", "/api/monitors/3/reading/baseline/rebase", () => json({ ...baselineStatus, baseline: { ...baselineStatus.baseline!, value: "215852" }, conflict: null })));
    await user.type(within(admin).getByLabelText(/実メーターで確認した値/), "215852");
    await user.type(within(admin).getByLabelText(/理由/), "実表示を確認");
    await user.type(within(admin).getByLabelText(/操作者/), "tester");
    await user.click(within(admin).getByRole("button", { name: "基準値を指定して再設定" }));
    await user.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "この値で再設定" }));
    expect(await within(admin).findByText(/基準値を再設定しました/)).toBeInTheDocument();
    const call = mocks.calls.find((c) => c.url.endsWith("/rebase"))!;
    expect(call.body).toEqual({ value: "215852", reason: "実表示を確認", operator: "tester", force: false });
  });

  it("rebase: Backendのforce要求(409 FORCE_REQUIRED)は従来どおり確認チェックを求める", async () => {
    const { mocks, user, admin } = await open();
    mocks.on(route("POST", "/api/monitors/3/reading/baseline/rebase", () => json({ detail: { code: "FORCE_REQUIRED", message: "x", candidate: "215852", requested: "300000", tolerance: "5" } }, 409)));
    await user.type(within(admin).getByLabelText(/実メーターで確認した値/), "300000");
    await user.type(within(admin).getByLabelText(/理由/), "確認");
    await user.type(within(admin).getByLabelText(/操作者/), "tester");
    await user.click(within(admin).getByRole("button", { name: "基準値を指定して再設定" }));
    await user.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "この値で再設定" }));
    expect(await within(admin).findByText(/大きく異なります/)).toBeInTheDocument();
    expect(within(admin).getByRole("button", { name: "基準値を指定して再設定" })).toBeDisabled(); // 強制確認のチェックが必要
  });

  it("reset: 確認(window.confirm)後にPOSTする", async () => {
    const { mocks, user, admin } = await open();
    mocks.on(route("POST", "/api/monitors/3/reading/baseline/reset", () => json(baselineStatus)));
    vi.stubGlobal("confirm", vi.fn(() => true));
    await user.type(within(admin).getByLabelText(/理由/), "メーター交換");
    await user.type(within(admin).getByLabelText(/操作者/), "tester");
    await user.click(within(admin).getByRole("button", { name: "基準値をリセット" }));
    await waitFor(() => expect(mocks.calls.some((c) => c.url.endsWith("/reset"))).toBe(true));
    expect(mocks.calls.find((c) => c.url.endsWith("/reset"))!.body).toEqual({ reason: "メーター交換", operator: "tester" });
  });
});

describe("既存機能の維持", () => {
  it("Excel出力・データ保存設定・モニター管理への導線が残っている", async () => {
    standardMocks([recordsHandler()]);
    const user = userEvent.setup();
    renderApp("/history");
    expect(await screen.findByRole("button", { name: "Excel出力" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "システム設定" }));
    expect(await screen.findByLabelText("画像保存先")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "モニター管理" }));
    expect(await screen.findByRole("button", { name: "＋ 新規モニター" })).toBeInTheDocument();
  });
  it("履歴のDrawer(Dashboard)", async () => {
    standardMocks([recordsHandler([record({ id: 8 })])]);
    const user = userEvent.setup();
    renderApp("/");
    const row = await waitFor(() => { const r = document.querySelector('tr[data-record-id="8"]') as HTMLElement; expect(r).toBeTruthy(); return r; });
    await user.click(within(row).getByRole("button", { name: /詳細/ }));
    expect(await screen.findByRole("dialog", { name: "計測記録の詳細" })).toBeInTheDocument();
  });
});
