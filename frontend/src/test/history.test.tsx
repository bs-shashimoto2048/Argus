import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { get, json, record, renderApp, route, standardMocks } from "./helpers";
import type { Call } from "./helpers";

beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-10-09T05:30:00Z")); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const carried = record({ id: 3, monitor_id: 3, monitor_name: "エネセン内ガスメータ用１\t", recorded_at: "2026-10-08T23:00:20", value: "215858", raw_value: "0215850", previous_value: "215836", usage: "22", value_source: "carried_forward", validation_status: "decrease_detected" });
const notSaved = record({ id: 1, recorded_at: "2026-10-08T09:00:15", image_status: "not_saved", original_image_path: null, overlay_image_path: null, usage: null, previous_value: null });
const normal = record({ id: 2, recorded_at: "2026-10-08T10:00:15" });

function recordsHandler(items = [normal, notSaved, carried], total = items.length) {
  return get("/api/records", (c: Call) => { const p = new URL(c.url, "http://x").searchParams; return { items, total, limit: Number(p.get("limit")), offset: Number(p.get("offset")) }; });
}
const lastRecordsUrl = (calls: Call[]) => new URL(calls.filter((c) => c.url.startsWith("/api/records?")).pop()!.url, "http://x");

describe("履歴・データ: 取得とフィルタ", () => {
  it("1時間記録を表(取得日時・モニター・確定値・前回値・使用量・信頼度・状態・画像・詳細)で表示する", async () => {
    standardMocks([recordsHandler()]);
    renderApp("/history");
    await screen.findByText("1時間ごとの計測履歴");
    const headers = (await screen.findAllByRole("columnheader")).map((h) => h.textContent);
    expect(headers).toEqual(["取得日時", "モニター", "確定値", "前回値", "使用量", "信頼度", "状態", "画像", "詳細"]);
    const rows = document.querySelectorAll(".records-table tbody tr");
    expect(rows).toHaveLength(3);
    expect(within(rows[0] as HTMLElement).getByText("10/08 19:00")).toBeInTheDocument(); // UTC 10:00 → JST 19:00
    expect(within(rows[0] as HTMLElement).getByText("95.7%")).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText("正常")).toBeInTheDocument();
  });

  it("初期は今日、「過去7日」「任意期間」で from/to が変わる(toは排他的で終了日の翌日0:00)", async () => {
    const mocks = standardMocks([recordsHandler()]);
    const user = userEvent.setup();
    renderApp("/history");
    await waitFor(() => expect(lastRecordsUrl(mocks.calls).searchParams.get("from")).toBe("2026-10-09T00:00:00+09:00"));
    expect(lastRecordsUrl(mocks.calls).searchParams.get("to")).toBe("2026-10-10T00:00:00+09:00");

    await user.click(screen.getByRole("button", { name: "過去7日" }));
    await waitFor(() => expect(lastRecordsUrl(mocks.calls).searchParams.get("from")).toBe("2026-10-03T00:00:00+09:00"));
    expect(lastRecordsUrl(mocks.calls).searchParams.get("to")).toBe("2026-10-10T00:00:00+09:00");

    await user.click(screen.getByRole("button", { name: "任意期間" }));
    fireEvent.change(screen.getByLabelText("開始日"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText("終了日"), { target: { value: "2026-10-08" } });
    await waitFor(() => expect(lastRecordsUrl(mocks.calls).searchParams.get("from")).toBe("2026-10-01T00:00:00+09:00"));
    expect(lastRecordsUrl(mocks.calls).searchParams.get("to")).toBe("2026-10-09T00:00:00+09:00"); // 終了日2026-10-08 → 翌日0:00 JST
  });

  it("任意期間で開始日>終了日の場合はエラーを表示し、取得しない", async () => {
    const mocks = standardMocks([recordsHandler()]);
    renderApp("/history");
    await userEvent.setup().click(await screen.findByRole("button", { name: "任意期間" }));
    const before = mocks.calls.filter((c) => c.url.startsWith("/api/records?")).length;
    fireEvent.change(screen.getByLabelText("開始日"), { target: { value: "2026-10-09" } });
    fireEvent.change(screen.getByLabelText("終了日"), { target: { value: "2026-10-01" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("開始日は終了日以前");
    expect(mocks.calls.filter((c) => c.url.startsWith("/api/records?")).length).toBe(before);
  });

  it("Monitorはプルダウンで選ぶと即時に履歴を再取得する(適用ボタンなし)。「すべてのモニター」で解除", async () => {
    const mocks = standardMocks([recordsHandler()]);
    const user = userEvent.setup();
    renderApp("/history");
    const select = await screen.findByRole("combobox", { name: "モニター" });
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(4)); // すべて + 3台
    expect(screen.queryByRole("button", { name: "適用" })).not.toBeInTheDocument();
    await user.selectOptions(select, "4");
    await waitFor(() => expect(lastRecordsUrl(mocks.calls).searchParams.getAll("monitor_id")).toEqual(["4"]));
    await user.selectOptions(select, "");
    await waitFor(() => expect(lastRecordsUrl(mocks.calls).searchParams.getAll("monitor_id")).toEqual([]));
  });

  it("記録が無い場合は空の案内を表示する", async () => {
    standardMocks([recordsHandler([], 0)]);
    renderApp("/history");
    expect(await screen.findByText("この条件に該当する計測記録はありません。")).toBeInTheDocument();
  });

  it("履歴の取得に失敗したらエラーを表示する", async () => {
    standardMocks([route("GET", "/api/records", () => json({ detail: "boom" }, 500))]);
    renderApp("/history");
    expect(await screen.findByText(/計測履歴を取得できません（boom）/)).toBeInTheDocument();
  });
});

describe("carried_forward の表示", () => {
  it("履歴で「前回確定値を保持」バッジ・行の強調・棄却されたRawを表示する(正式値は value)", async () => {
    standardMocks([recordsHandler()]);
    renderApp("/history");
    await screen.findByText("215858");
    const row = document.querySelector('tr[data-record-id="3"]') as HTMLElement;
    expect(row).toHaveClass("row-carried");
    expect(within(row).getByText("前回確定値を保持")).toBeInTheDocument();
    expect(within(row).getByText("215858")).toBeInTheDocument();
    expect(within(row).getByText("Raw 0215850")).toBeInTheDocument();
    expect(within(row).getByText("エネセン内ガスメータ用１")).toBeInTheDocument();
    expect(document.querySelector('tr[data-record-id="2"]')).not.toHaveClass("row-carried");
  });
});

describe("記録画像Drawer", () => {
  it("詳細で右Drawerを開き、元値を確認でき、元画像/推論画像を切り替える(保存済み画像のAPIのみ)", async () => {
    standardMocks([recordsHandler()]);
    const user = userEvent.setup();
    renderApp("/history");
    await screen.findByText("215858");
    const row = document.querySelector('tr[data-record-id="3"]') as HTMLElement;
    await user.click(within(row).getByRole("button", { name: /詳細/ }));
    const drawer = await screen.findByRole("dialog", { name: "計測記録の詳細" });
    expect(within(drawer).getByRole("img", { name: "記録時の元画像" })).toHaveAttribute("src", "/api/records/3/image/original");
    expect(within(drawer).getByText("decrease_detected")).toBeInTheDocument(); // validation_status
    expect(within(drawer).getByText("前回確定値を保持(carried_forward)")).toBeInTheDocument(); // value_source
    expect(within(drawer).getByText("0215850")).toBeInTheDocument(); // Raw
    expect(within(drawer).getByText("正常(normal)")).toBeInTheDocument(); // display_status
    expect(within(drawer).getByText("なし")).toBeInTheDocument(); // baseline_conflict
    expect(within(drawer).getByText("cpp_onnx")).toBeInTheDocument();
    expect(within(drawer).getByText("digital_production_v1.onnx")).toBeInTheDocument();
    expect(within(drawer).getByRole("note")).toHaveTextContent("採用せず");
    await user.click(within(drawer).getByRole("tab", { name: "推論結果画像" }));
    expect(within(drawer).getByRole("img", { name: "記録時の推論結果画像" })).toHaveAttribute("src", "/api/records/3/image/overlay");
    await user.click(within(drawer).getByRole("button", { name: "閉じる" }));
    expect(screen.queryByRole("dialog", { name: "計測記録の詳細" })).not.toBeInTheDocument();
  });

  it("画像なしの記録(not_saved)は壊れた画像ではなく「記録画像なし」を表示する", async () => {
    standardMocks([recordsHandler()]);
    const user = userEvent.setup();
    renderApp("/history");
    await screen.findByText("215858");
    const row = document.querySelector('tr[data-record-id="1"]') as HTMLElement;
    expect(within(row).getByText("画像なし")).toBeInTheDocument(); // 画像列は画像リンクを出さない
    await user.click(within(row).getByRole("button", { name: /詳細/ }));
    const drawer = await screen.findByRole("dialog", { name: "計測記録の詳細" });
    expect(within(drawer).getByText(/記録画像なし/)).toBeInTheDocument();
    expect(within(drawer).queryByRole("img")).not.toBeInTheDocument();
    await user.click(within(drawer).getByRole("tab", { name: "推論結果画像" }));
    expect(within(drawer).getByText(/記録画像なし/)).toBeInTheDocument();
  });

  it.each([
    ["failed", "画像の保存に失敗しました：disk full"],
    ["dropped", "画像を保存しませんでした"],
    ["disabled", "画像保存が無効でした"],
  ] as const)("image_status=%s の説明を表示する", async (status, text) => {
    const item = record({ id: 7, image_status: status, original_image_path: null, overlay_image_path: null, image_error: status === "failed" ? "disk full" : null });
    standardMocks([recordsHandler([item])]);
    const user = userEvent.setup();
    renderApp("/history");
    const row = await waitFor(() => { const r = document.querySelector('tr[data-record-id="7"]') as HTMLElement; expect(r).toBeTruthy(); return r; });
    await user.click(within(row).getByRole("button", { name: /詳細/ }));
    expect(await screen.findByText(new RegExp(text))).toBeInTheDocument();
  });

  it("保存済み画像が読み込めない場合(ファイル欠損)は説明を表示する", async () => {
    standardMocks([recordsHandler([normal])]);
    const user = userEvent.setup();
    renderApp("/history");
    const row = await waitFor(() => { const r = document.querySelector('tr[data-record-id="2"]') as HTMLElement; expect(r).toBeTruthy(); return r; });
    await user.click(within(row).getByRole("button", { name: /詳細/ }));
    fireEvent.error(await screen.findByRole("img", { name: "記録時の元画像" }));
    expect(await screen.findByText(/保存した画像を読み込めません/)).toBeInTheDocument();
  });
});

describe("Excel出力", () => {
  const xlsx = () => new Response("PK", { status: 200, headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "Content-Disposition": 'attachment; filename="Argus_MeterRecords_20261009.xlsx"', "X-Argus-Total-Rows": "45" } });
  let downloaded: string[] = [];
  beforeEach(() => {
    downloaded = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { downloaded.push(this.download); });
  });
  const open = async (user: ReturnType<typeof userEvent.setup>) => { renderApp("/history"); await user.click(await screen.findByRole("button", { name: "Excel出力" })); return screen.getByRole("dialog", { name: "Excel出力" }); };
  const exportCalls = (calls: Call[]) => calls.filter((c) => c.method === "POST" && c.url === "/api/records/export/excel");

  it("ダウンロード: 現在のMonitor/期間フィルタでPOSTし、ファイルを保存する", async () => {
    const mocks = standardMocks([recordsHandler(), route("POST", "/api/records/export/excel", xlsx)]);
    const user = userEvent.setup();
    renderApp("/history");
    const select = await screen.findByRole("combobox", { name: "モニター" });
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(4));
    await user.selectOptions(select, "2");
    await user.click(screen.getByRole("button", { name: "過去7日" }));
    await user.click(screen.getByRole("button", { name: "Excel出力" }));
    const dialog = screen.getByRole("dialog", { name: "Excel出力" });
    await user.click(within(dialog).getByRole("button", { name: "ダウンロード" }));
    expect(await within(dialog).findByText(/ダウンロードしました：Argus_MeterRecords_20261009.xlsx（45行）/)).toBeInTheDocument();
    expect(exportCalls(mocks.calls)[0].body).toEqual({ monitor_ids: [2], from: "2026-10-03T00:00:00+09:00", to: "2026-10-10T00:00:00+09:00", save_to_server: false });
    expect(downloaded).toEqual(["Argus_MeterRecords_20261009.xlsx"]);
  });

  it("サーバー保存: save_to_server=true で送り、ファイル名・保存先・行数・シート数を表示する", async () => {
    const saved = { saved: true, path: "C:\\Argus\\data\\exports\\Argus_MeterRecords_20261009.xlsx", filename: "Argus_MeterRecords_20261009.xlsx", folder: "C:\\Argus\\data\\exports", size_bytes: 15000, total_rows: 45, sheets: [{ monitor_id: 2, sheet_name: "A", rows: 15 }, { monitor_id: 3, sheet_name: "B", rows: 15 }, { monitor_id: 4, sheet_name: "C", rows: 15 }], image_links: 84, image_links_skipped: false };
    const mocks = standardMocks([recordsHandler(), route("POST", "/api/records/export/excel", () => json(saved))]);
    const user = userEvent.setup();
    const dialog = await open(user);
    await user.click(within(dialog).getByRole("radio", { name: /サーバー保存/ }));
    await user.click(within(dialog).getByRole("button", { name: "サーバーへ保存" }));
    expect(await within(dialog).findByText("サーバーへ保存しました")).toBeInTheDocument();
    expect(within(dialog).getByText("Argus_MeterRecords_20261009.xlsx")).toBeInTheDocument();
    expect(within(dialog).getByText("C:\\Argus\\data\\exports\\Argus_MeterRecords_20261009.xlsx")).toBeInTheDocument();
    expect(within(dialog).getByText("45行")).toBeInTheDocument();
    expect(within(dialog).getByText(/^3（/)).toBeInTheDocument();
    expect((exportCalls(mocks.calls)[0].body as { save_to_server: boolean }).save_to_server).toBe(true);
    expect(downloaded).toEqual([]);
  });

  it.each([
    [422, "期間が不正です", "出力条件が正しくありません"],
    [404, { code: "NO_RECORDS", message: "x" }, "記録がありません"],
    [409, { code: "EXPORT_IN_PROGRESS", message: "x" }, "実行中です"],
    [503, { code: "EXPORT_SAVE_FAILED", message: "denied" }, "保存先へ書き込めませんでした"],
    [503, { code: "EXPORT_SAVE_TIMEOUT", message: "timeout" }, "応答しません"],
  ] as const)("エラー %s を運用者向けメッセージで表示する", async (status, detail, text) => {
    standardMocks([recordsHandler(), route("POST", "/api/records/export/excel", () => json({ detail }, status))]);
    const user = userEvent.setup();
    const dialog = await open(user);
    await user.click(within(dialog).getByRole("radio", { name: /サーバー保存/ }));
    await user.click(within(dialog).getByRole("button", { name: "サーバーへ保存" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(text);
  });

  it("ダウンロード時のエラーも表示し、ファイルは保存しない", async () => {
    standardMocks([recordsHandler(), route("POST", "/api/records/export/excel", () => json({ detail: { code: "NO_RECORDS", message: "x" } }, 404))]);
    const user = userEvent.setup();
    const dialog = await open(user);
    await user.click(within(dialog).getByRole("button", { name: "ダウンロード" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("記録がありません");
    expect(downloaded).toEqual([]);
  });

  it("任意期間が不正な間は出力できない", async () => {
    standardMocks([recordsHandler()]);
    const user = userEvent.setup();
    renderApp("/history");
    await user.click(await screen.findByRole("button", { name: "任意期間" }));
    fireEvent.change(screen.getByLabelText("開始日"), { target: { value: "2026-10-09" } });
    fireEvent.change(screen.getByLabelText("終了日"), { target: { value: "2026-10-01" } });
    await user.click(screen.getByRole("button", { name: "Excel出力" }));
    expect(within(screen.getByRole("dialog", { name: "Excel出力" })).getByRole("button", { name: "ダウンロード" })).toBeDisabled();
  });
});
