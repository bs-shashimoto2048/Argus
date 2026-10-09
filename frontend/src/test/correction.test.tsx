import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { get, json, record, renderApp, route, standardMocks } from "./helpers";
import type { Call } from "./helpers";
import type { BaselineStatus, CorrectionResult, ReadingRecord, RecordCorrection } from "../types";

beforeEach(() => { localStorage.clear(); vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-10-09T05:30:00Z")); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const carried = record({ id: 7, monitor_id: 2, hour_bucket: "2026-10-09T08:00:00+09:00", recorded_at: "2026-10-08T23:00:15", value: "215858", numeric_value: "215858", raw_value: "0215850", raw_confidence: 0.881, confidence: 0.93,
  value_source: "carried_forward", validation_status: "decrease_detected", previous_value: "215836", usage: "22", correctable: true, correctable_reason: "carried_forward" });
const conflict = record({ id: 6, monitor_id: 2, hour_bucket: "2026-10-09T07:00:00+09:00", recorded_at: "2026-10-08T22:00:15", value: "215836", raw_value: "0215830", baseline_conflict: true, validation_status: "decrease_detected",
  value_source: "carried_forward", correctable: true, correctable_reason: "baseline_conflict" });
const confirmed = record({ id: 8, monitor_id: 3, monitor_name: "Digital B", hour_bucket: "2026-10-09T08:00:00+09:00", recorded_at: "2026-10-08T23:00:15", value: "100", raw_value: "0100", correctable: false });
const next = record({ id: 9, monitor_id: 2, hour_bucket: "2026-10-09T09:00:00+09:00", recorded_at: "2026-10-09T00:00:15", value: "215865", previous_value: "215858", usage: "7" });
const legacy = record({ id: 5, monitor_id: 2, hour_bucket: "2026-10-09T06:00:00+09:00", recorded_at: "2026-10-08T21:00:15", inference_at: null, raw_confidence: null, snapshot_consistent: false });

const baselineStatus: BaselineStatus = {
  monitor_id: 2, baseline: { value: "215858", numeric_value: "215858", confirmed_at: "2026-10-08T23:00:36Z", age_seconds: 100, source: "confirmed", state: "active", epoch: 3, decimal_position: null, expected_digits: null },
  conflict: { status: "decrease_detected", candidate: "215850", count: 5, started_at: "x", last_at: "x", duration_seconds: 400, active: true, alert: true }, candidate: { value: "215850", agreement_count: 5 },
  latest_raw: "0215850", current_confirmed: "215858", reading: { enabled: true, monotonic: true, allow_rollover: false, max_rate_per_minute: null, decimal_position: null, expected_digits: null }, alert_seconds: 300, runtime_active: true,
};

