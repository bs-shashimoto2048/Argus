import type { Monitor } from "../types";

// Issue #29: Monitor.status(映像Runtime接続状態)とinference_status(読取・推論状態)は
// Backend側でも別々に書き込まれる独立した値。Dashboard/Monitor Detail双方で同じ
// 合成ルールを使うことで、意味の食い違い(例: 読取不能なのに「停止中」に見える)を防ぐ。
export type CombinedMonitorStatus = "connecting" | "reconnecting" | "stopped" | "error" | "read_error" | "warning" | "normal";

// Dashboard/Detail共通のバッジ表示文言。
export const monitorStatusLabels: Record<CombinedMonitorStatus, string> = {
  connecting: "接続中",
  reconnecting: "再接続中",
  stopped: "停止中",
  error: "映像取得エラー",
  read_error: "読取不能",
  warning: "要確認",
  normal: "正常",
};

/**
 * 映像Runtime状態(monitor.status)と読取・推論状態(monitor.inference_status)を
 * 1つのバッジ表示用の値へ合成する。
 *
 * 映像に問題がある(running以外)場合は常にそれを優先して表示する(読取側の
 * 古い値に埋もれて「映像は動いているのに停止中と誤認する/その逆」が起きないようにする)。
 * 映像がrunningのときだけ、読取側の状態(read_error/low_confidence)を反映する。
 */
export function combinedMonitorStatus(monitor: Pick<Monitor, "status" | "inference_status">): CombinedMonitorStatus {
  if (monitor.status !== "running") return monitor.status;
  if (monitor.inference_status === "read_error") return "read_error";
  if (monitor.inference_status === "low_confidence") return "warning";
  return "normal";
}
