// 読取結果・正式値・読取基準値に関する、利用者向けの表示文言の共通mapper。
// 通常のUIには内部名(decrease_detected / carried_forward / baseline / rebase / reset / Raw 等)を出さない。
// 内部のAPI・DB・変数名はそのままで、表示の文言だけをここへ集約する(Componentごとに文言を持たない)。
// 診断タブなど技術者向けの画面では、内部名を括弧で併記してよい(internalName()で作る)。
import { ApiError } from "../api/client";
import type { ReadingRecord } from "../types";
import { stripLeadingZeros } from "./readingFormat";

export const AI_VALUE_LABEL = "最新のAI読取値";
export const AI_VALUE_HELP = "AIが画像から読み取った最新値です。正式値として採用される前の候補値を含みます。";
export const OFFICIAL_VALUE_LABEL = "正式値";
export const OFFICIAL_VALUE_HELP = "履歴・使用量計算に使用する値です。";
export const BASELINE_LABEL = "読取基準値";
export const BASELINE_HELP = "積算値の減少チェックを行う際に、AI読取値と比較する基準となる値です。";
export const BASELINE_MISMATCH_LABEL = "読取基準値との不一致";
export const BASELINE_MISMATCH_BADGE = "基準値と不一致";
export const BASELINE_MISMATCH_HELP = "AI読取値が現在の読取基準値と矛盾しているため、正式値として採用していません。";
export const CARRIED_TITLE = "直前の正式値を継続使用";

/** 技術者向け画面での併記: 「読取基準値より小さいため不採用（decrease_detected）」。 */
export const internalName = (label: string, internal: string | null | undefined) => (internal ? `${label}（${internal}）` : label);

// --- AI読取結果(validation_status) -------------------------------------------------

const STATUS_LABELS: Record<string, string> = {
  confirmed: "採用",
  low_confidence: "信頼度が低いため要確認",
  decrease_detected: "読取基準値より小さいため不採用",
  rate_exceeded: "増加量が設定上限を超えたため不採用",
  invalid_format: "表示桁数・小数部の形式が一致しないため不採用",
  no_reading: "読取値を取得できません",
  pending: "判定中",
};
export const UNKNOWN_STATUS_LABEL = "判定状態を確認してください";

export function validationStatusLabel(status: string | null | undefined): string {
  if (!status) return "--";
  return STATUS_LABELS[status] ?? UNKNOWN_STATUS_LABEL;
}

/** AI読取値を利用者向けに整える(先頭0を除いた形。無ければ「--」)。 */
export const aiValueText = (raw: string | null | undefined) => (raw ? stripLeadingZeros(raw) : "--");

/** 値の形式そのものが成立していない読取結果。最新のAI読取値をワンクリックで正式値にしてはいけない。 */
export const AI_VALUE_AUTOFILL_ALLOWED = new Set(["confirmed", "low_confidence", "decrease_detected", "rate_exceeded"]);
/** 形式は正常だが、採用されなかった読取結果(自動入力できるが、画像確認を促す)。 */
export const AI_VALUE_AUTOFILL_WARNING = new Set(["decrease_detected", "rate_exceeded"]);
export const AI_VALUE_AUTOFILL_BLOCKED_MESSAGE = "最新のAI読取値は、設定された表示桁数・小数部の形式と一致しないため自動入力できません。画像を確認して正式値を入力してください。";
export const AI_VALUE_AUTOFILL_WARNING_MESSAGE = "この値は読取基準値または増加量の判定で採用されませんでした。画像を確認してから使用してください。";

/**
 * 読取結果ごとの説明(「なぜ採用されなかったか」と、その結果として正式値がどうなったか)。
 * raw=AI読取値(元の桁列でも可)、baseline=現在の読取基準値(分かる場合)。confirmed/未知は説明なし(null)。
 */
