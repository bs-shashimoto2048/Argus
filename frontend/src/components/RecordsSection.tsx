import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ReadingRecord, RecordsPage } from "../types";
import { periodError, periodToRange, todayJst } from "../utils/records";
import { ExcelExportPanel } from "./ExcelExportPanel";
import { RecordDrawer } from "./RecordDrawer";
import { RecordFilters } from "./RecordFilters";
import type { RecordFilterValue } from "./RecordFilters";
import { RecordsTable } from "./RecordsTable";

type Props = {
  monitors: { id: number; display_name: string }[];
  pageSize: number;
  title: string;
  description?: string;
  showExport?: boolean;
  refreshMs?: number;
};

// 計測履歴(フィルタ + テーブル + ページネーション + 詳細Drawer)。Dashboard下部と履歴・データ画面で共用する。
export function RecordsSection({ monitors, pageSize, title, description, showExport = false, refreshMs }: Props) {
  const [filter, setFilter] = useState<RecordFilterValue>({ monitorIds: [], period: { mode: "today", startDate: todayJst(), endDate: todayJst() } });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<RecordsPage | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<ReadingRecord | null>(null);
  const requestId = useRef(0);

  const invalid = periodError(filter.period);
  const load = useCallback(() => {
    const range = periodToRange(filter.period);
    if (!range) return;
    const id = ++requestId.current;
    setLoading(true);
    api.records({ monitorIds: filter.monitorIds, from: range.from, to: range.to, limit: pageSize, offset })
      .then((result) => { if (id === requestId.current) { setPage(result); setError(""); } })
      .catch((reason: Error) => { if (id === requestId.current) setError(`計測履歴を取得できません（${reason.message}）`); })
      .finally(() => { if (id === requestId.current) setLoading(false); });
  }, [filter, offset, pageSize]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!refreshMs) return;
    const timer = window.setInterval(() => { if (!document.hidden) load(); }, refreshMs);
    return () => window.clearInterval(timer);
  }, [load, refreshMs]);

  const changeFilter = (next: RecordFilterValue) => { setFilter(next); setOffset(0); };
  const total = page?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + pageSize, total);

  return <section className="panel records-section" aria-label={title}>
    <div className="records-head">
      <div><h2>{title}</h2>{description && <p className="muted">{description}</p>}</div>
      {showExport && <ExcelExportPanel filter={filter} />}
    </div>
    <RecordFilters monitors={monitors} value={filter} onChange={changeFilter} />
    {error && <div className="alert error" role="alert">{error}</div>}
    {!invalid && page && page.items.length > 0 && <RecordsTable items={page.items} onOpen={setSelected} selectedId={selected?.id} />}
    {!invalid && page && page.items.length === 0 && !error && <div className="records-empty">この条件に該当する計測記録はありません。</div>}
    {!invalid && !page && !error && <div className="records-empty">読み込み中…</div>}
    <div className="pager" aria-label="ページ送り">
      <span>{total}件中 {from}〜{to}件{loading && "（更新中）"}</span>
      <button type="button" className="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>前へ</button>
      <button type="button" className="secondary" disabled={offset + pageSize >= total} onClick={() => setOffset(offset + pageSize)}>次へ</button>
    </div>
    {selected && <RecordDrawer record={selected} onClose={() => setSelected(null)} />}
  </section>;
}
