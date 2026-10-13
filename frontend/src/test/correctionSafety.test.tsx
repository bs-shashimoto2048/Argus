import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CorrectionDialog } from "../components/CorrectionDialog";
import { get, json, mockFetch, record, route } from "./helpers";
import type { Call } from "./helpers";

const rec = (status: string) => record({ id: 96, monitor_id: 4, monitor_name: "食堂前機械室内メータ用", value: "372457.6", raw_value: "37245.7", value_source: "carried_forward", validation_status: status, correctable: true });
const baseline = get("/api/monitors/4/reading/baseline", { monitor_id: 4, baseline: null, conflict: null });
const rawButton = () => screen.getByRole("button", { name: /最新のAI読取値 37245\.7 を入力/ });
const fill = (value: string) => {
  fireEvent.change(screen.getByLabelText(/修正後の値/), { target: { value } });
  fireEvent.change(screen.getByLabelText(/修正理由/), { target: { value: "画像で確認" } });
  fireEvent.change(screen.getByLabelText(/操作者/), { target: { value: "tester" } });
};

describe("最新推論値の自動入力(形式が成立していないRawはワンクリックで正式値にできない)", () => {
  it.each(["invalid_format", "no_reading", "pending"])("%s: ボタンは使えず、説明が表示される", (status) => {
    mockFetch([baseline]);
    render(<CorrectionDialog record={rec(status)} onClose={() => {}} onCorrected={() => {}} />);
    expect(rawButton()).toBeDisabled();
    expect(screen.getByText("最新のAI読取値は、設定された表示桁数・小数部の形式と一致しないため自動入力できません。画像を確認して正式値を入力してください。")).toBeInTheDocument();
    fireEvent.click(rawButton());
    expect((screen.getByLabelText(/修正後の値/) as HTMLInputElement).value).toBe(""); // 入力欄は埋まらない
  });

  it.each(["decrease_detected", "rate_exceeded"])("%s: 形式は正常なので利用できるが、警告を表示する", async (status) => {
    mockFetch([baseline]);
    const user = userEvent.setup();
    render(<CorrectionDialog record={rec(status)} onClose={() => {}} onCorrected={() => {}} />);
    expect(rawButton()).toBeEnabled();
    expect(screen.getByText("この値は読取基準値または増加量の判定で採用されませんでした。画像を確認してから使用してください。")).toBeInTheDocument();
    expect(screen.queryByText(/自動入力できません/)).toBeNull();
    await user.click(rawButton());
    expect((screen.getByLabelText(/修正後の値/) as HTMLInputElement).value).toBe("37245.7");
  });

  it("手入力は、invalid_formatの記録でも従来どおりできる", () => {
    mockFetch([baseline]);
    render(<CorrectionDialog record={rec("invalid_format")} onClose={() => {}} onCorrected={() => {}} />);
    fill("372457.6");
    expect(screen.getByRole("button", { name: "この内容で修正する" })).toBeEnabled();
  });
});

describe("前後の正式値から大きく乖離した補正値の確認(2段階確認)", () => {
  const deviation = { code: "CORRECTION_FORCE_REQUIRED", message: "前後の正式値から大きく乖離しています。桁落ち・小数点位置を確認してください", details: { value: "37245.7", current_value: "372457.6", reasons: [
    { kind: "scale", reference: "直前1時間の正式値", reference_value: "372454.2", ratio: 0.1, digit_shift: true, message: "直前1時間の正式値（372454.2）の約0.1倍です（桁落ち・小数点位置の誤りの可能性）" },
  ] } };

  function setup() {
    const onCorrected = vi.fn();
    const mocks = mockFetch([baseline, route("POST", "/api/records/96/correct", (c: Call) => ((c.body as { force?: boolean }).force
      ? json({ record_id: 96, correction: {}, next_record: null, recomputed_records: [], rebase: { requested: false, performed: false } })
      : json({ detail: deviation }, 409)))]);
    render(<CorrectionDialog record={rec("invalid_format")} onClose={() => {}} onCorrected={onCorrected} />);
    return { onCorrected, posts: () => mocks.calls.filter((c: Call) => c.method === "POST").map((c) => c.body as Record<string, unknown>) };
  }

  it("大幅乖離は保存されず、確認ダイアログ(警告・理由)が出る。エラー表示にはしない", async () => {
    const { onCorrected, posts } = setup();
    const user = userEvent.setup();
    fill("37245.7");
    await user.click(screen.getByRole("button", { name: "この内容で修正する" }));
    const alert = await screen.findByText("前後の正式値から大きく乖離しています。桁落ち・小数点位置を確認してください。");
    expect(alert).toBeInTheDocument();
    expect(screen.getByText(/直前1時間の正式値（372454\.2）の約0\.1倍です/)).toBeInTheDocument();
    expect(onCorrected).not.toHaveBeenCalled();
    expect(posts()).toHaveLength(1);
    expect(posts()[0]).not.toHaveProperty("force"); // 1回目はforceなし
    expect(screen.getByRole("button", { name: "確認のうえ修正する" })).toBeDisabled(); // 確認チェックまで保存できない
  });

  it("確認(チェック)後だけ保存できる: forceつきで再送される", async () => {
    const { onCorrected, posts } = setup();
    const user = userEvent.setup();
    fill("37245.7");
    await user.click(screen.getByRole("button", { name: "この内容で修正する" }));
    await screen.findByText(/桁落ち・小数点位置を確認してください。/);
    await user.click(screen.getByRole("checkbox", { name: /画像で桁数・小数点位置を確認しました/ }));
    await user.click(screen.getByRole("button", { name: "確認のうえ修正する" }));
    await waitFor(() => expect(onCorrected).toHaveBeenCalled());
    expect(posts()).toHaveLength(2);
    expect(posts()[1]).toMatchObject({ value: "37245.7", force: true });
  });

  it("値を変えると確認はやり直しになる(以前の確認を引き継がない)", async () => {
    const { posts } = setup();
    const user = userEvent.setup();
    fill("37245.7");
    await user.click(screen.getByRole("button", { name: "この内容で修正する" }));
    await screen.findByText(/桁落ち・小数点位置を確認してください。/);
    await user.click(screen.getByRole("checkbox", { name: /画像で桁数/ }));
    fireEvent.change(screen.getByLabelText(/修正後の値/), { target: { value: "372457.6" } });
    expect(screen.queryByText(/桁落ち・小数点位置を確認してください。/)).toBeNull();
    expect(screen.getByRole("button", { name: "この内容で修正する" })).toBeEnabled();
    expect(posts()).toHaveLength(1);
  });
});
