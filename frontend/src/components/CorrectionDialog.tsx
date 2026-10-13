import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { BaselineStatus, CorrectionDeviation, CorrectionResult, ReadingRecord } from "../types";
import { formatConfidence, formatRecordDateTimeFull, formatValue, limitImageUpscale } from "../utils/records";
import { AI_VALUE_AUTOFILL_ALLOWED, AI_VALUE_AUTOFILL_BLOCKED_MESSAGE, AI_VALUE_AUTOFILL_WARNING, AI_VALUE_AUTOFILL_WARNING_MESSAGE, AI_VALUE_HELP, BASELINE_MISMATCH_HELP, BASELINE_MISMATCH_LABEL, VALUE_SOURCE_TITLE, userErrorMessage, validationStatusDescription, validationStatusLabel, valueSourceLabel } from "../utils/readingLabels";
import { stripLeadingZeros } from "../utils/readingFormat";

const OPERATOR_KEY = "argus.baseline.operator"; // 基準値の操作と同じ(自己申告の操作者名を覚えておく)
const loadOperator = () => { try { return window.localStorage.getItem(OPERATOR_KEY) ?? ""; } catch { return ""; } };
const saveOperator = (value: string) => { try { window.localStorage.setItem(OPERATOR_KEY, value); } catch { /* 保存できなくても動作に影響しない */ } };

type Props = { record: ReadingRecord; onClose: () => void; onCorrected: (result: CorrectionResult) => void };

