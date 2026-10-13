import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CorrectionDialog } from "../components/CorrectionDialog";
import { get, json, mockFetch, record, route } from "./helpers";
import type { Call } from "./helpers";

const held = record({ id: 84, monitor_id: 4, monitor_name: "食堂前機械室内メータ用", value: "372413.7", raw_value: "37241.3", value_source: "carried_forward", validation_status: "invalid_format", correctable: true });

describe("読取値の修正: 現在の正式値と同じ値でも補正できる(画像確認済みの監査記録)", () => {
  it("同じ値を入力しても保存ボタンが有効で、補足が表示される", async () => {
    mockFetch([get("/api/monitors/4/reading/baseline", { monitor_id: 4, baseline: null, conflict: null })]);
    const user = userEvent.setup();
    render(<CorrectionDialog record={held} onClose={() => {}} onCorrected={() => {}} />);
    expect(screen.getByText(/現在の正式値と同じ値でも、画像確認済みとして補正履歴を残せます/)).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "この内容で修正する" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/修正後の値/), "372413.7"); // 現在の正式値と同じ
    await user.type(screen.getByLabelText(/修正理由/), "画像で確認");
    await user.type(screen.getByLabelText(/操作者/), "tester");
    expect(submit).toBeEnabled();
  });

  it("同じ値のまま送信すると、そのままBackendへ送られる(クライアントで弾かない)。baselineの再設定は既定でOFF", async () => {
    const onCorrected = vi.fn();
    const mocks = mockFetch([
      get("/api/monitors/4/reading/baseline", { monitor_id: 4, baseline: null, conflict: null }),
      route("POST", "/api/records/84/correct", () => json({ record_id: 84, correction: {}, next_record: null, recomputed_records: [], rebase: { requested: false, performed: false } })),
    ]);
    const user = userEvent.setup();
    render(<CorrectionDialog record={held} onClose={() => {}} onCorrected={onCorrected} />);
    fireEvent.change(screen.getByLabelText(/修正後の値/), { target: { value: "372413.7" } });
    fireEvent.change(screen.getByLabelText(/修正理由/), { target: { value: "画像で確認" } });
    fireEvent.change(screen.getByLabelText(/操作者/), { target: { value: "tester" } });
    await user.click(screen.getByRole("button", { name: "この内容で修正する" }));
    await waitFor(() => expect(onCorrected).toHaveBeenCalled());
    const post = mocks.calls.find((c: Call) => c.method === "POST" && c.url === "/api/records/84/correct")!;
    expect(post.body).toEqual({ value: "372413.7", reason: "画像で確認", operator: "tester", rebase_current_baseline: false });
  });
});
