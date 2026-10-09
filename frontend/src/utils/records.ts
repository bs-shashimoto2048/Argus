import type { DataStorageState, ImageStatus, ReadingRecord } from "../types";
import { ApiError } from "../api/client";
import { parseUtcTimestamp } from "./datetime";

// --- 期間(JST) ---------------------------------------------------------------
// Backendのfrom/toは記録時刻(recorded_at)の期間で、toは含まない(排他的)。UIでユーザーが終了日として
// 2026-10-09 を指定した場合は、翌日 2026-10-10 00:00 JST をAPIへ渡す(Backendは補正しない)。

export type PeriodMode = "today" | "last7" | "custom";
export type Period = { mode: PeriodMode; startDate: string; endDate: string }; // 日付はYYYY-MM-DD(JST)

const JST_DATE = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit" });

/** 現在のJSTの日付(YYYY-MM-DD)。 */
export function todayJst(now: Date = new Date()): string {
  return JST_DATE.format(now);
}

/** YYYY-MM-DDへ日数を加える(暦計算のみ。タイムゾーンの影響を受けない)。 */
export function addDays(date: string, days: number): string {
  const [y, m, d] = date.split("-").map(Number);
  const result = new Date(Date.UTC(y, m - 1, d + days));
  return result.toISOString().slice(0, 10);
}

export function startOfDayJst(date: string): string {
  return `${date}T00:00:00+09:00`;
}

/** 期間の選択を、APIのfrom/to(toは排他的)へ変換する。無効な期間はnull。 */
export function periodToRange(period: Period, now: Date = new Date()): { from: string; to: string } | null {
  const today = todayJst(now);
  if (period.mode === "today") return { from: startOfDayJst(today), to: startOfDayJst(addDays(today, 1)) };
  if (period.mode === "last7") return { from: startOfDayJst(addDays(today, -6)), to: startOfDayJst(addDays(today, 1)) };
  if (!period.startDate || !period.endDate || period.startDate > period.endDate) return null;
  return { from: startOfDayJst(period.startDate), to: startOfDayJst(addDays(period.endDate, 1)) };
}

export function periodError(period: Period): string | null {
  if (period.mode !== "custom") return null;
  if (!period.startDate || !period.endDate) return "開始日と終了日を指定してください";
  if (period.startDate > period.endDate) return "開始日は終了日以前にしてください";
  return null;
}

// --- 表示整形 -----------------------------------------------------------------

