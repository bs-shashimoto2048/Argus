import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { CorrectionResult, ReadingRecord } from "../types";
import { compareRecordOrder, periodError, periodToRange, todayJst } from "../utils/records";
import { ExcelExportPanel } from "./ExcelExportPanel";
import { ExportXlButton } from "./ExportXlButton";
import { RecordDrawer } from "./RecordDrawer";
import { RecordFilters } from "./RecordFilters";
import type { RecordFilterValue } from "./RecordFilters";
import { RecordsTable } from "./RecordsTable";

/** 1回の取得件数。ページ送りはせず、スクロールの末尾に近づいたら次のこの件数ぶんを追加で取得する(巨大な一括取得を避ける)。 */
export const RECORDS_CHUNK = 500;

type Props = {
  monitors: { id: number; display_name: string }[];
  title: string;
  description?: string;
  showExport?: boolean;
  refreshMs?: number;
  // 指定すると、そのMonitorの記録だけを表示し、Monitor選択を出さない(Monitor Detailの履歴タブ)。
  fixedMonitorId?: number;
  // 履歴表(スクロール領域)の高さの用途別クラス。
  size?: "compact" | "tall";
  // 指定すると、Monitor・期間の条件を親が持つ(グラフと共有する)。省略時はこのセクション内で保持する。
  filter?: RecordFilterValue;
  onFilterChange?: (next: RecordFilterValue) => void;
  // 期間コントロールの右に [Export (XL)](現在の条件の全件を.xlsxで出力)を出す。
  showExportXl?: boolean;
};

