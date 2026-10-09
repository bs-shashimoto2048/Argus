import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { BaselineStatus, CorrectionResult, ReadingRecord } from "../types";
import { formatConfidence, formatRecordDateTimeFull, formatValue, valueSourceLabels } from "../utils/records";
import { stripLeadingZeros } from "../utils/readingFormat";

const OPERATOR_KEY = "argus.baseline.operator"; // 基準値の操作と同じ(自己申告の操作者名を覚えておく)
const loadOperator = () => { try { return window.localStorage.getItem(OPERATOR_KEY) ?? ""; } catch { return ""; } };
const saveOperator = (value: string) => { try { window.localStorage.setItem(OPERATOR_KEY, value); } catch { /* 保存できなくても動作に影響しない */ } };

type Props = { record: ReadingRecord; onClose: () => void; onCorrected: (result: CorrectionResult) => void };

// 読取値(正式値)の修正ダイアログ。carried_forward / 基準値競合中の記録だけに出る。
// 保存した元画像・overlay(記録時の証跡)を見ながら、運用者が明示的に修正値を入力する(自動確定はしない)。
// 修正しても、Raw・信頼度・判定・画像などの元証跡は変わらず、修正の監査履歴が残る。
export function CorrectionDialog({ record, onClose, onCorrected }: Props) {
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [operator, setOperator] = useState(loadOperator);
  const [rebase, setRebase] = useState(false); // 既定OFF: 履歴の修正だけでは、現在の読取基準値は変更しない
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [baseline, setBaseline] = useState<BaselineStatus | null>(null);

  // 現在の読取基準値と、基準値と矛盾している読取(競合候補)。取得できなくても修正は行える。
  useEffect(() => { api.readingBaseline(record.monitor_id).then(setBaseline).catch(() => setBaseline(null)); }, [record.monitor_id]);

  const rawCandidate = record.raw_value ? stripLeadingZeros(record.raw_value) : null;
  const ready = value.trim() !== "" && reason.trim() !== "" && operator.trim() !== "";
  const liveConflict = baseline?.conflict?.active ?? false;
  const overlayAvailable = record.image_status === "ok" && !!record.overlay_image_path;

  const submit = async () => {
    setBusy(true); setError("");
    try {
      saveOperator(operator.trim());
      const result = await api.correctRecord(record.id, { value: value.trim(), reason: reason.trim(), operator: operator.trim(), rebase_current_baseline: rebase });
      onCorrected(result);
    } catch (reasonError) {
      setError(reasonError instanceof Error ? reasonError.message : String(reasonError));
    } finally {
      setBusy(false);
    }
  };

  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="読取値の修正" style={{ zIndex: 60 }}>
    <div className="modal correction-modal">
      <div className="modal-head"><h2>読取値を修正</h2><button type="button" className="icon-button" onClick={onClose} aria-label="閉じる">×</button></div>
      <p className="muted">保存したoverlay画像で実際の値を確認してから、修正後の値を入力してください。修正しても、最新推論値・信頼度・読取判定・画像などの元の証跡は変わらず、修正の履歴が監査記録として残ります。</p>
      <div className="correction-grid">
        <div className="correction-image">
          {overlayAvailable ? <img src={api.recordImage(record.id, "overlay")} alt="記録時の推論結果画像" /> : <div className="image-empty">記録画像なし</div>}
        </div>
        <dl className="correction-facts">
          <div><dt>記録日時</dt><dd>{formatRecordDateTimeFull(record.recorded_at)}</dd></div>
          <div><dt>モニター</dt><dd>{record.monitor_name.trim()}</dd></div>
          <div><dt>現在の正式値</dt><dd className="strong">{formatValue(record.value)}</dd></div>
          <div><dt>最新推論値（Raw）</dt><dd>{formatValue(record.raw_value)}</dd></div>
          <div><dt>最新推論値の信頼度</dt><dd>{formatConfidence(record.raw_confidence)}</dd></div>
          <div><dt>読取判定</dt><dd><code>{formatValue(record.validation_status)}</code></dd></div>
          <div><dt>値の由来</dt><dd>{valueSourceLabels[record.value_source] ?? record.value_source}</dd></div>
          <div><dt>現在の読取基準値</dt><dd>{baseline?.baseline?.value ?? "--"}</dd></div>
          <div><dt>基準値競合</dt><dd>{liveConflict ? `あり（競合する読取 ${baseline?.conflict?.candidate ?? "--"}）` : record.baseline_conflict ? "記録時にあり" : "なし"}</dd></div>
        </dl>
      </div>
      <div className="correction-form">
        <label>修正後の値（正式値）
          <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="例: 215850 / 372414.3" inputMode="decimal" />
        </label>
        {rawCandidate && <button type="button" className="secondary small-button use-raw" onClick={() => setValue(rawCandidate)}>最新推論値 {rawCandidate} を入力</button>}
        <label>修正理由（必須）<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="例: 画像で桁を確認し、読取の棄却中だったため" /></label>
        <label>操作者（必須・自己申告）<input value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="氏名など" /></label>
        {(liveConflict || record.baseline_conflict) && <label className="check rebase-option">
          <input type="checkbox" checked={rebase} onChange={(e) => setRebase(e.target.checked)} /> 現在の読取基準値もこの値へ再設定する（既定はOFF。基準値の操作として、別の監査履歴も残ります）
        </label>}
        {error && <div className="alert error" role="alert">{error}</div>}
      </div>
      <div className="modal-actions">
        <button type="button" className="secondary" onClick={onClose}>キャンセル</button>
        <button type="button" onClick={() => void submit()} disabled={!ready || busy}>{busy ? "修正中…" : "この内容で修正する"}</button>
      </div>
    </div>
  </div>;
}