export function validationStatusDescription(status: string | null | undefined, raw?: string | null, baseline?: string | null): string | null {
  const value = raw ? `「${aiValueText(raw)}」` : "";
  const carried = "そのため、直前の正式値を継続使用しています。";
  switch (status) {
    case "decrease_detected":
      return `今回のAI読取値${value}は、現在の読取基準値${baseline ? `「${baseline}」` : ""}より小さいため採用されませんでした。\nそのため、直前まで使用していた正式値をこの記録でも使用しています。`;
    case "invalid_format":
      return `今回のAI読取値${value}は、設定された表示桁数・小数部の形式と一致しなかったため、正式値として採用されませんでした。\n${carried}`;
    case "rate_exceeded":
      return `今回のAI読取値${value}は、設定した1分あたりの最大増加量を超えたため採用されませんでした。\n${carried}`;
    case "no_reading":
      return "この時刻はAI読取値を取得できなかったため、直前の正式値を継続使用しています。";
    case "pending":
      return `今回のAI読取値${value}は、同じ値の一致回数がまだ足りず判定中のため採用されませんでした。\n${carried}`;
    case "low_confidence":
      return `今回のAI読取値${value}は、信頼度が低いため要確認です。`;
    default:
      return null;
  }
}

// --- 正式値の決まり方(value_source) --------------------------------------------------

export const VALUE_SOURCE_TITLE = "正式値の決まり方";
const SOURCE_LABELS: Record<string, string> = { confirmed: "今回のAI読取値を採用", carried_forward: "直前の正式値を継続使用", none: "正式値なし" };
const SOURCE_HELPS: Record<string, string> = {
  confirmed: "AI読取値が判定を通り、正式値として採用されました。",
  carried_forward: "AI読取値が採用されなかったため、直前まで使用していた正式値をこの記録でも使用しています。",
  none: "この時刻は正式値を決められませんでした。",
};
export const CORRECTED_SOURCE_LABEL = "運用者が確認・修正";

export function valueSourceLabel(source: string | null | undefined, corrected = false): string {
  if (corrected) return source === "carried_forward" ? `${CARRIED_TITLE} → ${CORRECTED_SOURCE_LABEL}` : CORRECTED_SOURCE_LABEL;
  return (source && SOURCE_LABELS[source]) || UNKNOWN_STATUS_LABEL;
}
export const valueSourceDescription = (source: string | null | undefined) => (source && SOURCE_HELPS[source]) || null;

/** 記録(Drawer・Dashboard・グラフの印)の「直前の正式値を継続使用」の説明本文。 */
export function carriedNoteBody(record: Pick<ReadingRecord, "validation_status" | "raw_value">, baseline?: string | null): string {
  return validationStatusDescription(record.validation_status, record.raw_value, baseline)
    ?? `今回のAI読取値${record.raw_value ? `「${aiValueText(record.raw_value)}」` : ""}は採用されなかったため、直前の正式値を継続使用しています。`;
}

// --- 読取基準値(baseline) ----------------------------------------------------------

const BASELINE_SOURCE: Record<string, string> = { confirmed: "通常確定", operator_rebase: "運用者が変更", operator_reset: "運用者が解除", auto_semantic_reset: "読取設定の変更に伴い自動解除", db: "保存済みの読取基準値" };
export const baselineSourceLabel = (source: string | null | undefined) => (source && BASELINE_SOURCE[source]) || "--";
const BASELINE_ACTIONS: Record<string, string> = { reset: "読取基準値を未設定に戻す", rebase: "読取基準値を変更", auto_semantic_reset: "読取設定の変更に伴い読取基準値を自動解除" };
export const baselineActionLabel = (action: string) => BASELINE_ACTIONS[action] ?? "読取基準値の操作";
export const baselineStateLabel = (state: string | null | undefined) => (state === "pending_reset" ? "未設定（次の正常なAI読取値を自動設定）" : state ? "有効" : "--");

export const BASELINE_CHANGE_TITLE = "読取基準値を指定値へ変更";
export const BASELINE_CHANGE_HELP = "現在の読取基準値を、運用者が確認した値へ変更します。";
export const BASELINE_CLEAR_TITLE = "読取基準値を未設定に戻す";
export const BASELINE_CLEAR_HELP = "現在の読取基準値を解除し、次に正常確定したAI読取値を新しい読取基準値として設定します。";
export const BASELINE_FAR_MESSAGE = "入力した基準値は、最新のAI読取値から大きく離れています。桁数・小数点位置・実メーターの表示を確認してください。";

