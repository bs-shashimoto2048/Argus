// 最終運用値(Confirmed/UI/DB/CSV)は、Backendが整数部の先頭の0を除去した形で返す
// (backend/reading/canonicalizer.py::strip_leading_zeros と同じ規則)。Raw Reading(元の桁列)と
// Confirmedを比較する場合は、この関数でRaw側も同じ形へ揃える。
export function stripLeadingZeros(value: string | null | undefined): string | null {
  if (value == null) return null;
  if (value === "") return value;
  const dot = value.indexOf(".");
  const integer = dot === -1 ? value : value.slice(0, dot);
  const rest = dot === -1 ? "" : value.slice(dot);
  if (integer === "") return value;
  return (integer.replace(/^0+/, "") || "0") + rest;
}

// 秒数を「3時間12分」「5分」「40秒」のような短い日本語表記にする。
export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || !Number.isFinite(totalSeconds) || totalSeconds < 0) return "--";
  const seconds = Math.floor(totalSeconds);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}日${hours}時間`;
  if (hours > 0) return `${hours}時間${minutes}分`;
  if (minutes > 0) return `${minutes}分`;
  return `${seconds}秒`;
}

// conflictの警告文(Dashboard/Detailで共通)。値はいずれも最終運用値の形式(先頭0除去後)。
export function conflictMessage(status: string | null | undefined, baseline: string | null | undefined, candidate: string | null | undefined, seconds: number): string {
  const duration = formatDuration(seconds);
  if (status === "rate_exceeded") return `基準値 ${baseline ?? "--"} からの変化量が上限を超える読取 ${candidate ?? "--"} が${duration}続いています`;
  return `基準値 ${baseline ?? "--"} より小さい読取 ${candidate ?? "--"} が${duration}続いています`;
}
