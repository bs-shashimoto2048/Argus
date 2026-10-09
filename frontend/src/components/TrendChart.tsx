import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api/client";
import type { ReadingRecord } from "../types";
import { periodError, periodToRange } from "../utils/records";
import { TREND_MAX_PAGES, TREND_PAGE, buildSeries, extractChartEvents, niceTicks, seriesColor, splitSegments } from "../utils/trend";
import type { ChartEvent, TrendMetric, TrendSeries } from "../utils/trend";
import type { RecordFilterValue } from "./RecordFilters";

const HEIGHT = 180; // グラフ本体の高さ(px)
const MARGIN = { top: 10, right: 14, bottom: 22, left: 58 };
const DEFAULT_WIDTH = 900;

/** イベント印の描画フック。nullを返すと描かない。将来の印(基準値競合など)はここへ差し込む。 */
export type EventMarkerRenderer = (event: ChartEvent, pos: { x: number; y: number; color: string }) => ReactNode;

/** 既定の印: 前回値保持=ひし形(中抜き) / 手動修正=二重丸。基準値競合は未描画(構造だけ用意)。 */
export const defaultEventRenderer: EventMarkerRenderer = (event, { x, y, color }) => {
  if (event.kind === "carried_forward") return <path d={`M${x} ${y - 5}L${x + 5} ${y}L${x} ${y + 5}L${x - 5} ${y}Z`} fill="#fff" stroke={color} strokeWidth={1.6}><title>{event.label}</title></path>;
  if (event.kind === "manual_corrected") return <g><circle cx={x} cy={y} r={6} fill="none" stroke={color} strokeWidth={1.4} /><circle cx={x} cy={y} r={2.5} fill={color} /><title>{event.label}</title></g>;
  return null;
};

const timeFormat = (spanMs: number) => {
  const withDate = spanMs > 36 * 3600_000;
  const f = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", ...(withDate ? { month: "2-digit", day: "2-digit" } : {}), hour: "2-digit", minute: "2-digit", hour12: false });
  return (t: number) => f.format(new Date(t));
};
const fullTime = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
const fmtNumber = (v: number) => v.toLocaleString("ja-JP", { maximumFractionDigits: 3 });

type Props = {
  monitors: { id: number; display_name: string }[];
  filter: RecordFilterValue; // 履歴セクションと共有する条件(Monitor・期間)
  refreshMs?: number;
  renderEvent?: EventMarkerRenderer;
};

