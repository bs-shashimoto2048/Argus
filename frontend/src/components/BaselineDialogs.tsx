import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { BaselineStatus } from "../types";
import { stripLeadingZeros } from "../utils/readingFormat";
import { BASELINE_CHANGE_HELP, BASELINE_CHANGE_TITLE, BASELINE_CLEAR_HELP, BASELINE_CLEAR_TITLE, BASELINE_FAR_MESSAGE, candidateDifference, userErrorMessage } from "../utils/readingLabels";

// 読取基準値を設定画面から直接「指定値へ変更」「未設定に戻す」ための確認ダイアログ。内部のAPIは既存のrebase / reset(監査履歴つき)。
// 利用者向けの表示には rebase / reset などの内部名を出さない。
const OPERATOR_KEY = "argus.baseline.operator"; // 読取値の修正・診断タブの操作と同じ(自己申告の操作者名を覚えておく)
const loadOperator = () => { try { return window.localStorage.getItem(OPERATOR_KEY) ?? ""; } catch { return ""; } };
const saveOperator = (value: string) => { try { window.localStorage.setItem(OPERATOR_KEY, value); } catch { /* 保存できなくても動作に影響しない */ } };

type FarInfo = { candidate: string; requested: string; tolerance: string };

/** 最新のAI読取値(合意候補。無ければ最新の読取の先頭0を除いた形)。 */
export const latestAiValue = (status: BaselineStatus) => status.candidate?.value ?? (status.latest_raw ? stripLeadingZeros(status.latest_raw) : null);

type Props = { monitorId: number; status: BaselineStatus; onClose: () => void; onDone: (next: BaselineStatus) => void };

export function BaselineChangeDialog({ monitorId, status, onClose, onDone }: Props) {
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [operator, setOperator] = useState(loadOperator);
  const [far, setFar] = useState<FarInfo | null>(null); // 最新のAI読取値から大きく離れている場合の確認(2段階目)
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const current = status.baseline?.value ?? null;
  const ai = latestAiValue(status);
  const difference = candidateDifference(value.trim() || null, ai);
  const ready = value.trim() !== "" && reason.trim() !== "" && operator.trim() !== "";

  const submit = async (force: boolean) => {
    setBusy(true); setError("");
    try {
      saveOperator(operator.trim());
      onDone(await api.rebaseBaseline(monitorId, { value: value.trim(), reason: reason.trim(), operator: operator.trim(), ...(force ? { force: true } : {}) }));
    } catch (reasonError) {
      const detail = reasonError instanceof ApiError && reasonError.detail && typeof reasonError.detail === "object" ? (reasonError.detail as { code?: string; candidate?: string; requested?: string; tolerance?: string }) : null;
      if (detail?.code === "FORCE_REQUIRED") setFar({ candidate: detail.candidate ?? "--", requested: detail.requested ?? value.trim(), tolerance: detail.tolerance ?? "" }); // 保存せず、確認を求める
      else setError(userErrorMessage(reasonError));
    } finally {
      setBusy(false);
    }
  };

  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={BASELINE_CHANGE_TITLE} style={{ zIndex: 60 }}>
    <div className="modal baseline-dialog">
      <div className="modal-head"><h2>{BASELINE_CHANGE_TITLE}</h2><button type="button" className="icon-button" onClick={onClose} aria-label="閉じる">×</button></div>
      <p className="muted">{BASELINE_CHANGE_HELP}実メーターの表示を確認した値だけを指定してください。この操作は監査履歴に残ります。</p>
      <dl className="baseline-dialog-facts">
        <div><dt>現在の読取基準値</dt><dd>{current ?? "未設定"}</dd></div>
        <div><dt>最新のAI読取値</dt><dd>{ai ?? "--"}</dd></div>
        <div><dt>差</dt><dd>{difference?.text ?? "--"}</dd></div>
      </dl>
      {far ? <div className="alert warning far-confirm" role="alert">
        <strong>{BASELINE_FAR_MESSAGE}</strong>
        <dl className="baseline-dialog-facts">
          <div><dt>現在の読取基準値</dt><dd>{current ?? "未設定"}</dd></div>
          <div><dt>最新のAI読取値</dt><dd>{far.candidate}</dd></div>
          <div><dt>入力値</dt><dd>{far.requested}</dd></div>
          <div><dt>差</dt><dd>{candidateDifference(far.requested, far.candidate)?.text ?? "--"}</dd></div>
        </dl>
        <div className="modal-actions">
          <button type="button" className="secondary" onClick={() => setFar(null)}>戻る</button>
          <button type="button" className="danger" disabled={busy} onClick={() => void submit(true)}>確認して変更</button>
        </div>
      </div> : <>
        <div className="correction-form">
          <label>新しい読取基準値<input value={value} onChange={(e) => setValue(e.target.value)} placeholder="例: 265754 / 372398.5" inputMode="decimal" /></label>
          <label>変更理由（必須）<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="例: 実メーターの表示を確認し、固着していた値を修正するため" /></label>
          <label>操作者（必須・自己申告）<input value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="氏名など" /></label>
          {error && <div className="alert error" role="alert">{error}</div>}
        </div>
        <div className="modal-actions">
          <button type="button" className="secondary" onClick={onClose}>キャンセル</button>
          <button type="button" disabled={!ready || busy} onClick={() => void submit(false)}>{busy ? "変更中…" : "この値へ変更"}</button>
        </div>
      </>}
    </div>
  </div>;
}

export function BaselineClearDialog({ monitorId, status, onClose, onDone }: Props) {
  const [reason, setReason] = useState("");
  const [operator, setOperator] = useState(loadOperator);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const current = status.baseline?.value ?? null;
  const ready = reason.trim() !== "" && operator.trim() !== "";

  const submit = async () => {
    setBusy(true); setError("");
    try {
      saveOperator(operator.trim());
      onDone(await api.resetBaseline(monitorId, { reason: reason.trim(), operator: operator.trim() }));
    } catch (reasonError) {
      setError(userErrorMessage(reasonError));
    } finally {
      setBusy(false);
    }
  };

  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={BASELINE_CLEAR_TITLE} style={{ zIndex: 60 }}>
    <div className="modal baseline-dialog">
      <div className="modal-head"><h2>{BASELINE_CLEAR_TITLE}</h2><button type="button" className="icon-button" onClick={onClose} aria-label="閉じる">×</button></div>
      <p>{current ? `現在の読取基準値 ${current} を解除します。` : "現在の読取基準値は未設定です。"}</p>
      <p className="muted">{BASELINE_CLEAR_HELP}（表示中の現在値はすぐには変わりません。この操作は監査履歴に残ります。）</p>
      <div className="correction-form">
        <label>解除する理由（必須）<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="例: 誤読で固着していたため" /></label>
        <label>操作者（必須・自己申告）<input value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="氏名など" /></label>
        {error && <div className="alert error" role="alert">{error}</div>}
      </div>
      <div className="modal-actions">
        <button type="button" className="secondary" onClick={onClose}>キャンセル</button>
        <button type="button" className="danger" disabled={!ready || busy} onClick={() => void submit()}>{busy ? "解除中…" : "未設定に戻す"}</button>
      </div>
    </div>
  </div>;
}
