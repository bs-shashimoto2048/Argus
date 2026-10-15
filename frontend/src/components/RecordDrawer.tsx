import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CorrectionResult, ReadingRecord, RecordCorrection } from "../types";
import { displayStatusLabels, formatConfidence, formatRecordDateTimeFull, formatValue, imageUnavailableMessage, limitImageUpscale, recordState } from "../utils/records";
import { AI_VALUE_HELP, CARRIED_TITLE, OFFICIAL_VALUE_HELP, VALUE_SOURCE_TITLE, carriedNoteBody, recordResultLabel, valueSourceDescription, valueSourceLabel } from "../utils/readingLabels";
import { CorrectionDialog } from "./CorrectionDialog";
import { StateBadge } from "./StateBadge";
import { stripLeadingZeros } from "../utils/readingFormat";

type Kind = "original" | "overlay";

// canCorrect=false(閲覧モード)では「読取値を修正」を出さない。
type Props = { record: ReadingRecord; onClose: () => void; onCorrected?: (result: CorrectionResult) => void; canCorrect?: boolean };

// 記録の詳細(右Drawer)。画像は「記録時に保存した画像」(GET /api/records/{id}/image/...)だけを表示し、現在のlive映像は使わない。
// 正式値の信頼度と最新推論値(Raw)の信頼度は別の値(前回確定値を保持した記録では別のtick)なので、分けて表示する。
export function RecordDrawer({ record, onClose, onCorrected, canCorrect = true }: Props) {
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
  const rows: [string, string][] = [
    ["記録日時", formatRecordDateTimeFull(record.recorded_at)],
    ["推論時刻", record.inference_at ? formatRecordDateTimeFull(record.inference_at) : "--（同一tick保証なしの記録）"],
    ["モニター", record.monitor_name.trim()],
    ["正式値", formatValue(record.value)],
    ...(record.is_corrected ? [["元の正式値", formatValue(record.original_value)] as [string, string]] : []),
    ["1時間前の正式値", formatValue(record.previous_value)],
    ["使用量（前回との差）", formatValue(record.usage)],
    ["最新のAI読取値", formatValue(record.raw_value)],
    ...(record.candidate_value && record.candidate_value !== stripLeadingZeros(record.raw_value) ? [["時系列判定候補", formatValue(record.candidate_value)] as [string, string]] : []),
    ["AI読取値の信頼度", formatConfidence(record.raw_confidence)],
    ["正式値の信頼度", formatConfidence(record.confidence)],
    ["読取結果", recordResultLabel(record)],
    [VALUE_SOURCE_TITLE, valueSourceLabel(record.value_source, record.is_corrected)],
    ["モニター状態", displayStatusLabels[record.display_status] ?? "状態を確認してください"],
    ["読取基準値との不一致", record.baseline_conflict ? "あり" : "なし"],
    ["AI読取方式", formatValue(record.engine)],
    ["使用モデル", formatValue(record.model_id)],
  ];
  return <>
    <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
    <aside className="record-drawer" role="dialog" aria-modal="true" aria-label="計測記録の詳細">
      <div className="drawer-head">
        <div><h2>計測記録の詳細</h2><StateBadge state={state} />{record.is_corrected && <span className="corrected-badge" title={`元の正式値 ${formatValue(record.original_value)}`}>運用者修正{record.correction_count > 1 ? `（${record.correction_count}回）` : ""}</span>}</div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="閉じる">×</button>
      </div>
      <div className="drawer-value">
        <small title={OFFICIAL_VALUE_HELP}>正式値</small>
        <strong>{formatValue(record.value)}</strong>
        <span className="muted tiny drawer-value-help">{OFFICIAL_VALUE_HELP}</span>
        {carried && <div className="carried-note" role="note"><strong>{CARRIED_TITLE}</strong><p>{carriedNoteBody(record)}</p></div>}
        {record.is_corrected && <div className="corrected-note" role="note">
          <strong>運用者が正式値を確認・修正しました</strong>
          <dl className="corrected-facts">
            <div><dt>元の正式値</dt><dd>{formatValue(record.original_value)}</dd></div>
            <div><dt>修正後の正式値</dt><dd>{formatValue(record.value)}</dd></div>
            <div><dt>操作者</dt><dd>{record.corrected_by ?? "--"}</dd></div>
            <div><dt>日時</dt><dd>{record.corrected_at ? formatRecordDateTimeFull(record.corrected_at) : "--"}</dd></div>
          </dl>
          <p>AI読取値・信頼度・画像などの記録時証跡は変更されていません。</p>
        </div>}
        {record.correctable && onCorrected && canCorrect && <button type="button" className="secondary correct-button" onClick={() => setCorrecting(true)}>読取値を修正</button>}
      </div>
      <div className="drawer-tabs" role="tablist" aria-label="記録画像の種類">
        <button type="button" role="tab" aria-selected={kind === "original"} className={kind === "original" ? "active" : ""} onClick={() => setKind("original")}>元画像</button>
        <button type="button" role="tab" aria-selected={kind === "overlay"} className={kind === "overlay" ? "active" : ""} onClick={() => setKind("overlay")}>推論結果画像</button>
      </div>
      <div className="drawer-image">
        {unavailable ? <div className="image-empty" role="status">{unavailable}</div>
          : loadFailed ? <div className="image-empty" role="status">保存した画像を読み込めません（ファイルの削除、画像保存先の変更、共有フォルダの不通の可能性があります）</div>
          : <img key={`${record.id}-${kind}`} src={api.recordImage(record.id, kind)} alt={kind === "original" ? "記録時の元画像" : "記録時の推論結果画像"} onLoad={(e) => limitImageUpscale(e.currentTarget)} onError={() => setLoadFailed(true)} />}
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
            <div className="muted small">使用量 {formatValue(item.old_usage)} → {formatValue(item.new_usage)}{item.context && (item.context as { rebase?: { performed?: boolean } }).rebase?.performed ? " / 読取基準値も変更" : ""}</div>
          </li>)}
        </ol>}
      </section>}
      {correcting && onCorrected && <CorrectionDialog record={record} onClose={() => setCorrecting(false)} onCorrected={(result) => { setCorrecting(false); onCorrected(result); }} />}
    </aside>
  </>;
}