function setup(items: ReadingRecord[], corrections: RecordCorrection[] = [], postHandler?: (c: Call) => Response) {
  const state = { items: [...items], corrections: [...corrections] };
  const correctedResult = (c: Call): CorrectionResult => {
    const body = c.body as { value: string; reason: string; operator: string; rebase_current_baseline: boolean };
    const target = state.items.find((r) => r.id === 7)!;
    const updated = { ...target, value: body.value, numeric_value: body.value, usage: "14", is_corrected: true, correction_count: 1, original_value: target.value, corrected_by: body.operator, corrected_at: "2026-10-09T05:31:00" };
    const row: RecordCorrection = { id: 1, record_id: 7, monitor_id: 2, corrected_at: "2026-10-09T05:31:00", operator: body.operator, reason: body.reason, old_value: target.value, new_value: body.value, old_numeric_value: target.value, new_numeric_value: body.value,
      old_usage: "22", new_usage: "14", raw_value: target.raw_value, raw_confidence: target.raw_confidence, validation_status: target.validation_status, value_source: target.value_source, baseline_value: "215858", baseline_conflict: false,
      original_image_path: null, overlay_image_path: null, client_host: "127.0.0.1", context: { rebase: { requested: body.rebase_current_baseline, performed: body.rebase_current_baseline } } };
    state.corrections = [row];
    state.items = state.items.map((r) => (r.id === 7 ? updated : r.id === 9 ? { ...r, previous_value: body.value, usage: "15" } : r));
    return { record_id: 7, correction: row, next_record: { record_id: 9, hour_bucket: next.hour_bucket, value: "215865", value_source: "confirmed", old_usage: "7", new_usage: "15" }, rebase: { requested: body.rebase_current_baseline, performed: body.rebase_current_baseline }, record: updated };
  };
  const mocks = standardMocks([
    get("/api/records", () => ({ items: state.items, total: state.items.length, limit: 500, offset: 0 })),
    get("/api/records/7/corrections", () => ({ record_id: 7, corrections: state.corrections })),
    get("/api/monitors/2/reading/baseline", baselineStatus),
    route("POST", "/api/records/7/correct", (c) => postHandler ? postHandler(c) : json(correctedResult(c))),
  ]);
  return { ...mocks, state };
}
const open = async (user: ReturnType<typeof userEvent.setup>, id: number) => {
  const row = await waitFor(() => { const r = document.querySelector(`tr[data-record-id="${id}"]`) as HTMLElement; expect(r).toBeTruthy(); return r; });
  await user.click(within(row).getByRole("button", { name: /詳細/ }));
  return screen.findByRole("dialog", { name: "計測記録の詳細" });
};
const postCalls = (calls: Call[]) => calls.filter((c) => c.method === "POST" && c.url === "/api/records/7/correct");

describe("計測記録の詳細: 正式値の信頼度と最新推論値の信頼度を分けて表示", () => {
  it("正式値の信頼度(confidence)と最新推論値の信頼度(raw_confidence)を別の項目で表示し、推論時刻も出す", async () => {
    setup([carried, confirmed]);
    const user = userEvent.setup();
    renderApp("/history");
    const drawer = await open(user, 7);
    expect(within(drawer).getByText("正式値の信頼度").nextElementSibling).toHaveTextContent("93.0%");
    expect(within(drawer).getByText("最新推論値の信頼度").nextElementSibling).toHaveTextContent("88.1%");
    expect(within(drawer).getByText("最新推論値（Raw）").nextElementSibling).toHaveTextContent("0215850");
    expect(within(drawer).getByText("推論時刻")).toBeInTheDocument();
    expect(within(drawer).getByText("記録日時")).toBeInTheDocument();
    expect(within(drawer).queryByText("信頼度")).not.toBeInTheDocument(); // どちらの信頼度か曖昧な項目名は使わない
  });

  it("同一tick保証が無い既存の記録(inference_atなし)は、そのことを明示する(推測で補わない)", async () => {
    setup([legacy]);
    const user = userEvent.setup();
    renderApp("/history");
    const drawer = await open(user, 5);
    expect(within(drawer).getByText("推論時刻").nextElementSibling).toHaveTextContent("同一tick保証なし");
    expect(within(drawer).getByText("最新推論値の信頼度").nextElementSibling).toHaveTextContent("--");
  });
});

describe("読取値を修正: 対象の記録だけにボタンを出す", () => {
  it("carried_forward / 基準値競合の記録には「読取値を修正」を出し、通常のconfirmedな記録には出さない", async () => {
    setup([carried, conflict, confirmed]);
    const user = userEvent.setup();
    renderApp("/history");
    let drawer = await open(user, 7);
    expect(within(drawer).getByRole("button", { name: "読取値を修正" })).toBeInTheDocument(); // carried_forward
    await user.click(within(drawer).getByRole("button", { name: "閉じる" }));
    drawer = await open(user, 6);
    expect(within(drawer).getByRole("button", { name: "読取値を修正" })).toBeInTheDocument(); // baseline conflict
    await user.click(within(drawer).getByRole("button", { name: "閉じる" }));
    drawer = await open(user, 8);
    expect(within(drawer).queryByRole("button", { name: "読取値を修正" })).not.toBeInTheDocument(); // 通常のconfirmed
  });
});

