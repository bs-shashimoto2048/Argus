import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ReadingRecord } from "../types";
import { displayStatusLabels, formatConfidence, formatRecordDateTimeFull, formatValue, imageUnavailableMessage, recordState, valueSourceLabels } from "../utils/records";
import { StateBadge } from "./StateBadge";

type Kind = "original" | "overlay";

// 記録の詳細(右Drawer)。画像は「記録時に保存した画像」(GET /api/records/{id}/image/...)だけを表示し、現在のlive映像は使わない。
export function RecordDrawer({ record, onClose }: { record: ReadingRecord; onClose: () => void }) {
  const [kind, setKind] = useState<Kind>("original");
  const [loadFailed, setLoadFailed] = useState(false);
  useEffect(() => { setKind("original"); setLoadFailed(false); }, [record.id]);
  useEffect(() => { setLoadFailed(false); }, [kind]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const unavailable = imageUnavailableMessage(record, kind);
  const state = recordState(record);
  const carried = record.value_source === "carried_forward";
  const rows: [string, string][] = [
    ["記録日時", formatRecordDateTimeFull(record.recorded_at)],
    ["モニター", record.monitor_name.trim()],
    ["正式確定値", formatValue(record.value)],
    ["前回値", formatValue(record.previous_value)],
    ["使用量", formatValue(record.usage)],
    ["最新推論値（Raw）", formatValue(record.raw_value)],
    ["信頼度", formatConfidence(record.confidence)],
    ["読取判定", formatValue(record.validation_status)],
    ["値の由来", valueSourceLabels[record.value_source] ?? record.value_source],
    ["表示状態", `${displayStatusLabels[record.display_status] ?? record.display_status}(${record.display_status})`],
    ["基準値競合", record.baseline_conflict ? "あり" : "なし"],
    ["推論エンジン", formatValue(record.engine)],
    ["モデル", formatValue(record.model_id)],
  ];
  return <>
    <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
    <aside className="record-drawer" role="dialog" aria-modal="true" aria-label="計測記録の詳細">
      <div className="drawer-head">
        <div><h2>計測記録の詳細</h2><StateBadge state={state} /></div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="閉じる">×</button>
      </div>
      <div className="drawer-value">
        <small>正式確定値</small>
        <strong>{formatValue(record.value)}</strong>
        {carried && <div className="carried-note" role="note">前回確定値を保持 — 記録時点の最新Raw（{formatValue(record.raw_value)}）は{formatValue(record.validation_status)}のため採用せず、それ以前に確定済みの値を正式値としました。</div>}
      </div>
      <div className="drawer-tabs" role="tablist" aria-label="記録画像の種類">
        <button type="button" role="tab" aria-selected={kind === "original"} className={kind === "original" ? "active" : ""} onClick={() => setKind("original")}>元画像</button>
        <button type="button" role="tab" aria-selected={kind === "overlay"} className={kind === "overlay" ? "active" : ""} onClick={() => setKind("overlay")}>推論結果画像</button>
      </div>
      <div className="drawer-image">
        {unavailable ? <div className="image-empty" role="status">{unavailable}</div>
          : loadFailed ? <div className="image-empty" role="status">保存した画像を読み込めません（ファイルの削除、画像保存先の変更、共有フォルダの不通の可能性があります）</div>
          : <img key={`${record.id}-${kind}`} src={api.recordImage(record.id, kind)} alt={kind === "original" ? "記録時の元画像" : "記録時の推論結果画像"} onError={() => setLoadFailed(true)} />}
      </div>
      <dl className="drawer-fields">
        {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>
    </aside>
  </>;
}