// --- 判定方式(majority / consecutive) と設定項目 ------------------------------------

export const MODE_LABELS: Record<string, string> = { majority: "多数決", consecutive: "連続一致" };
export const MODE_HELPS: Record<string, string> = { majority: "直近の読取結果の中で、最も多く一致した値を採用します。", consecutive: "同じ値が指定回数連続した場合に採用します。" };

// --- 補正・APIのエラー(内部codeは画面に出さない) ---------------------------------------

export const CORRECTION_FAR_MESSAGE = "前後の正式値から大きく乖離しています。桁落ち・小数点位置を確認してください。";

/** APIエラーを利用者向けの日本語にする。内部code(CORRECTION_FORCE_REQUIRED等)は表示しない(必要ならconsoleへ)。 */
export function userErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const code = error.detail && typeof error.detail === "object" ? (error.detail as { code?: string }).code : undefined;
    if (code) console.warn(`API error: ${code} (HTTP ${error.status})`);
    switch (code) {
      case "CORRECTION_FORCE_REQUIRED": return CORRECTION_FAR_MESSAGE;
      case "FORCE_REQUIRED": case "REBASE_FORCE_REQUIRED": return BASELINE_FAR_MESSAGE;
      case "NO_CHANGE": return "現在の値と同じです。";
      case "INVALID_VALUE": return error.message && !/^[A-Z_]+$/.test(error.message) ? error.message : "値の形式が正しくありません。";
      case "NOT_CORRECTABLE": return "この記録の正式値は修正できません。";
      default: break;
    }
    return error.message && !/^(HTTP \d+|[A-Z][A-Z_]+)$/.test(error.message) ? error.message : `処理に失敗しました（HTTP ${error.status}）`;
  }
  return error instanceof Error ? error.message : String(error);
}

// --- 読取基準値と最新のAI読取値の比較(設定画面の判定状態カード) ---------------------------------------
const decimals = (text: string) => (text.includes(".") ? text.split(".")[1].length : 0);

/** 候補値 - 基準値(小数桁は両者の大きい方に揃える)。数値でなければnull。 */
export function candidateDifference(candidate: string | null | undefined, baseline: string | null | undefined): { text: string; negative: boolean } | null {
  if (!candidate || !baseline) return null;
  const c = Number(candidate), b = Number(baseline);
  if (!Number.isFinite(c) || !Number.isFinite(b)) return null;
  const places = Math.max(decimals(candidate), decimals(baseline));
  const diff = Number((c - b).toFixed(places));
  return { text: `${diff > 0 ? "+" : ""}${diff.toFixed(places)}`, negative: diff < 0 };
}

const statusReasons: Record<string, { text: string; warn: boolean }> = {
  decrease_detected: { text: "基準値未満のため不採用", warn: true },
  invalid_format: { text: STATUS_LABELS.invalid_format, warn: true },
  rate_exceeded: { text: STATUS_LABELS.rate_exceeded, warn: true },
  no_reading: { text: "読取値を取得できないため直前の正式値を継続使用", warn: true },
  low_confidence: { text: STATUS_LABELS.low_confidence, warn: true },
  pending: { text: "判定中（一致回数が不足）", warn: false },
  confirmed: { text: STATUS_LABELS.confirmed, warn: false },
};

/** 現在の判定(利用者向けの説明)。候補が基準値未満で減少チェックONなら、statusに関わらず「基準値未満のため不採用」。 */
export function judgement(monotonic: boolean, difference: { negative: boolean } | null, validationStatus: string | null | undefined): { text: string; warn: boolean } | null {
  if (monotonic && difference?.negative) return statusReasons.decrease_detected;
  if (validationStatus && statusReasons[validationStatus]) return statusReasons[validationStatus];
  if (difference) return monotonic ? { text: "基準値以上（減少なし）", warn: false } : { text: "減少チェックOFFのため基準値との比較なし", warn: false };
  return null;
}