// 計測履歴(フィルタ + 固定ヘッダーのスクロール表 + 詳細Drawer)。Dashboard下部・履歴・データ画面・Monitor Detailの履歴タブで共用する。
// ページ送りは無く、現在の条件の全件を縦スクロールだけで確認できる。内部ではchunk単位で段階的に読み込む。
export function RecordsSection({ monitors, title, description, showExport = false, refreshMs, fixedMonitorId, size = "compact", filter: controlledFilter, onFilterChange, showExportXl = false }: Props) {
  const [ownFilter, setOwnFilter] = useState<RecordFilterValue>({ monitorIds: fixedMonitorId != null ? [fixedMonitorId] : [], period: { mode: "today", startDate: todayJst(), endDate: todayJst() } });
  const filter = controlledFilter ?? ownFilter;
  const setFilter = onFilterChange ?? setOwnFilter;
  const [items, setItems] = useState<ReadingRecord[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  const [selected, setSelected] = useState<ReadingRecord | null>(null);
  const generation = useRef(0); // フィルタ変更のたびに増やし、古い応答を捨てる
  const loadingRef = useRef(false);
  const itemsRef = useRef<ReadingRecord[]>([]);

  const invalid = periodError(filter.period);
  const range = periodToRange(filter.period);
  const from = range?.from;
  const to = range?.to;
  const monitorKey = filter.monitorIds.join(",");

  const fetchChunk = useCallback((offset: number, limit: number) => {
    return api.records({ monitorIds: monitorKey ? monitorKey.split(",").map(Number) : [], from, to, limit, offset });
  }, [monitorKey, from, to]);

  // 条件(Monitor/期間)が変わったら、先頭のchunkを取り直す(即時反映)。
  useEffect(() => {
    if (!from || !to) return;
    const id = ++generation.current;
    loadingRef.current = false;
    setItems(null); setTotal(0); setError(""); setLoadingMore(false);
    itemsRef.current = [];
    fetchChunk(0, RECORDS_CHUNK)
      .then((page) => { if (id === generation.current) { itemsRef.current = page.items; setItems(page.items); setTotal(page.total); } })
      .catch((reason: Error) => { if (id === generation.current) setError(`計測履歴を取得できません（${reason.message}）`); });
  }, [fetchChunk, from, to]);

  // スクロール末尾に近づいたら、続きを追加で取得する。
  const loadMore = useCallback(() => {
    const current = itemsRef.current;
    if (loadingRef.current || current.length === 0 || current.length >= total) return;
    const id = generation.current;
    loadingRef.current = true;
    setLoadingMore(true);
    fetchChunk(current.length, RECORDS_CHUNK)
      .then((page) => {
        if (id !== generation.current) return;
        const known = new Set(itemsRef.current.map((r) => r.id));
        const merged = [...itemsRef.current, ...page.items.filter((r) => !known.has(r.id))];
        itemsRef.current = merged; setItems(merged); setTotal(page.total);
      })
      .catch((reason: Error) => { if (id === generation.current) setError(`計測履歴の続きを取得できません（${reason.message}）`); })
      .finally(() => { if (id === generation.current) { loadingRef.current = false; setLoadingMore(false); } });
  }, [fetchChunk, total]);

  // 定期更新: 新しい記録(先頭側)だけを軽く取得して差し込む(スクロール位置・読み込み済みの行は保持する)。
  // 先頭chunk(正式順序で並んだ最新100件)で、その範囲の行を置き換え、それより後ろの(すでに読み込んだ)行はそのまま残す。
  const monitorKeyOrder = monitors.map((m) => m.id).join(",");
  useEffect(() => {
    if (!refreshMs || !from || !to) return;
    const timer = window.setInterval(() => {
      if (document.hidden || itemsRef.current.length === 0) return;
      const id = generation.current;
      fetchChunk(0, 100).then((page) => {
        if (id !== generation.current) return;
        const rank = new Map(monitorKeyOrder ? monitorKeyOrder.split(",").map((id, index) => [Number(id), index] as [number, number]) : []);
        const freshIds = new Set(page.items.map((r) => r.id));
        const last = page.items[page.items.length - 1];
        // 先頭chunkが全件(または末尾が未取得)でなければ、その末尾より後ろの既存の行だけを残す(行の位置は動かさない)。
        const tail = last && page.items.length < page.total ? itemsRef.current.filter((r) => !freshIds.has(r.id) && compareRecordOrder(r, last, rank) > 0) : [];
        const merged = [...page.items, ...tail];
        itemsRef.current = merged; setItems(merged); setTotal(page.total);
      }).catch(() => { /* 次回の更新で再試行する */ });
    }, refreshMs);
    return () => window.clearInterval(timer);
  }, [refreshMs, fetchChunk, from, to, monitorKeyOrder]);

  // 読取値を修正したら、一覧の該当行(正式値・使用量・修正済み)と、使用量が再計算された次の1時間の行を、その場で更新する(行の位置は動かさない)。
  const handleCorrected = (result: CorrectionResult) => {
    const next = result.next_record;
    const merged = itemsRef.current.map((r) => {
      if (r.id === result.record.id) return result.record;
      if (next && r.id === next.record_id) return { ...r, previous_value: result.record.value, usage: next.new_usage };
      return r;
    });
    itemsRef.current = merged;
    setItems(merged);
    setSelected(result.record);
  };

  const changeFilter = (next: RecordFilterValue) => setFilter(fixedMonitorId != null ? { ...next, monitorIds: [fixedMonitorId] } : next);
  const loaded = items?.length ?? 0;
  const fmt = (n: number) => n.toLocaleString("ja-JP");
  const countText = items === null ? "" : loaded >= total ? `${fmt(total)}件（全件表示）` : `${fmt(total)}件中 ${fmt(loaded)}件を表示（下へスクロールで続きを読み込みます）`;

  return <section className="panel records-section" aria-label={title}>
    {/* 左: タイトルと説明 / 右: Monitor・期間のフィルタ(同じ行)。Excel出力は履歴・データ画面のみ。 */}
    <div className="records-head">
      <div className="records-title"><h2>{title}</h2>{description && <p className="muted">{description}</p>}</div>
      <div className="records-controls">
        <RecordFilters monitors={monitors} value={filter} onChange={changeFilter} hideMonitor={fixedMonitorId != null} />
        {showExportXl && <ExportXlButton filter={filter} />}
        {showExport && <ExcelExportPanel filter={filter} />}
      </div>
    </div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {/* 表のエリアは常に同じ高さ(読込中・0件・多数件でも変わらない)。表の中だけがスクロールする。 */}
    <div className={`records-area ${size}`} aria-busy={items === null && !error}>
      {!invalid && items && items.length > 0 && <RecordsTable items={items} onOpen={setSelected} selectedId={selected?.id} hasMore={loaded < total} loadingMore={loadingMore} onNearEnd={loadMore} groupByTime={filter.monitorIds.length === 0} />}
      {!invalid && items && items.length === 0 && !error && <div className="records-empty">この条件に該当する計測記録はありません。</div>}
      {!invalid && !items && !error && <div className="records-empty">読み込み中…</div>}
      {invalid && <div className="records-empty">期間を指定してください。</div>}
    </div>
    <div className="records-count" aria-live="polite">{countText}</div>
    {selected && <RecordDrawer record={selected} onClose={() => setSelected(null)} onCorrected={handleCorrected} />}
  </section>;
}