// 使用量推移グラフ。履歴と同じ条件(Monitor・期間)のrecordsを取得し、Monitorごとに1本の折れ線(SVG手描き)で表示する。
export function TrendChart({ monitors, filter, refreshMs, renderEvent = defaultEventRenderer }: Props) {
  const [metric, setMetric] = useState<TrendMetric>("usage");
  const [records, setRecords] = useState<ReadingRecord[] | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState("");
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [hover, setHover] = useState<number | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const generation = useRef(0);

  const invalid = periodError(filter.period);
  const range = periodToRange(filter.period);
  const from = range?.from;
  const to = range?.to;
  const monitorKey = filter.monitorIds.join(",");

  // 期間内の全件(1000件ずつ最大TREND_MAX_PAGESページ)を取得する。条件が変われば取り直し、古い応答は捨てる。
  const load = useMemo(() => async (id: number, keepCurrent: boolean) => {
    if (!from || !to) return;
    const ids = monitorKey ? monitorKey.split(",").map(Number) : [];
    try {
      const all: ReadingRecord[] = [];
      let total = 0;
      for (let page = 0; page < TREND_MAX_PAGES; page += 1) {
        const result = await api.records({ monitorIds: ids, from, to, limit: TREND_PAGE, offset: page * TREND_PAGE });
        if (id !== generation.current) return;
        all.push(...result.items);
        total = result.total;
        if (all.length >= total || result.items.length === 0) break;
      }
      setRecords(all); setTruncated(all.length < total); setError("");
    } catch (reason) {
      if (id === generation.current && !keepCurrent) setError(`グラフ用の計測履歴を取得できません（${(reason as Error).message}）`);
    }
  }, [from, to, monitorKey]);

  useEffect(() => {
    if (!from || !to) return;
    const id = ++generation.current;
    setRecords(null); setError(""); setTruncated(false); setHover(null);
    void load(id, false);
  }, [load, from, to]);

  useEffect(() => {
    if (!refreshMs || !from || !to) return;
    const timer = window.setInterval(() => { if (!document.hidden) void load(generation.current, true); }, refreshMs);
    return () => window.clearInterval(timer);
  }, [refreshMs, load, from, to]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => { const w = el.clientWidth; if (w > 0) setWidth(w); });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const series: TrendSeries[] = useMemo(() => (records ? buildSeries(records, monitors, metric) : []), [records, monitors, metric]);
  const events = useMemo(() => (records ? extractChartEvents(records) : []), [records]);

  // --- 座標 ---
  const times = series.flatMap((s) => s.points.map((p) => p.time));
  const ys = series.flatMap((s) => s.points.flatMap((p) => (p.y == null ? [] : [p.y])));
  let tMin = times.length ? Math.min(...times) : 0;
  let tMax = times.length ? Math.max(...times) : 1;
  if (tMax - tMin < 3600_000) { tMin -= 1800_000; tMax += 1800_000; }
  let yMin = ys.length ? Math.min(...ys) : 0;
  let yMax = ys.length ? Math.max(...ys) : 1;
  if (metric !== "value") yMin = Math.min(0, yMin); // 使用量・累積増加量は0を基準線に含める
  if (yMax === yMin) yMax = yMin + 1;
  const ticks = niceTicks(yMin, yMax, 4);
  yMin = Math.min(yMin, ticks[0]); yMax = Math.max(yMax, ticks[ticks.length - 1]);
  const plotW = Math.max(100, width - MARGIN.left - MARGIN.right);
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const px = (t: number) => MARGIN.left + ((t - tMin) / (tMax - tMin)) * plotW;
  const py = (v: number) => MARGIN.top + (1 - (v - yMin) / (yMax - yMin)) * plotH;
  const xFormat = timeFormat(tMax - tMin);
  const xTickCount = Math.max(2, Math.min(7, Math.floor(plotW / 120)));
  const xTicks = Array.from({ length: xTickCount }, (_, i) => tMin + ((tMax - tMin) * i) / (xTickCount - 1));
  const colorOf = (monitorId: number) => seriesColor(Math.max(0, series.findIndex((s) => s.monitor_id === monitorId)));

  const uniqueTimes = useMemo(() => [...new Set(times)].sort((a, b) => a - b), [records, metric]); // eslint-disable-line react-hooks/exhaustive-deps
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (uniqueTimes.length === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / (rect.width || width)) * width;
    const t = tMin + ((x - MARGIN.left) / plotW) * (tMax - tMin);
    setHover(uniqueTimes.reduce((best, cur) => (Math.abs(cur - t) < Math.abs(best - t) ? cur : best), uniqueTimes[0]));
  };
  const hoverRows = hover == null ? [] : series.map((s, i) => ({ s, i, p: s.points.find((p) => p.time === hover) })).filter((r) => r.p);

  const metricLabel = metric === "usage" ? "使用量" : metric === "delta" ? "累積増加量" : "実値";
  const fmtDelta = (v: number) => (v > 0 ? `+${fmtNumber(v)}` : fmtNumber(v));
  const conditionText = `${filter.monitorIds.length === 0 ? "すべてのモニター" : filter.monitorIds.length === 1 ? (monitors.find((m) => m.id === filter.monitorIds[0])?.display_name.trim() ?? "選択中のモニター") : `${filter.monitorIds.length}台`}・${filter.period.mode === "today" ? "今日" : filter.period.mode === "last7" ? "過去7日" : `${filter.period.startDate} 〜 ${filter.period.endDate}`}`;
  const eventKinds = [...new Set(events.map((e) => e.kind))];
  const summary = series.map((s) => { const last = [...s.points].reverse().find((p) => p.y != null); return `${s.name}: ${last ? fmtNumber(last.y!) : "データなし"}`; }).join("、");

  return <section className="panel trend-panel" aria-label="使用量推移グラフ">
    <div className="trend-head">
      <h2>使用量推移</h2>
      <span className="segmented" role="group" aria-label="グラフの指標">
        {([["usage", "使用量"], ["delta", "累積増加量"], ["value", "実値"]] as const).map(([key, label]) => <button type="button" key={key} className={`segment${metric === key ? " active" : ""}`} aria-pressed={metric === key} onClick={() => setMetric(key)}>{label}</button>)}
      </span>
      <span className="trend-condition muted" title="Monitor・期間は計測履歴と共通です">{conditionText}</span>
      {series.length > 0 && <ul className="trend-legend" aria-label="凡例">
        {series.map((s, i) => <li key={s.monitor_id}><i style={{ background: seriesColor(i) }} aria-hidden="true" />{s.name}</li>)}
        {eventKinds.includes("carried_forward") && <li className="legend-event"><i className="marker-diamond" aria-hidden="true" />前回値保持</li>}
        {eventKinds.includes("manual_corrected") && <li className="legend-event"><i className="marker-ring" aria-hidden="true" />手動修正</li>}
      </ul>}
    </div>
    <div className="trend-body" ref={wrapRef}>
      {error && <div className="alert error" role="alert">{error}</div>}
      {invalid && <div className="trend-empty">期間を指定してください。</div>}
      {!invalid && !error && records === null && <div className="trend-empty">読み込み中…</div>}
      {!invalid && records !== null && series.length === 0 && <div className="trend-empty">この条件に該当する計測記録はありません。</div>}
      {!invalid && records !== null && series.length > 0 && <>
        <svg className="trend-svg" width={width} height={HEIGHT} viewBox={`0 0 ${width} ${HEIGHT}`} role="img" aria-label={`${metricLabel}の推移。${summary}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)} data-testid="trend-svg">
          {ticks.map((v) => <g key={v}><line x1={MARGIN.left} x2={width - MARGIN.right} y1={py(v)} y2={py(v)} stroke="#e2e8f0" strokeWidth={1} /><text x={MARGIN.left - 6} y={py(v) + 4} textAnchor="end" fontSize={11} fill="#475569">{fmtNumber(v)}</text></g>)}
          {xTicks.map((t) => <text key={t} x={px(t)} y={HEIGHT - 6} textAnchor="middle" fontSize={11} fill="#475569">{xFormat(t)}</text>)}
          {series.map((s, i) => <g key={s.monitor_id} className="trend-series" data-monitor-id={s.monitor_id} stroke={seriesColor(i)}>
            {splitSegments(s.points).map((seg, k) => seg.length === 1
              ? <circle key={k} className="trend-dot" cx={px(seg[0].time)} cy={py(seg[0].y)} r={2.6} fill={seriesColor(i)} stroke="none" />
              : <polyline key={k} className="trend-line" fill="none" strokeWidth={1.8} strokeLinejoin="round" points={seg.map((p) => `${px(p.time).toFixed(1)},${py(p.y).toFixed(1)}`).join(" ")} />)}
          </g>)}
          {events.map((event, k) => {
            const s = series.find((x) => x.monitor_id === event.monitor_id);
            if (!s) return null;
            const point = s.points.find((p) => p.time === event.time);
            const node = renderEvent(event, { x: px(event.time), y: point?.y != null ? py(point.y) : MARGIN.top + plotH, color: colorOf(event.monitor_id) });
            return node ? <g key={k} className={`trend-event event-${event.kind}`} data-monitor-id={event.monitor_id}>{node}</g> : null;
          })}
          {hover != null && <line x1={px(hover)} x2={px(hover)} y1={MARGIN.top} y2={MARGIN.top + plotH} stroke="#94a3b8" strokeDasharray="3 3" />}
        </svg>
        {hover != null && <div className="trend-tooltip" style={{ left: Math.min(Math.max(px(hover) + 10, 0), Math.max(0, width - 190)) }} role="status">
          <strong>{fullTime.format(new Date(hover))}</strong>
          {hoverRows.map(({ s, i, p }) => metric === "delta"
            ? <div key={s.monitor_id} className="tooltip-delta"><div><i style={{ background: seriesColor(i) }} aria-hidden="true" /><strong>{s.name}</strong></div><div>累積増加量: {p!.y == null ? "なし" : fmtDelta(p!.y)}</div><div>実値: {p!.actualText ?? "なし"}</div></div>
            : <div key={s.monitor_id}><i style={{ background: seriesColor(i) }} aria-hidden="true" />{s.name}: {p!.y == null ? "なし" : fmtNumber(p!.y)}</div>)}
        </div>}
        {truncated && <div className="trend-note muted">期間内の記録が多いため、新しい側の{(TREND_PAGE * TREND_MAX_PAGES).toLocaleString("ja-JP")}件までを表示しています。</div>}
      </>}
    </div>
  </section>;
}

