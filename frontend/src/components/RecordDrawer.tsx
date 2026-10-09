import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CorrectionResult, ReadingRecord, RecordCorrection } from "../types";
import { displayStatusLabels, formatConfidence, formatRecordDateTimeFull, formatValue, imageUnavailableMessage, recordState, valueSourceLabels } from "../utils/records";
import { CorrectionDialog } from "./CorrectionDialog";
import { StateBadge } from "./StateBadge";

type Kind = "original" | "overlay";

type Props = { record: ReadingRecord; onClose: () => void; onCorrected?: (result: CorrectionResult) => void };

// 記録の詳細(右Drawer)。画像は「記録時に保存した画像」(GET /api/records/{id}/image/...)だけを表示し、現在のlive映像は使わない。
// 正式値の信頼度と最新推論値(Raw)の信頼度は別の値(前回確定値を保持した記録では別のtick)なので、分けて表示する。
export function RecordDrawer({ record, onClose, onCorrected }: Props) {
  const [kind, setKind] = useState<Kind>("original");
  const [loadFailed, setLoadFailed] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [history, setHistory] = useState<RecordCorrection[]>([]);
  useEffect(() => { setKind("original"); setLoadFailed(false); setCorrecting(false); }, [record.id]);
  useEffect(() => { setLoadFailed(false); }, [kind]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape" && !correcting) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, correcting]);
  // 修正済みの記録は、修正履歴(監査の正本)を取得して表示する。
  useEffect(() => {
    if (!record.is_corrected) { setHistory([]); return; }
    let alive = true;
    api.recordCorrections(record.id).then((r) => { if (alive) setHistory(r.corrections); }).catch(() => { if (alive) setHistory([]); });
    return () => { alive = false; };
  }, [record.id, record.is_corrected, record.correction_count]);

  const unavailable = imageUnavailableMessage(record, kind);
  const state = recordState(record);
  const carried = record.value_source === "carried_forward";
  const sourceLabel = valueSourceLabels[record.value_source] ?? record.value_source;
  const rows: [string, string][] = [
    ["記録日時", formatRecordDateTimeFull(record.recorded_at)],
    ["推論時刻", record.inference_at ? formatRecordDateTimeFull(record.inference_at) : "--（同一tick保証なしの記録）"],
    ["モニター", record.monitor_name.trim()],
    ["正式確定値", formatValue(record.value)],
    ...(record.is_corrected ? [["元の正式値", formatValue(record.original_value)] as [string, string]] : []),
    ["前回値", formatValue(record.previous_value)],
    ["使用量", formatValue(record.usage)],
    ["最新推論値（Raw）", formatValue(record.raw_value)],
    ["正式値の信頼度", formatConfidence(record.confidence)],
    ["最新推論値の信頼度", formatConfidence(record.raw_confidence)],
    ["読取判定", formatValue(record.validation_status)],
    ["値の由来", record.is_corrected ? `${sourceLabel} → 手動修正済み` : sourceLabel],
    ["表示状態", `${displayStatusLabels[record.display_status] ?? record.display_status}(${record.display_status})`],
    ["基準値競合", record.baseline_conflict ? "あり" : "なし"],
    ["推論エンジン", formatValue(record.engine)],
    ["モデル", formatValue(record.model_id)],
  ];
  return <>
    <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
    <aside className="record-drawer" role="dialog" aria-modal="true" aria-label="計測記録の詳細">
      <div className="drawer-head">
        <div><h2>計測記録の詳細</h2><StateBadge state={state} />{record.is_corrected && <span className="corrected-badge" title={`元の正式値 ${formatValue(record.original_value)}`}>修正済み{record.correction_count > 1 ? `（${record.correction_count}回）` : ""}</span>}</div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="閉じる">×</button>
      </div>
      <div className="drawer-value">
        <small>正式確定値</small>
        <strong>{formatValue(record.value)}</strong>
        {carried && <div className="carried-note" role="note">前回確定値を保持 — 記録時点の最新Raw（{formatValue(record.raw_value)}）は{formatValue(record.validation_status)}のため採用せず、それ以前に確定済みの値を正式値としました。</div>}
        {record.is_corrected && <div className="corrected-note" role="note">手動修正済み: 元の正式値 {formatValue(record.original_value)} → {formatValue(record.value)}（{record.corrected_by ?? "--"}、{record.corrected_at ? formatRecordDateTimeFull(record.corrected_at) : "--"}）。Raw・信頼度・読取判定・画像は記録時のままです。</div>}
        {record.correctable && onCorrected && <button type="button" className="secondary correct-button" onClick={() => setCorrecting(true)}>読取値を修正</button>}
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
      {record.is_corrected && <section className="correction-history" aria-label="修正履歴">
        <h3>修正履歴</h3>
        {history.length === 0 ? <p className="muted">履歴を読み込み中…</p> : <ol>
          {history.map((item) => <li key={item.id}>
            <div className="correction-line"><strong>{formatValue(item.old_value)} → {item.new_value}</strong><span>{formatRecordDateTimeFull(item.corrected_at)}</span></div>
            <div className="muted small">{item.operator} / {item.reason}</div>
            <div className="muted small">使用量 {formatValue(item.old_usage)} → {formatValue(item.new_usage)}{item.context && (item.context as { rebase?: { performed?: boolean } }).rebase?.performed ? " / 読取基準値も再設定" : ""}</div>
          </li>)}
        </ol>}
      </section>}
      {correcting && onCorrected && <CorrectionDialog record={record} onClose={() => setCorrecting(false)} onCorrected={(result) => { setCorrecting(false); onCorrected(result); }} />}
    </aside>
  </>;
}