describe("読取値の修正ダイアログ", () => {
  it("記録日時・正式値・最新Raw・Rawの信頼度・overlay画像・読取判定・値の由来・基準値・競合候補を確認できる", async () => {
    setup([carried]);
    const user = userEvent.setup();
    renderApp("/history");
    const drawer = await open(user, 7);
    await user.click(within(drawer).getByRole("button", { name: "読取値を修正" }));
    const dialog = await screen.findByRole("dialog", { name: "読取値の修正" });
    expect(within(dialog).getByText("記録日時")).toBeInTheDocument();
    expect(within(dialog).getByText("現在の正式値").nextElementSibling).toHaveTextContent("215858");
    expect(within(dialog).getByText("最新推論値（Raw）").nextElementSibling).toHaveTextContent("0215850");
    expect(within(dialog).getByText("最新推論値の信頼度").nextElementSibling).toHaveTextContent("88.1%");
    expect(within(dialog).getByText("読取判定").nextElementSibling).toHaveTextContent("decrease_detected");
    expect(within(dialog).getByText("値の由来").nextElementSibling).toHaveTextContent("前回確定値を保持");
    expect(within(dialog).getByRole("img", { name: "記録時の推論結果画像" })).toHaveAttribute("src", "/api/records/7/image/overlay"); // 保存したoverlay(現在のlive映像ではない)
    await waitFor(() => expect(within(dialog).getByText("現在の読取基準値").nextElementSibling).toHaveTextContent("215858"));
    expect(within(dialog).getByText("基準値競合").nextElementSibling).toHaveTextContent("競合する読取 215850");
  });

  it("修正理由・操作者・修正後の値がすべて入るまで実行できない。「最新推論値を入力」は入力欄を埋めるだけで自動確定しない", async () => {
    const m = setup([carried]);
    const user = userEvent.setup();
    renderApp("/history");
    await user.click(within(await open(user, 7)).getByRole("button", { name: "読取値を修正" }));
    const dialog = await screen.findByRole("dialog", { name: "読取値の修正" });
    const submit = within(dialog).getByRole("button", { name: "この内容で修正する" });
    expect(submit).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "最新推論値 215850 を入力" })); // Raw 0215850 → 先頭0を除いた値
    expect(within(dialog).getByLabelText(/修正後の値/)).toHaveValue("215850");
    expect(submit).toBeDisabled(); // 理由・操作者が空
    await user.type(within(dialog).getByLabelText(/修正理由/), "画像で確認");
    expect(submit).toBeDisabled(); // 操作者が空
    await user.type(within(dialog).getByLabelText(/操作者/), "tester");
    expect(submit).toBeEnabled();
    expect(postCalls(m.calls)).toHaveLength(0); // ここまでは何も送信していない(自動確定しない)
  });

  it("修正を実行する: POSTし、記録が「修正済み」になり、元の正式値・修正履歴・再計算された使用量が表示される(Raw・画像は変わらない)", async () => {
    const m = setup([carried, next]);
    const user = userEvent.setup();
    renderApp("/history");
    await user.click(within(await open(user, 7)).getByRole("button", { name: "読取値を修正" }));
    const dialog = await screen.findByRole("dialog", { name: "読取値の修正" });
    await user.type(within(dialog).getByLabelText(/修正後の値/), "215850");
    await user.type(within(dialog).getByLabelText(/修正理由/), "画像で0215850を確認");
    await user.type(within(dialog).getByLabelText(/操作者/), "山田");
    await user.click(within(dialog).getByRole("button", { name: "この内容で修正する" }));
    await waitFor(() => expect(postCalls(m.calls)).toHaveLength(1));
    expect(postCalls(m.calls)[0].body).toEqual({ value: "215850", reason: "画像で0215850を確認", operator: "山田", rebase_current_baseline: false }); // 基準値の再設定は既定でOFF
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "読取値の修正" })).not.toBeInTheDocument());
    const drawer = screen.getByRole("dialog", { name: "計測記録の詳細" });
    expect(within(drawer).getByText(/^修正済み/)).toBeInTheDocument();
    expect(within(drawer).getByText("元の正式値").nextElementSibling).toHaveTextContent("215858");
    expect(within(drawer).getByText("正式確定値", { selector: "dt" }).nextElementSibling).toHaveTextContent("215850");
    expect(within(drawer).getByText("使用量").nextElementSibling).toHaveTextContent("14");
    expect(within(drawer).getByText("値の由来").nextElementSibling).toHaveTextContent("前回確定値を保持(carried_forward) → 手動修正済み");
    expect(within(drawer).getByText("最新推論値（Raw）").nextElementSibling).toHaveTextContent("0215850"); // 元証跡は変わらない
    expect(within(drawer).getByText("読取判定").nextElementSibling).toHaveTextContent("decrease_detected");
    expect(within(drawer).getByText("最新推論値の信頼度").nextElementSibling).toHaveTextContent("88.1%");
    expect(within(drawer).getByRole("img", { name: "記録時の元画像" })).toHaveAttribute("src", "/api/records/7/image/original");
    const history = await within(drawer).findByRole("region", { name: "修正履歴" });
    expect(within(history).getByText("215858 → 215850")).toBeInTheDocument();
    expect(within(history).getByText(/山田 \/ 画像で0215850を確認/)).toBeInTheDocument();
    expect(within(history).getByText(/使用量 22 → 14/)).toBeInTheDocument();
    // 一覧(表): 修正済みbadge・修正後の値、次の1時間の記録のusageも再計算後の値へ
    const row = document.querySelector('tr[data-record-id="7"]') as HTMLElement;
    expect(within(row).getByText("修正済み")).toBeInTheDocument();
    expect(row.querySelector(".c-value")).toHaveTextContent("215850");
    expect((document.querySelector('tr[data-record-id="9"] .c-usage') as HTMLElement).textContent).toBe("15");
    expect((document.querySelector('tr[data-record-id="9"] .c-prev') as HTMLElement).textContent).toBe("215850");
    expect(localStorage.getItem("argus.baseline.operator")).toBe("山田"); // 操作者名を覚えておく
  });

  it("「現在の読取基準値もこの値へ再設定する」は、基準値競合の記録でだけ選べ、既定OFF。ONにしたときだけrebase_current_baseline=true", async () => {
    const m = setup([carried]);
    const user = userEvent.setup();
    renderApp("/history");
    await user.click(within(await open(user, 7)).getByRole("button", { name: "読取値を修正" }));
    const dialog = await screen.findByRole("dialog", { name: "読取値の修正" });
    const checkbox = await within(dialog).findByRole("checkbox", { name: /現在の読取基準値もこの値へ再設定する/ }); // 現在も継続中の競合があるときに表示
    expect(checkbox).not.toBeChecked();
    await user.type(within(dialog).getByLabelText(/修正後の値/), "215850");
    await user.type(within(dialog).getByLabelText(/修正理由/), "確認");
    await user.type(within(dialog).getByLabelText(/操作者/), "tester");
    await user.click(checkbox);
    await user.click(within(dialog).getByRole("button", { name: "この内容で修正する" }));
    await waitFor(() => expect(postCalls(m.calls)).toHaveLength(1));
    expect((postCalls(m.calls)[0].body as { rebase_current_baseline: boolean }).rebase_current_baseline).toBe(true);
  });

  it("基準値の競合が無い記録(carried_forwardのみ・競合なし)では、基準値の再設定の選択肢を出さない", async () => {
    standardMocks([get("/api/records", { items: [carried], total: 1, limit: 500, offset: 0 }), get("/api/monitors/2/reading/baseline", { ...baselineStatus, conflict: null })]);
    const user = userEvent.setup();
    renderApp("/history");
    await user.click(within(await open(user, 7)).getByRole("button", { name: "読取値を修正" }));
    const dialog = await screen.findByRole("dialog", { name: "読取値の修正" });
    await waitFor(() => expect(within(dialog).getByText("現在の読取基準値").nextElementSibling).toHaveTextContent("215858"));
    expect(within(dialog).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("APIのエラー(値の不正など)は日本語で表示し、記録は変わらない", async () => {
    setup([carried], [], () => json({ detail: { code: "INVALID_VALUE", message: "桁数が期待桁数(7桁)を超えています" } }, 422));
    const user = userEvent.setup();
    renderApp("/history");
    await user.click(within(await open(user, 7)).getByRole("button", { name: "読取値を修正" }));
    const dialog = await screen.findByRole("dialog", { name: "読取値の修正" });
    await user.type(within(dialog).getByLabelText(/修正後の値/), "21585000");
    await user.type(within(dialog).getByLabelText(/修正理由/), "確認");
    await user.type(within(dialog).getByLabelText(/操作者/), "tester");
    await user.click(within(dialog).getByRole("button", { name: "この内容で修正する" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("桁数が期待桁数(7桁)を超えています");
    expect(screen.getByRole("dialog", { name: "読取値の修正" })).toBeInTheDocument(); // ダイアログは開いたまま(入力を直せる)
    const row = document.querySelector('tr[data-record-id="7"]') as HTMLElement;
    expect(within(row).queryByText("修正済み")).not.toBeInTheDocument();
  });

  it("キャンセルしても何も送信しない", async () => {
    const m = setup([carried]);
    const user = userEvent.setup();
    renderApp("/history");
    await user.click(within(await open(user, 7)).getByRole("button", { name: "読取値を修正" }));
    await user.click(within(await screen.findByRole("dialog", { name: "読取値の修正" })).getByRole("button", { name: "キャンセル" }));
    expect(screen.queryByRole("dialog", { name: "読取値の修正" })).not.toBeInTheDocument();
    expect(postCalls(m.calls)).toHaveLength(0);
  });
});

describe("修正済みの記録の表示", () => {
  it("修正済みのbadgeを一覧に表示し、Drawerで修正履歴(複数回分)を新しい順に確認できる", async () => {
    const history: RecordCorrection[] = [
      { id: 2, record_id: 7, monitor_id: 2, corrected_at: "2026-10-09T05:40:00", operator: "b", reason: "2回目", old_value: "215850", new_value: "215851", old_numeric_value: "215850", new_numeric_value: "215851", old_usage: "14", new_usage: "15",
        raw_value: "0215850", raw_confidence: 0.881, validation_status: "decrease_detected", value_source: "carried_forward", baseline_value: null, baseline_conflict: false, original_image_path: null, overlay_image_path: null, client_host: "h", context: null },
      { id: 1, record_id: 7, monitor_id: 2, corrected_at: "2026-10-09T05:31:00", operator: "a", reason: "1回目", old_value: "215858", new_value: "215850", old_numeric_value: "215858", new_numeric_value: "215850", old_usage: "22", new_usage: "14",
        raw_value: "0215850", raw_confidence: 0.881, validation_status: "decrease_detected", value_source: "carried_forward", baseline_value: null, baseline_conflict: false, original_image_path: null, overlay_image_path: null, client_host: "h", context: { rebase: { performed: true } } },
    ];
    const corrected = { ...carried, value: "215851", is_corrected: true, correction_count: 2, original_value: "215858", corrected_by: "b", corrected_at: "2026-10-09T05:40:00" };
    setup([corrected], history);
    const user = userEvent.setup();
    renderApp("/history");
    const drawer = await open(user, 7);
    expect(within(drawer).getByText("修正済み（2回）")).toBeInTheDocument();
    const region = await within(drawer).findByRole("region", { name: "修正履歴" });
    const items = within(region).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("215850 → 215851");
    expect(items[1]).toHaveTextContent("215858 → 215850");
    expect(items[1]).toHaveTextContent("読取基準値も再設定");
    expect(within(drawer).getByText("元の正式値").nextElementSibling).toHaveTextContent("215858"); // 最初の修正前の正式値
    expect(within(drawer).getByRole("button", { name: "読取値を修正" })).toBeInTheDocument(); // 再度の修正もできる(履歴は全件残る)
  });
});