/** 記録時刻(UTCのISO)をJSTの「10/09 08:00」形式にする。 */
export function formatRecordTime(value: string | null | undefined): string {
  if (!value) return "--";
  const date = parseUtcTimestamp(value);
  const parts = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("month")}/${get("day")} ${get("hour")}:${get("minute")}`;
}

export function formatRecordDateTimeFull(value: string | null | undefined): string {
  if (!value) return "--";
  return parseUtcTimestamp(value).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", hour12: false });
}

export function formatConfidence(value: number | null | undefined): string {
  return value == null ? "--" : `${(value * 100).toFixed(1)}%`;
}

export function formatValue(value: string | null | undefined): string {
  return value == null || value === "" ? "--" : value;
}

// --- 運用者向けの状態 ---------------------------------------------------------

export type RecordTone = "ok" | "caution" | "danger" | "muted";
export type RecordState = { key: string; label: string; tone: RecordTone };

/**
 * 記録の元値(display_status / validation_status / value_source / baseline_conflict)を、運用者向けの
 * 1つの状態へ変換する。優先順位: 通信異常・停止 > 基準値競合 > 読取異常 > 前回確定値を保持 > 要確認 > 正常。
 * 元値そのものは詳細Drawerで確認できる。
 */
export function recordState(record: Pick<ReadingRecord, "display_status" | "validation_status" | "value_source" | "baseline_conflict">): RecordState {
  const display = record.display_status;
  if (display === "error" || display === "reconnecting" || display === "connecting") return { key: "comm_error", label: "通信異常", tone: "danger" };
  if (display === "stopped") return { key: "stopped", label: "停止中", tone: "muted" };
  if (record.baseline_conflict) return { key: "baseline_conflict", label: "基準値競合", tone: "danger" };
  if (display === "read_error") return { key: "read_error", label: "読取異常", tone: "danger" };
  if (record.value_source === "carried_forward") return { key: "carried_forward", label: "前回確定値を保持", tone: "caution" };
  if (record.value_source === "none") return { key: "no_value", label: "値なし", tone: "muted" };
  if (display === "warning" || record.validation_status === "low_confidence") return { key: "warning", label: "要確認", tone: "caution" };
  return { key: "normal", label: "正常", tone: "ok" };
}

export const displayStatusLabels: Record<string, string> = {
  normal: "正常", warning: "要確認", read_error: "読取不能", error: "通信異常", reconnecting: "再接続中", connecting: "接続中", stopped: "停止中",
};
export const valueSourceLabels: Record<string, string> = {
  confirmed: "確定(confirmed)", carried_forward: "前回確定値を保持(carried_forward)", none: "値なし(none)",
};

// --- 記録画像 -----------------------------------------------------------------

/** 画像が保存されていない場合の説明(保存済みの場合はnull)。 */
export function imageUnavailableMessage(record: Pick<ReadingRecord, "image_status" | "original_image_path" | "overlay_image_path" | "image_error">, kind: "original" | "overlay"): string | null {
  const path = kind === "original" ? record.original_image_path : record.overlay_image_path;
  const status: ImageStatus = record.image_status;
  if (status === "ok" && path) return null;
  switch (status) {
    case "not_saved": return "記録画像なし（この記録は画像保存の開始前に作成されました）";
    case "disabled": return "記録画像なし（画像保存が無効でした）";
    case "failed": return `画像の保存に失敗しました${record.image_error ? `：${record.image_error}` : ""}`;
    case "dropped": return `画像を保存しませんでした${record.image_error ? `：${record.image_error}` : "（容量不足または保存先の障害）"}`;
    case "pending": return "画像を保存中です。しばらくしてから開き直してください";
    default: return "記録画像なし";
  }
}

export function hasImage(record: Pick<ReadingRecord, "image_status" | "original_image_path" | "overlay_image_path">): boolean {
  return record.image_status === "ok" && !!(record.original_image_path || record.overlay_image_path);
}

export const imageStatusLabels: Record<ImageStatus, string> = {
  ok: "保存済み", not_saved: "画像なし", failed: "保存失敗", dropped: "保存せず", disabled: "保存無効", pending: "保存中",
};

// --- Excel出力のエラー ----------------------------------------------------------

/** Excel出力APIのエラー(422/404/409/503)を運用者向けメッセージへ変換する。 */
export function exportErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const code = error.detail && typeof error.detail === "object" && "code" in error.detail ? String((error.detail as { code: unknown }).code) : "";
    if (error.status === 422) return `出力条件が正しくありません。期間とモニターを確認してください（${error.message}）`;
    if (error.status === 404 || code === "NO_RECORDS") return "対象の期間・モニターに記録がありません。条件を変えてください";
    if (error.status === 409 || code === "EXPORT_IN_PROGRESS") return "別のExcel出力を実行中です。完了してからもう一度お試しください";
    if (error.status === 503) {
      if (code === "EXPORT_SAVE_TIMEOUT") return `サーバーの保存先が応答しません。ネットワーク共有の接続を確認してください（${error.message}）`;
      return `サーバーの保存先へ書き込めませんでした。システム設定でExcel保存先を確認してください（${error.message}）`;
    }
    return `Excel出力に失敗しました（${error.message}）`;
  }
  return `Excel出力に失敗しました（${error instanceof Error ? error.message : String(error)}）`;
}

// --- データ保存状態 -------------------------------------------------------------

export const storageStateLabels: Record<DataStorageState, { label: string; tone: RecordTone; hint: string }> = {
  ok: { label: "正常", tone: "ok", hint: "記録画像を保存できます" },
  warning: { label: "警告", tone: "caution", hint: "保存先の空き容量が少なくなっています" },
  stopped: { label: "保存停止", tone: "danger", hint: "空き容量が停止しきい値を下回り、新しい画像を保存していません（計測値の記録は継続）" },
  failing: { label: "保存先異常", tone: "danger", hint: "保存先に書き込めません。保存先の接続・権限を確認してください（計測値の記録は継続）" },
  disabled: { label: "保存無効", tone: "muted", hint: "元画像・推論画像の保存がどちらもOFFです" },
};
