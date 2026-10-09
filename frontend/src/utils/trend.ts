import type { ReadingRecord } from "../types";

/** グラフの指標。usage=使用量(既定) / value=累積値(正式値の系列)。 */
export type TrendMetric = "usage" | "value";

// --- イベント(グラフ上の印)---------------------------------------------------
// 将来、基準値競合などの印をグラフへ重ねられるよう、型付きの構造とrenderer hook(TrendChartのrenderEvent)を用意する。
export type ChartEventKind = "carried_forward" | "baseline_conflict" | "manual_corrected";
export type ChartEvent = {
  kind: ChartEventKind;
  monitor_id: number;
  time: number; // 計測枠(hour_bucket)の時刻(epoch ms)
  label: string;
};

export const chartEventLabels: Record<ChartEventKind, string> = {
  carried_forward: "前回確定値を保持",
  baseline_conflict: "基準値競合",
  manual_corrected: "手動修正",
};

/** 計測枠の時刻(epoch ms)。hour_bucketはoffset付きISO。 */
export function recordTime(record: Pick<ReadingRecord, "hour_bucket" | "recorded_at">): number {
  const t = Date.parse(record.hour_bucket);
  return Number.isNaN(t) ? Date.parse(`${record.recorded_at}Z`) : t;
}

/** 記録のフィールド(value_source / baseline_conflict / is_corrected)から、グラフ用のイベントを取り出す。 */
export function extractChartEvents(records: ReadingRecord[]): ChartEvent[] {
  const events: ChartEvent[] = [];
  for (const r of records) {
    const time = recordTime(r);
    if (r.value_source === "carried_forward") events.push({ kind: "carried_forward", monitor_id: r.monitor_id, time, label: chartEventLabels.carried_forward });
    if (r.baseline_conflict) events.push({ kind: "baseline_conflict", monitor_id: r.monitor_id, time, label: chartEventLabels.baseline_conflict });
    if (r.is_corrected) events.push({ kind: "manual_corrected", monitor_id: r.monitor_id, time, label: chartEventLabels.manual_corrected });
  }
  return events;
}

// --- 系列 ---------------------------------------------------------------------
export type TrendPoint = { time: number; y: number | null };
export type TrendSeries = { monitor_id: number; name: string; points: TrendPoint[] };

function toNumber(text: string | null | undefined): number | null {
  if (text == null || text === "") return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

/**
 * 記録をMonitorごとの系列にする。系列の順序は monitors(表示順)。記録が無いMonitorの系列は作らない。
 * 値がnull(使用量なし等)の点はy=nullのまま残し、折れ線ではそこを途切れ(gap)にする。
 */
export function buildSeries(records: ReadingRecord[], monitors: { id: number; display_name: string }[], metric: TrendMetric): TrendSeries[] {
  const byMonitor = new Map<number, ReadingRecord[]>();
  for (const r of records) {
    const list = byMonitor.get(r.monitor_id);
    if (list) list.push(r); else byMonitor.set(r.monitor_id, [r]);
  }
  const order = monitors.map((m) => m.id);
  const known = new Set(order);
  const ids = [...order, ...[...byMonitor.keys()].filter((id) => !known.has(id)).sort((a, b) => a - b)]; // 削除済みMonitorは最後
  const series: TrendSeries[] = [];
  for (const id of ids) {
    const rows = byMonitor.get(id);
    if (!rows || rows.length === 0) continue;
    const name = (monitors.find((m) => m.id === id)?.display_name ?? rows[0].monitor_name).trim();
    const points = rows.map((r) => ({ time: recordTime(r), y: toNumber(metric === "usage" ? r.usage : r.value) })).sort((a, b) => a.time - b.time);
    series.push({ monitor_id: id, name, points });
  }
  return series;
}

/** yがnullの点で途切れる連続区間(=折れ線の部分パス)。長さ1の区間は孤立点。 */
export function splitSegments(points: TrendPoint[]): { time: number; y: number }[][] {
  const segments: { time: number; y: number }[][] = [];
  let current: { time: number; y: number }[] = [];
  for (const p of points) {
    if (p.y == null) { if (current.length) segments.push(current); current = []; } else current.push({ time: p.time, y: p.y });
  }
  if (current.length) segments.push(current);
  return segments;
}

/** 系列の色(Monitorごとに区別できる色)。 */
export const SERIES_COLORS = ["#2563eb", "#dc6803", "#0f9d58", "#9333ea", "#d92d20", "#0891b2", "#a16207", "#be185d"];
export const seriesColor = (index: number) => SERIES_COLORS[index % SERIES_COLORS.length];

/** 端数を丸めた「きれいな」目盛り。 */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!(max > min)) { const base = Number.isFinite(min) ? min : 0; return [base, base + 1]; }
  const rough = (max - min) / count;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= rough) ?? 10 * pow;
  const first = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let v = first; v <= max + step * 0.999; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

/** グラフ取得の上限(1回1000件 x 最大ページ数)。これを超える期間は新しい側だけを描き、注記する。 */
export const TREND_PAGE = 1000;
export const TREND_MAX_PAGES = 20;
