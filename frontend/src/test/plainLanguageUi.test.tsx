import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MonitorCard } from "../components/MonitorCard";
import { CorrectionDialog } from "../components/CorrectionDialog";
import { ReadingSettingsPanel } from "../components/ReadingSettingsPanel";
import { RecordDrawer } from "../components/RecordDrawer";
import { RecordsTable } from "../components/RecordsTable";
import { chartEventLabels } from "../utils/trend";
import type { BaselineStatus, ReadingSettings } from "../types";
import { get, json, mockFetch, monitor, record, route } from "./helpers";
import type { Call } from "./helpers";

const reading: ReadingSettings = { enabled: true, mode: "majority", window_size: 5, required_matches: 3, min_confidence: 0.6, expected_digits: 7, decimal_position: 1, monotonic: true, max_rate_per_minute: null, max_consecutive_failures: 5, allow_rollover: false, rollover_max: null };

const status = (value: string | null = "215998", over: Partial<BaselineStatus> = {}): BaselineStatus => ({
  monitor_id: 3,
  baseline: value === null ? { value: null, numeric_value: null, confirmed_at: null, age_seconds: null, source: "operator_reset", state: "pending_reset", epoch: 7, decimal_position: 1, expected_digits: 7 }
    : { value, numeric_value: value, confirmed_at: "2026-10-13T04:00:12Z", age_seconds: 30, source: "confirmed", state: "active", epoch: 6, decimal_position: 1, expected_digits: 7 },
  conflict: null, candidate: { value: "215993", agreement_count: 5 }, latest_raw: "0215993", current_confirmed: "215998",
  reading: { enabled: true, monotonic: true, allow_rollover: false, max_rate_per_minute: null, decimal_position: 1, expected_digits: 7 }, alert_seconds: 300, runtime_active: true, ...over,
});

function Harness({ initial, onChanged }: { initial: BaselineStatus; onChanged?: (s: BaselineStatus) => void }) {
  const [baseline, setBaseline] = useState<BaselineStatus | null>(initial);
  return <ReadingSettingsPanel value={reading} onChange={() => {}} open onToggleOpen={() => {}} baseline={baseline} monitorId={3} onBaselineChanged={(next) => { setBaseline(next); onChanged?.(next); }} />;
}
const card = () => screen.getByLabelText("現在の判定状態");
const fillDialog = (dialog: HTMLElement, fields: Record<string, string>) => {
  for (const [label, value] of Object.entries(fields)) fireEvent.change(within(dialog).getByLabelText(new RegExp(label)), { target: { value } });
};

