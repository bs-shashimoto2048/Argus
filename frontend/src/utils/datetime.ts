// Backend(FastAPI/Pydantic)はdatetime.utcnow()由来のnaive UTC時刻をtimezone指定
// 無しのISO文字列("2026-08-20T02:11:00.665290"のようにZ/offsetが付かない)として返す。
// JavaScriptのDateはtimezone指定の無い日時文字列をUTCではなく「ローカル時刻」として
// 解釈するため、そのまま new Date() に渡すと実際の日本時間より9時間遅れて表示される
// バグになる。ここでZが無ければ付与し、UTCとして正しく解釈させる。
export function parseUtcTimestamp(value: string): Date {
  const hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

// 日本時間(JST)の時刻表示。ブラウザ自体のタイムゾーン設定に依存せず、常にJSTで表示する。
export function formatTimeJst(value: string | null | undefined): string {
  if (!value) return "--";
  return parseUtcTimestamp(value).toLocaleTimeString("ja-JP", { timeZone: "Asia/Tokyo" });
}
