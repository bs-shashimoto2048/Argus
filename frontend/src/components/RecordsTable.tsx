import type { ReadingRecord } from "../types";
import { formatConfidence, formatRecordTime, formatValue, hasImage, imageStatusLabels, recordState } from "../utils/records";
import { StateBadge } from "./StateBadge";

type Props = { items: ReadingRecord[]; onOpen: (record: ReadingRecord) => void; selectedId?: number | null };

// 1時間ごとの計測履歴(reading_records)。値は記録の value(先頭0除去後の正式値)をそのまま表示する。
// 前回確定値を保持した記録(carried_forward)は、行を強調し、棄却された最新Rawも併記して「Rawの取りこぼし」に気付けるようにする。
export function RecordsTable({ items, onOpen, selectedId }: Props) {
  // 表は固定幅(table-layout: fixed + colgroup)で、ヘッダーはスクロール領域内でstickyに固定する(列位置がずれない)。
  return <div className="records-table-wrap">
    <table className="records-table">
      <colgroup><col style={{ width: 104 }} /><col /><col style={{ width: 120 }} /><col style={{ width: 100 }} /><col style={{ width: 80 }} /><col style={{ width: 80 }} /><col style={{ width: 150 }} /><col style={{ width: 70 }} /><col style={{ width: 70 }} /></colgroup>
      <thead>
        <tr><th>取得日時</th><th>モニター</th><th className="num">確定値</th><th className="num">前回値</th><th className="num">使用量</th><th className="num">信頼度</th><th>状態</th><th>画像</th><th>詳細</th></tr>
      </thead>
      <tbody>
        {items.map((record) => {
          const state = recordState(record);
          const carried = record.value_source === "carried_forward";
          return <tr key={record.id} className={`${carried ? "row-carried" : ""}${selectedId === record.id ? " row-selected" : ""}`} data-record-id={record.id}>
            <td className="nowrap">{formatRecordTime(record.recorded_at)}</td>
            <td className="cell-monitor" title={record.monitor_name.trim()}>{record.monitor_name.trim()}</td>
            <td className="num">
              <strong className="record-value">{formatValue(record.value)}</strong>
              {carried && <small className="record-raw" title="記録時点の最新Raw(棄却されたため正式値には使っていません)">Raw {formatValue(record.raw_value)}</small>}
            </td>
            <td className="num">{formatValue(record.previous_value)}</td>
            <td className="num">{formatValue(record.usage)}</td>
            <td className="num">{formatConfidence(record.confidence)}</td>
            <td><StateBadge state={state} /></td>
            <td>{hasImage(record) ? <button type="button" className="link-button" onClick={() => onOpen(record)}>画像</button> : <span className="muted small" title={record.image_error ?? undefined}>{imageStatusLabels[record.image_status]}</span>}</td>
            <td><button type="button" className="secondary small-button" onClick={() => onOpen(record)} aria-label={`${formatRecordTime(record.recorded_at)} ${record.monitor_name.trim()} の詳細`}>詳細</button></td>
          </tr>;
        })}
      </tbody>
    </table>
  </div>;
}