describe("設定画面から読取基準値を変更・未設定に戻す", () => {
  it("「積算値チェック」に [基準値を変更] [基準値を未設定に戻す] があり、「診断タブから操作します」の案内は無い", () => {
    mockFetch();
    render(<Harness initial={status()} />);
    expect(screen.getByRole("button", { name: "基準値を変更" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "基準値を未設定に戻す" })).toBeEnabled();
    expect(screen.queryByText(/診断タブから操作します|この画面では編集できません/)).toBeNull();
    expect(within(card()).getByText("215998")).toBeInTheDocument();
  });

  it("読取安定化が無効のMonitor・基準値を取得できない時は、ボタンを押せない", () => {
    mockFetch();
    const { unmount } = render(<Harness initial={status("215998", { reading: { enabled: false, monotonic: true, allow_rollover: false, max_rate_per_minute: null, decimal_position: 1, expected_digits: 7 } })} />);
    expect(screen.getByRole("button", { name: "基準値を変更" })).toBeDisabled();
    unmount();
    render(<ReadingSettingsPanel value={reading} onChange={() => {}} open onToggleOpen={() => {}} baseline={null} monitorId={3} />);
    expect(screen.getByRole("button", { name: "基準値を未設定に戻す" })).toBeDisabled();
  });

  it("変更ダイアログ: 現在の読取基準値・最新のAI読取値・差を表示し、新しい基準値・理由・操作者がそろうまで実行できない", async () => {
    const mocks = mockFetch([route("POST", "/api/monitors/3/reading/baseline/rebase", () => json(status("215995")))]);
    const user = userEvent.setup();
    render(<Harness initial={status()} />);
    await user.click(screen.getByRole("button", { name: "基準値を変更" }));
    const dialog = await screen.findByRole("dialog", { name: "読取基準値を指定値へ変更" });
    expect(within(dialog).getByText("現在の読取基準値").nextElementSibling).toHaveTextContent("215998");
    expect(within(dialog).getByText("最新のAI読取値").nextElementSibling).toHaveTextContent("215993");
    expect(within(dialog).getByText("差").nextElementSibling).toHaveTextContent("--");
    expect(within(dialog).getByText(/現在の読取基準値を、運用者が確認した値へ変更します/)).toBeInTheDocument();
    const submit = within(dialog).getByRole("button", { name: "この値へ変更" });
    expect(submit).toBeDisabled();
    fillDialog(dialog, { "新しい読取基準値": "215995" });
    expect(within(dialog).getByText("差").nextElementSibling).toHaveTextContent("+2"); // 最新のAI読取値との差
    expect(submit).toBeDisabled(); // 理由・操作者が必須
    fillDialog(dialog, { "変更理由": "実メーターを確認", "操作者": "tester" });
    expect(submit).toBeEnabled();
    await user.click(submit);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "読取基準値を指定値へ変更" })).toBeNull());
    expect(mocks.calls.find((c: Call) => c.method === "POST")!.body).toEqual({ value: "215995", reason: "実メーターを確認", operator: "tester" }); // forceなし
    expect(within(card()).getByText("215995")).toBeInTheDocument(); // 成功後、画面がすぐ新しい読取基準値になる
  });

  it("最新のAI読取値から大きく離れた値は、確認画面(戻る / 確認して変更)を経てforceつきで変更する", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const mocks = mockFetch([route("POST", "/api/monitors/3/reading/baseline/rebase", (c: Call) => ((c.body as { force?: boolean }).force
      ? json(status("21599"))
      : json({ detail: { code: "FORCE_REQUIRED", message: "FORCE_REQUIRED", candidate: "215993", requested: "21599", tolerance: "1" } }, 409)))]);
    const user = userEvent.setup();
    render(<Harness initial={status()} />);
    await user.click(screen.getByRole("button", { name: "基準値を変更" }));
    const dialog = await screen.findByRole("dialog", { name: "読取基準値を指定値へ変更" });
    fillDialog(dialog, { "新しい読取基準値": "21599", "変更理由": "確認", "操作者": "tester" });
    await user.click(within(dialog).getByRole("button", { name: "この値へ変更" }));
    expect(await within(dialog).findByText("入力した基準値は、最新のAI読取値から大きく離れています。桁数・小数点位置・実メーターの表示を確認してください。")).toBeInTheDocument();
    const far = dialog.querySelector(".far-confirm") as HTMLElement;
    expect(within(far).getByText("入力値").nextElementSibling).toHaveTextContent("21599");
    expect(within(far).getByText("最新のAI読取値").nextElementSibling).toHaveTextContent("215993");
    expect(within(far).getByText("差").nextElementSibling).toHaveTextContent("-194394");
    expect(dialog.textContent).not.toMatch(/FORCE_REQUIRED|ForceRequired/); // 内部名は出さない
    expect(mocks.calls.filter((c: Call) => c.method === "POST")).toHaveLength(1);
    await user.click(within(dialog).getByRole("button", { name: "戻る" })); // 入力へ戻れる
    expect(within(dialog).getByRole("button", { name: "この値へ変更" })).toBeEnabled();
    await user.click(within(dialog).getByRole("button", { name: "この値へ変更" }));
    await user.click(await within(dialog).findByRole("button", { name: "確認して変更" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "読取基準値を指定値へ変更" })).toBeNull());
    const posts = mocks.calls.filter((c: Call) => c.method === "POST");
    expect(posts).toHaveLength(3);
    expect(posts[2].body).toMatchObject({ value: "21599", force: true });
    warn.mockRestore();
  });

  it("未設定に戻す: 確認文・理由と操作者が必須。成功後は「未設定」になり、次に正常確定した値で再び設定される", async () => {
    const mocks = mockFetch([route("POST", "/api/monitors/3/reading/baseline/reset", () => json(status(null)))]);
    const user = userEvent.setup();
    let latest: BaselineStatus = status();
    const { rerender } = render(<Harness initial={latest} onChanged={(next) => { latest = next; }} />);
    await user.click(screen.getByRole("button", { name: "基準値を未設定に戻す" }));
    const dialog = await screen.findByRole("dialog", { name: "読取基準値を未設定に戻す" });
    expect(within(dialog).getByText("現在の読取基準値 215998 を解除します。")).toBeInTheDocument();
    expect(within(dialog).getByText(/次に正常確定したAI読取値を新しい読取基準値として設定します/)).toBeInTheDocument();
    const submit = within(dialog).getByRole("button", { name: "未設定に戻す" });
    expect(submit).toBeDisabled();
    fillDialog(dialog, { "解除する理由": "誤読で固着", "操作者": "tester" });
    await user.click(submit);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "読取基準値を未設定に戻す" })).toBeNull());
    expect(mocks.calls.find((c: Call) => c.method === "POST")!.body).toEqual({ reason: "誤読で固着", operator: "tester" });
    expect(within(card()).getByText("未設定")).toBeInTheDocument();
    expect(latest.baseline?.state).toBe("pending_reset");
    // 次に正常確定したAI読取値が、新しい読取基準値になる(Backendの動作。画面は最新の状態を表示する)
    rerender(<ReadingSettingsPanel value={reading} onChange={() => {}} open onToggleOpen={() => {}} baseline={status("216001")} monitorId={3} />);
    expect(within(card()).getByText("216001")).toBeInTheDocument();
  });
});

