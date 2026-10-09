import { useEffect, useMemo, useRef } from "react";
import type { ReadingRecord } from "../types";
import { formatConfidence, formatRecordTime, formatValue, hasImage, imageStatusLabels, recordState } from "../utils/records";
import { StateBadge } from "./StateBadge";

// hasMore/onNearEnd/loadingMore: スクロール末尾に近づいたら続きを読み込む(ページ送りなし)。
// groupByTime: 「すべてのモニター」のとき、同じ計測枠(取得時刻)の行を1グループとして扱い(時刻DESC → 同一時刻内はMonitorの表示順)、交互の背景と強い区切り線を付ける。
// monitorOrder: Monitorの表示順(display_order順のID配列)。単一Monitorの表示ではgroupByTime=falseにする。
type Props = { items: ReadingRecord[]; onOpen: (record: ReadingRecord) => void; selectedId?: number | null; hasMore?: boolean; loadingMore?: boolean; onNearEnd?: () => void; groupByTime?: boolean; monitorOrder?: number[] };

/** 使用量の表示。nullは「-」(0.0は0.0のまま)。DB/APIの値は変えない、表示だけの変換。 */
export function formatUsage(value: string | null | undefined): string {
  return value == null || value === "" ? "-" : value;
}

/** 時刻(計測枠)の新しい順 → 同じ時刻の中ではMonitorの表示順。 */
export function sortByTimeThenMonitor(items: ReadingRecord[], monitorOrder: number[]): ReadingRecord[] {
  const rank = new Map(monitorOrder.map((id, index) => [id, index]));
  const rankOf = (id: number) => rank.get(id) ?? Number.MAX_SAFE_INTEGER;
  return [...items].sort((a, b) => {
    if (a.hour_bucket !== b.hour_bucket) return a.hour_bucket < b.hour_bucket ? 1 : -1;
    return rankOf(a.monitor_id) - rankOf(b.monitor_id) || a.id - b.id;
  });
}

// 1時間ごとの計測履歴(reading_records)。値は記録の value(先頭0除去後の正式値)をそのまま表示する。
// 前回確定値を保持した記録(carried_forward)は、行を強調し、棄却された最新Rawも併記して「Rawの取りこぼし」に気付けるようにする。
const NEAR_END_PX = 120;

export function RecordsTable({ items, onOpen, selectedId, hasMore = false, loadingMore = false, onNearEnd, groupByTime = false, monitorOrder = [] }: Props) {
  const orderKey = monitorOrder.join(",");
  const rows = useMemo(() => (groupByTime ? sortByTimeThenMonitor(items, orderKey ? orderKey.split(",").map(Number) : []) : items), [items, groupByTime, orderKey]);
  const wrapRef = useRef<HTMLDivElement>(null);
  const nearEnd = () => { const el = wrapRef.current; return !!el && el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_END_PX; };
  // 読み込んだ行が枠に満たない(スクロールできない)間は、続きを自動で読み込む。
  useEffect(() => {
    const el = wrapRef.current;
    if (hasMore && !loadingMore && el && el.clientHeight > 0 && el.scrollHeight <= el.clientHeight + 4) onNearEnd?.();
  }, [items.length, hasMore, loadingMore, onNearEnd]);
  // 表は固定幅(table-layout: fixed + colgroup)で、ヘッダーはスクロール領域内でstickyに固定する(列位置がずれない)。
  let groupIndex = 0;
  return <div className="records-table-wrap" ref={wrapRef} onScroll={() => { if (hasMore && !loadingMore && nearEnd()) onNearEnd?.(); }} data-testid="records-scroll">
    <table className={`records-table history-table${groupByTime ? " grouped" : ""}`}>
      <colgroup><col style={{ width: 104 }} /><col /><col style={{ width: 120 }} /><col style={{ width: 100 }} /><col style={{ width: 80 }} /><col style={{ width: 80 }} /><col style={{ width: 150 }} /><col style={{ width: 70 }} /><col style={{ width: 70 }} /></colgroup>
      <thead>
        <tr><th>取得日時</th><th>モニター</th><th className="num">確定値</th><th className="num">前回値</th><th className="num">使用量</th><th className="num">信頼度</th><th>状態</th><th>画像</th><th>詳細</th></tr>
      </thead>
      <tbody>
        {rows.map((record, index) => {
          const state = recordState(record);
          const carried = record.value_source === "carried_forward";
          // 時刻グループ(すべてのモニター時のみ): 交互の背景(group-a/b)と、時刻が変わる先頭行の強い上罫線(group-start)。
          // 状態による強調(row-state-*)は、グループ背景より優先する(CSSの詳細度で担保)。
          const previous = index > 0 ? rows[index - 1] : null;
          let groupClass = "";
          if (groupByTime) {
            if (!previous || previous.hour_bucket !== record.hour_bucket) groupIndex += 1;
            groupClass = ` group-${groupIndex % 2 === 0 ? "a" : "b"}${previous && previous.hour_bucket !== record.hour_bucket ? " group-start" : ""}`;
          }
          const toneClass = state.tone === "caution" || state.tone === "danger" ? ` row-state-${state.tone}` : "";
          return <tr key={record.id} className={`${carried ? "row-carried" : ""}${toneClass}${groupClass}${selectedId === record.id ? " row-selected" : ""}`} data-record-id={record.id} data-hour-bucket={record.hour_bucket}>
            <td className="nowrap">{formatRecordTime(record.recorded_at)}</td>
            <td className="cell-monitor" title={record.monitor_name.trim()}>{record.monitor_name.trim()}</td>
            <td className="num c-value">
              <strong className="record-value">{formatValue(record.value)}</strong>
              {carried && <small className="record-raw" title="記録時点の最新Raw(棄却されたため正式値には使っていません)">Raw {formatValue(record.raw_value)}</small>}
            </td>
            <td className="num c-prev">{formatValue(record.previous_value)}</td>
            <td className="num c-usage">{formatUsage(record.usage)}</td>
            <td className="num c-conf">{formatConfidence(record.confidence)}</td>
            <td><StateBadge state={state} /></td>
            <td>{hasImage(record) ? <button type="button" className="link-button" onClick={() => onOpen(record)}>画像</button> : <span className="muted small" title={record.image_error ?? undefined}>{imageStatusLabels[record.image_status]}</span>}</td>
            <td><button type="button" className="secondary small-button" onClick={() => onOpen(record)} aria-label={`${formatRecordTime(record.recorded_at)} ${record.monitor_name.trim()} の詳細`}>詳細</button></td>
          </tr>;
        })}
        {loadingMore && <tr className="row-loading"><td colSpan={9}>続きを読み込み中…</td></tr>}
      </tbody>
    </table>
  </div>;
}