// 「最新のAI読取値を入力」を使える読取結果(許可リストは readingLabels.ts)。値の形式そのものが成立していない読取値はワンクリックで正式値にできない
// (例: 桁数不一致で不採用の 37245.7 を、372457.6 の正式値として誤採用した事例)。形式は正常なまま不採用になった場合は、警告つきで許可する。

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
  const [deviation, setDeviation] = useState<CorrectionDeviation | null>(null); // 前後の正式値などから大きく乖離している場合の確認要求
  const [deviationChecked, setDeviationChecked] = useState(false);

  // 現在の読取基準値と、基準値と矛盾している読取(競合候補)。取得できなくても修正は行える。
  useEffect(() => { api.readingBaseline(record.monitor_id).then(setBaseline).catch(() => setBaseline(null)); }, [record.monitor_id]);

  const rawCandidate = record.raw_value ? stripLeadingZeros(record.raw_value) : null;
  const rawAutofill = rawCandidate != null && AI_VALUE_AUTOFILL_ALLOWED.has(record.validation_status ?? "");
  const rawAutofillWarning = rawAutofill && AI_VALUE_AUTOFILL_WARNING.has(record.validation_status ?? "");
  const statusExplanation = validationStatusDescription(record.validation_status, record.raw_value, baseline?.baseline?.value);
  const ready = value.trim() !== "" && reason.trim() !== "" && operator.trim() !== "" && (deviation === null || deviationChecked);
  const changeValue = (next: string) => { setValue(next); setDeviation(null); setDeviationChecked(false); }; // 値を変えたら、確認し直す
  const liveConflict = baseline?.conflict?.active ?? false;
  const overlayAvailable = record.image_status === "ok" && !!record.overlay_image_path;
  const originalAvailable = record.image_status === "ok" && !!record.original_image_path;
  const [kind, setKind] = useState<"original" | "overlay">(overlayAvailable ? "overlay" : "original"); // 既定は推論結果(bbox・信頼度つき)。元画像へ切り替えて桁を見比べられる
  const [zoomed, setZoomed] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const imageAvailable = kind === "overlay" ? overlayAvailable : originalAvailable;
  useEffect(() => { setLoadFailed(false); }, [kind]);
  useEffect(() => {
    if (!zoomed) return undefined;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); setZoomed(false); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [zoomed]);

  const submit = async () => {
    setBusy(true); setError("");
    try {
      saveOperator(operator.trim());
      const confirmed = deviation !== null && deviationChecked; // 乖離の確認(2段階目)を済ませた場合だけforceを送る
      const result = await api.correctRecord(record.id, { value: value.trim(), reason: reason.trim(), operator: operator.trim(), rebase_current_baseline: rebase, ...(confirmed ? { force: true } : {}) });
      onCorrected(result);
    } catch (reasonError) {
      const detail = reasonError instanceof ApiError ? (reasonError.detail as { code?: string; details?: CorrectionDeviation } | null) : null;
      if (reasonError instanceof ApiError && detail?.code === "CORRECTION_FORCE_REQUIRED" && detail.details) {
        setDeviation(detail.details); setDeviationChecked(false); // 保存せず、確認を求める(エラーとしては表示しない)
      } else setError(userErrorMessage(reasonError));
    } finally {
      setBusy(false);
    }
  };

  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="読取値の修正" style={{ zIndex: 60 }}>
    <div className="modal correction-modal">
      <div className="modal-head"><h2>読取値を修正</h2><button type="button" className="icon-button" onClick={onClose} aria-label="閉じる">×</button></div>
      <p className="muted">保存した画像で実際の値を確認してから、修正後の正式値を入力してください。修正しても、AI読取値・信頼度・読取結果・画像などの記録時の証跡は変わらず、修正の履歴が監査記録として残ります。</p>
      <div className="correction-grid">
        <div className="correction-media">
          {overlayAvailable && originalAvailable && <div className="drawer-tabs correction-tabs" role="tablist" aria-label="記録画像の種類">
            <button type="button" role="tab" aria-selected={kind === "overlay"} className={kind === "overlay" ? "active" : ""} onClick={() => setKind("overlay")}>推論結果画像</button>
            <button type="button" role="tab" aria-selected={kind === "original"} className={kind === "original" ? "active" : ""} onClick={() => setKind("original")}>元画像</button>
          </div>}
          <div className="correction-image">
            {imageAvailable && !loadFailed
              ? <img key={kind} src={api.recordImage(record.id, kind)} alt={kind === "overlay" ? "記録時のAI読取結果画像" : "記録時の元画像"} title="クリックで拡大" onClick={() => setZoomed(true)} onLoad={(e) => limitImageUpscale(e.currentTarget)} onError={() => setLoadFailed(true)} />
              : <div className="image-empty">{imageAvailable ? "保存した画像を読み込めません" : "記録画像なし"}</div>}
          </div>
          {imageAvailable && !loadFailed && <p className="muted tiny correction-image-hint">画像をクリックすると拡大して全体を確認できます。</p>}
        </div>
        <dl className="correction-facts">
          <div><dt>記録日時</dt><dd>{formatRecordDateTimeFull(record.recorded_at)}</dd></div>
          <div><dt>モニター</dt><dd>{record.monitor_name.trim()}</dd></div>
          <div><dt>現在の正式値</dt><dd className="strong">{formatValue(record.value)}</dd></div>
          <div><dt title={AI_VALUE_HELP}>最新のAI読取値</dt><dd>{formatValue(record.raw_value)}</dd></div>
          <div><dt>AI読取値の信頼度</dt><dd>{formatConfidence(record.raw_confidence)}</dd></div>
          <div><dt>AI読取結果</dt><dd>{validationStatusLabel(record.validation_status)}</dd></div>
          <div><dt>{VALUE_SOURCE_TITLE}</dt><dd>{valueSourceLabel(record.value_source, record.is_corrected)}</dd></div>
          <div><dt>現在の読取基準値</dt><dd>{baseline?.baseline?.value ?? "--"}</dd></div>
          <div><dt title={BASELINE_MISMATCH_HELP}>{BASELINE_MISMATCH_LABEL}</dt><dd>{liveConflict ? `あり（不一致のAI読取値 ${baseline?.conflict?.candidate ?? "--"}）` : record.baseline_conflict ? "記録時にあり" : "なし"}</dd></div>
        </dl>
      </div>
      {statusExplanation && <p className="muted tiny status-explain" role="note">{statusExplanation}</p>}
      <div className="correction-form">
        <label>修正後の値（正式値）
          <input value={value} onChange={(e) => changeValue(e.target.value)} placeholder="例: 215850 / 372414.3" inputMode="decimal" />
          <small className="muted same-value-note">現在の正式値と同じ値でも、画像確認済みとして補正履歴を残せます。</small>
        </label>
        {rawCandidate && <button type="button" className="secondary small-button use-raw" disabled={!rawAutofill} onClick={() => changeValue(rawCandidate)}>最新のAI読取値 {rawCandidate} を入力</button>}
        {rawCandidate && !rawAutofill && <p className="muted tiny raw-blocked" role="note">{AI_VALUE_AUTOFILL_BLOCKED_MESSAGE}</p>}
        {rawAutofillWarning && <p className="tiny raw-warning" role="note">{AI_VALUE_AUTOFILL_WARNING_MESSAGE}</p>}
        <label>修正理由（必須）<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="例: 画像で桁を確認し、読取の棄却中だったため" /></label>
        <label>操作者（必須・自己申告）<input value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="氏名など" /></label>
        {(liveConflict || record.baseline_conflict) && <label className="check rebase-option">
          <input type="checkbox" checked={rebase} onChange={(e) => setRebase(e.target.checked)} /> 読取基準値もこの値へ変更する（正式値だけを修正する場合はOFFのままにしてください。読取基準値の変更として、別の監査履歴も残ります）
        </label>}
        {deviation && <div className="alert warning deviation-confirm" role="alert">
          <strong>前後の正式値から大きく乖離しています。桁落ち・小数点位置を確認してください。</strong>
          <div>入力値 {deviation.value}{deviation.current_value ? `（現在の正式値 ${deviation.current_value}）` : ""}</div>
          <ul>{deviation.reasons.map((r, i) => <li key={i}>{r.message}</li>)}</ul>
          <label className="check"><input type="checkbox" checked={deviationChecked} onChange={(e) => setDeviationChecked(e.target.checked)} /> 画像で桁数・小数点位置を確認しました。この値で保存します（監査履歴に残ります）</label>
        </div>}
        {error && <div className="alert error" role="alert">{error}</div>}
      </div>
      <div className="modal-actions">
        <button type="button" className="secondary" onClick={onClose}>キャンセル</button>
        <button type="button" onClick={() => void submit()} disabled={!ready || busy}>{busy ? "修正中…" : deviation ? "確認のうえ修正する" : "この内容で修正する"}</button>
      </div>
    </div>
    {zoomed && imageAvailable && <div className="lightbox-backdrop correction-lightbox" style={{ zIndex: 70 }} onClick={() => setZoomed(false)}>
      <div className="lightbox" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="lightbox-close" onClick={() => setZoomed(false)} aria-label="拡大表示を閉じる">×</button>
        <img className="correction-zoom-image" src={api.recordImage(record.id, kind)} alt={kind === "overlay" ? "拡大表示: 記録時のAI読取結果画像" : "拡大表示: 記録時の元画像"} />
      </div>
    </div>}
  </div>;
}
