import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { addDays, exportErrorMessage, formatRecordTime, imageUnavailableMessage, periodToRange, recordState, todayJst } from "../utils/records";
import { record } from "./helpers";

describe("期間(JST)", () => {
  const now = new Date("2026-10-09T05:30:00Z"); // JST 14:30
  it("今日: 当日0:00〜翌日0:00(toは排他的)", () => {
    expect(periodToRange({ mode: "today", startDate: "", endDate: "" }, now)).toEqual({ from: "2026-10-09T00:00:00+09:00", to: "2026-10-10T00:00:00+09:00" });
  });
  it("UTCで日付が前日でもJSTの今日になる", () => {
    expect(todayJst(new Date("2026-10-08T16:00:00Z"))).toBe("2026-10-09");
  });
  it("過去7日: 今日を含む7暦日", () => {
    expect(periodToRange({ mode: "last7", startDate: "", endDate: "" }, now)).toEqual({ from: "2026-10-03T00:00:00+09:00", to: "2026-10-10T00:00:00+09:00" });
  });
  it("任意期間: 終了日2026-10-09 → APIへは翌日2026-10-10 0:00 JST", () => {
    expect(periodToRange({ mode: "custom", startDate: "2026-10-08", endDate: "2026-10-09" })).toEqual({ from: "2026-10-08T00:00:00+09:00", to: "2026-10-10T00:00:00+09:00" });
  });
  it("任意期間: 月末・年末をまたぐ", () => {
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(periodToRange({ mode: "custom", startDate: "2026-10-31", endDate: "2026-10-31" })?.to).toBe("2026-11-01T00:00:00+09:00");
  });
  it("任意期間: 未入力・開始>終了は無効", () => {
    expect(periodToRange({ mode: "custom", startDate: "", endDate: "2026-10-09" })).toBeNull();
    expect(periodToRange({ mode: "custom", startDate: "2026-10-10", endDate: "2026-10-09" })).toBeNull();
  });
});

describe("表示", () => {
  it("記録時刻はJSTで表示する", () => {
    expect(formatRecordTime("2026-10-08T23:00:20")).toBe("10/09 08:00");
  });
  it("運用者向け状態への変換", () => {
    const base = record({ id: 1 });
    expect(recordState(base).label).toBe("正常");
    expect(recordState({ ...base, value_source: "carried_forward", validation_status: "decrease_detected" }).label).toBe("前回確定値を保持");
    expect(recordState({ ...base, validation_status: "low_confidence", display_status: "warning" }).label).toBe("要確認");
    expect(recordState({ ...base, display_status: "error" }).label).toBe("通信異常");
    expect(recordState({ ...base, display_status: "read_error" }).label).toBe("読取異常");
    expect(recordState({ ...base, baseline_conflict: true }).label).toBe("基準値競合");
    expect(recordState({ ...base, display_status: "stopped", value_source: "none" }).label).toBe("停止中");
  });
  it("画像の有無の説明", () => {
    expect(imageUnavailableMessage(record({ id: 1 }), "original")).toBeNull();
    expect(imageUnavailableMessage(record({ id: 1, image_status: "not_saved", original_image_path: null, overlay_image_path: null }), "original")).toContain("記録画像なし");
    expect(imageUnavailableMessage(record({ id: 1, image_status: "failed", original_image_path: null, image_error: "disk full" }), "original")).toContain("disk full");
    expect(imageUnavailableMessage(record({ id: 1, image_status: "dropped", original_image_path: null }), "original")).toContain("保存しませんでした");
    expect(imageUnavailableMessage(record({ id: 1, image_status: "disabled", original_image_path: null }), "original")).toContain("無効");
  });
  it("Excel出力エラーを運用者向けメッセージへ", () => {
    expect(exportErrorMessage(new ApiError(404, { code: "NO_RECORDS", message: "x" }))).toContain("記録がありません");
    expect(exportErrorMessage(new ApiError(409, { code: "EXPORT_IN_PROGRESS", message: "x" }))).toContain("実行中");
    expect(exportErrorMessage(new ApiError(422, "期間が不正です"))).toContain("出力条件");
    expect(exportErrorMessage(new ApiError(503, { code: "EXPORT_SAVE_TIMEOUT", message: "応答なし" }))).toContain("応答しません");
    expect(exportErrorMessage(new ApiError(503, { code: "EXPORT_SAVE_FAILED", message: "denied" }))).toContain("書き込めません");
  });
});