// 通常のUIに、内部実装名(decrease_detected / carried_forward / baseline / rebase / reset / Raw 等)が出ていないこと。
const INTERNAL = /decrease_detected|rate_exceeded|invalid_format|carried_forward|baseline_conflict|\bmajority\b|\bconsecutive\b|\brebase\b|\breset\b|\bRaw\b|\bepoch\b|value_source|validation_status|display_status|\bmonotonic\b|\bbaseline\b|no_reading|\bpending\b|low_confidence|\bconfirmed\b|ForceRequired|FORCE_REQUIRED/;
const visibleText = () => document.body.textContent ?? "";
const attributes = () => [...document.querySelectorAll("[title],[aria-label],[alt],[placeholder]")].map((e) => ["title", "aria-label", "alt", "placeholder"].map((a) => e.getAttribute(a) ?? "").join(" ")).join(" ");

describe("通常のUIに内部名を出さない", () => {
  const carried = (status: string) => record({ id: 7, monitor_id: 3, monitor_name: "エネセン内ガスメータ用１", value: "215998", raw_value: "0215993", value_source: "carried_forward", validation_status: status, baseline_conflict: true, correctable: true, correctable_reason: "baseline_conflict" });

  it.each(["decrease_detected", "invalid_format", "rate_exceeded", "no_reading", "pending", "something_new"])("記録Drawer(%s): 項目名・本文・属性に内部名が無い", async (validation) => {
    mockFetch([get("/api/records/7/corrections", { corrections: [] })]);
    render(<RecordDrawer record={{ ...carried(validation), is_corrected: true, correction_count: 1, original_value: "215990", corrected_by: "tester", corrected_at: "2026-10-13T05:00:00" }} onClose={() => {}} onCorrected={() => {}} />);
    await screen.findByText("運用者が正式値を確認・修正しました");
    expect(visibleText()).not.toMatch(INTERNAL);
    expect(attributes()).not.toMatch(INTERNAL);
    for (const label of ["正式値", "1時間前の正式値", "使用量（前回との差）", "最新のAI読取値", "AI読取値の信頼度", "正式値の信頼度", "読取結果", "正式値の決まり方", "モニター状態", "読取基準値との不一致", "AI読取方式", "使用モデル"]) expect(screen.getAllByText(label, { selector: "dt, small" }).length).toBeGreaterThan(0);
  });

  it("記録Drawer: 時系列判定候補は、AI読取値(先頭0除去後)と異なるときだけ区別して表示する(Issue #77)", () => {
    mockFetch([get("/api/records/7/corrections", { corrections: [] })]);
    const { rerender } = render(<RecordDrawer record={{ ...carried("invalid_format"), raw_value: "0216025", candidate_value: "21625" }} onClose={() => {}} />);
    expect(screen.getByText("時系列判定候補")).toBeInTheDocument();
    rerender(<RecordDrawer record={{ ...carried("invalid_format"), raw_value: "0216025", candidate_value: "216025" }} onClose={() => {}} />);
    expect(screen.queryByText("時系列判定候補")).not.toBeInTheDocument();
    rerender(<RecordDrawer record={{ ...carried("invalid_format"), raw_value: "0216025" }} onClose={() => {}} />);
    expect(screen.queryByText("時系列判定候補")).not.toBeInTheDocument();
  });

  it("記録Drawer(carried_forward): 「直前の正式値を継続使用」と、AI読取値が採用されなかった理由・正式値の継続を説明する", async () => {
    mockFetch([get("/api/records/7/corrections", { corrections: [] })]);
    render(<RecordDrawer record={carried("decrease_detected")} onClose={() => {}} onCorrected={() => {}} />);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("直前の正式値を継続使用");
    expect(note).toHaveTextContent("今回のAI読取値「215993」は、現在の読取基準値より小さいため採用されませんでした。");
    expect(note).toHaveTextContent("そのため、直前まで使用していた正式値をこの記録でも使用しています。");
    expect(screen.getByText("履歴・使用量計算に使用する値です。")).toBeInTheDocument();
  });

  it.each(["decrease_detected", "invalid_format", "rate_exceeded", "no_reading", "pending", "something_new"])("読取値修正ダイアログ(%s): 内部名が無い", async (validation) => {
    mockFetch([get("/api/monitors/3/reading/baseline", status())]);
    render(<CorrectionDialog record={carried(validation)} onClose={() => {}} onCorrected={() => {}} />);
    await screen.findByText("現在の読取基準値");
    expect(visibleText()).not.toMatch(INTERNAL);
    expect(attributes()).not.toMatch(INTERNAL);
    expect(screen.getByText("AI読取結果")).toBeInTheDocument();
    expect(screen.getByText("正式値の決まり方")).toBeInTheDocument();
    expect(screen.getByText("読取基準値との不一致")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /読取基準値もこの値へ変更する/ })).toBeInTheDocument();
    expect(screen.getByText(/正式値だけを修正する場合はOFFのままにしてください/)).toBeInTheDocument();
  });

  it("読取安定化設定(基準値・ダイアログを含む): 内部名が無い", async () => {
    mockFetch();
    const user = userEvent.setup();
    render(<Harness initial={status()} />);
    expect(visibleText()).not.toMatch(INTERNAL);
    expect(attributes()).not.toMatch(INTERNAL);
    expect(visibleText()).not.toMatch(/epoch/); // 内部管理番号は表示しない
    for (const name of ["基準値を変更", "基準値を未設定に戻す"]) {
      await user.click(screen.getByRole("button", { name }));
      expect(visibleText()).not.toMatch(INTERNAL);
      await user.click(screen.getAllByRole("button", { name: "キャンセル" })[0]);
    }
    expect(screen.getByRole("option", { name: "多数決" })).toBeInTheDocument();
    expect(screen.getByText(/直近5回のAI読取結果を使って値を判定します。同じ値が3回以上確認された場合に採用します/)).toBeInTheDocument();
    expect(screen.getByText(/右端から何桁を小数として扱うかを指定します/)).toBeInTheDocument();
    expect(screen.getByText(/桁が最大値まで進んだあと、0へ戻るタイプのメーターで使用します/)).toBeInTheDocument();
    expect(screen.getByText(/直近の読取結果の中で、最も多く一致した値を採用します/)).toBeInTheDocument();
  });

  it("Dashboardのカード・履歴の表・グラフの印の名称に内部名が無い", () => {
    const m = monitor({ id: 3, display_name: "エネセン内ガスメータ用１", reading_baseline: { value: "215998", state: "active", confirmed_at: "2026-10-13T04:00:12", conflict: true, conflict_status: "decrease_detected", conflict_candidate: "215993", conflict_since: null, conflict_seconds: 600 } });
    const { unmount } = render(<MonitorCard monitor={m} onClick={() => {}} displayFps={5} latestRecord={carried("decrease_detected")} />);
    expect(visibleText()).not.toMatch(INTERNAL);
    expect(screen.getByText(/直前の正式値を継続使用/)).toBeInTheDocument();
    expect(document.querySelector(".carried-badge")).toHaveTextContent("のAI読取値 215993 は読取基準値より小さいため不採用");
    expect(document.querySelector(".baseline-conflict-badge")).toHaveTextContent("基準値と不一致");
    unmount();
    render(<RecordsTable items={[carried("invalid_format"), { ...carried("decrease_detected"), id: 8, is_corrected: true, correction_count: 1, baseline_conflict: false }]} onOpen={() => {}} />);
    expect(visibleText()).not.toMatch(INTERNAL);
    expect(attributes()).not.toMatch(INTERNAL);
    expect(screen.getByText("正式値", { selector: "th" })).toBeInTheDocument();
    for (const label of Object.values(chartEventLabels)) expect(label).not.toMatch(INTERNAL);
    expect(chartEventLabels).toEqual({ carried_forward: "直前の正式値を継続使用", baseline_conflict: "読取基準値との不一致", manual_corrected: "運用者が確認・修正" });
  });
});
