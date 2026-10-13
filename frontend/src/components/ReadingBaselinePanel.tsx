import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { BaselineEvent, BaselineStatus } from "../types";
import { formatDateTimeJst } from "../utils/datetime";
import { conflictMessage, formatDuration } from "../utils/readingFormat";
import { BASELINE_CHANGE_HELP, BASELINE_CHANGE_TITLE, BASELINE_CLEAR_HELP, BASELINE_CLEAR_TITLE, BASELINE_FAR_MESSAGE, BASELINE_HELP, baselineActionLabel, baselineSourceLabel } from "../utils/readingLabels";

const OPERATOR_KEY = "argus.baseline.operator";

// 操作者は自己申告(認証機構が未導入のため)。直前に入力した名前だけをブラウザへ覚えておく。
function loadOperator(): string {
  try { return window.localStorage.getItem(OPERATOR_KEY) ?? ""; } catch { return ""; }
}
function saveOperator(value: string) {
  try { window.localStorage.setItem(OPERATOR_KEY, value); } catch { /* 保存できなくても動作に影響しない */ }
}


type ForceInfo = { candidate: string; requested: string; tolerance: string };

export function ReadingBaselinePanel({ monitorId, currentValue, open, onToggleOpen }: { monitorId: number; currentValue: string | null; open: boolean; onToggleOpen: () => void }) {
  const [status, setStatus] = useState<BaselineStatus | null>(null);
  const [events, setEvents] = useState<BaselineEvent[] | null>(null);
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [operator, setOperator] = useState(loadOperator);
  const [force, setForce] = useState<ForceInfo | null>(null);
  const [forceChecked, setForceChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmingRebase, setConfirmingRebase] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    api.readingBaseline(monitorId).then(setStatus).catch(() => setStatus(null));
    api.baselineEvents(monitorId).then((response) => setEvents(response.events)).catch(() => setEvents(null));
  }, [monitorId]);

  // 開いている間だけ定期的に更新する(閉じている間はAPIを呼ばない)。
  useEffect(() => {
    if (!open) return;
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [open, refresh]);

  const disabled = busy || !status?.reading.enabled;
  const inputsReady = reason.trim() !== "" && operator.trim() !== "";

  const run = async (action: () => Promise<BaselineStatus>, done: string) => {
    setBusy(true); setError(""); setMessage("");
    try {
      saveOperator(operator.trim());
      setStatus(await action());
      setMessage(done); setForce(null); setForceChecked(false); setValue("");
      api.baselineEvents(monitorId).then((response) => setEvents(response.events)).catch(() => undefined);
    } catch (reasonError) {
      if (reasonError instanceof ApiError && reasonError.status === 409 && reasonError.detail && typeof reasonError.detail === "object" && (reasonError.detail as { code?: string }).code === "FORCE_REQUIRED") {
        const detail = reasonError.detail as { candidate: string; requested: string; tolerance: string };
        setForce({ candidate: detail.candidate, requested: detail.requested, tolerance: detail.tolerance });
        setForceChecked(false);
      } else {
        setError(reasonError instanceof Error ? reasonError.message : String(reasonError));
      }
    } finally {
      setBusy(false);
    }
  };

  // 再設定は、現baseline・最新Raw/合意候補・入力値・理由を確認してから実行する(確認ダイアログ)。
  const rebase = () => { setConfirmingRebase(false); return run(() => api.rebaseBaseline(monitorId, { value: value.trim(), reason: reason.trim(), operator: operator.trim(), force: force !== null && forceChecked }), "読取基準値を変更しました。次の正常なAI読取値から反映されます。"); };
  const reset = () => {
    if (!window.confirm(`${BASELINE_CLEAR_HELP}（表示中の現在値はすぐには変わりません。）よろしいですか？`)) return;
    run(() => api.resetBaseline(monitorId, { reason: reason.trim(), operator: operator.trim() }), "読取基準値を未設定に戻しました。次に正常確定したAI読取値を新しい読取基準値にします。");
  };

  const baseline = status?.baseline ?? null;
  const conflict = status?.conflict ?? null;
  const pending = baseline?.state === "pending_reset";

  return (
    <section className="panel collapsible-panel">
      <button type="button" className="collapsible-header" onClick={onToggleOpen} aria-expanded={open}>
        <span className="chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
        <h3>読取基準値</h3>
      </button>
      <div className="collapsible-body" style={open ? undefined : { display: "none" }}>
        <p className="muted" style={{ fontSize: "0.76rem", margin: "0 0 8px" }}>
          {BASELINE_HELP}誤った値が採用されて固着した場合や、メーターを交換した場合に、ここから運用者が明示的に変更します（小さい値が自動で採用されることはありません）。設定画面の「読取安定化設定」からも変更できます。
        </p>
        {!status && <p className="muted">読み込み中…</p>}
        {status && !status.reading.enabled && <div className="alert error">読取安定化が無効のため、読取基準値はありません（変更もできません）。</div>}
        {status && (
          <>
            {conflict?.active && conflict.alert && (
              <div className="alert warning">⚠ {conflictMessage(conflict.status, baseline?.value, conflict.candidate, conflict.duration_seconds)}</div>
            )}
            {conflict?.active && !conflict.alert && (
              <p className="muted status-note">読取基準値と矛盾するAI読取値（{conflict.candidate}）を検知しています（{formatDuration(conflict.duration_seconds)}。{formatDuration(status.alert_seconds)}続くと警告します）。</p>
            )}
            <div className="readonly-field"><small>現在の読取基準値</small>
              <strong>{pending ? "未設定（次に正常確定したAI読取値を新しい読取基準値にします）" : baseline?.value ?? "なし（最初に確定したAI読取値が基準になります）"}</strong>
            </div>
            {baseline && !pending && baseline.confirmed_at && (
              <p className="muted status-note">確定日時: {formatDateTimeJst(baseline.confirmed_at)}（{formatDuration(baseline.age_seconds)}前） / 決まり方: {baselineSourceLabel(baseline.source)}</p>
            )}
            <div className="two-col">
              <div className="readonly-field"><small>現在の正式値</small><strong>{status.current_confirmed ?? currentValue ?? "--"}</strong></div>
              <div className="readonly-field"><small>最新のAI読取値（元の桁列）</small><strong>{status.latest_raw ?? "--"}</strong></div>
            </div>
            <div className="readonly-field"><small>採用候補のAI読取値（先頭0除去後）</small>
              <strong>{status.candidate ? `${status.candidate.value}（一致 ${status.candidate.agreement_count}）` : "--"}</strong>
            </div>
            <h4 style={{ margin: "12px 0 6px" }}>{BASELINE_CHANGE_TITLE}</h4>
            <label>実メーターで確認した値（新しい読取基準値）
              <input value={value} placeholder="例: 265754 / 372398.5" onChange={(e) => { setValue(e.target.value); setForce(null); setForceChecked(false); }} />
            </label>
            <label>理由（必須）<input value={reason} placeholder="例: 誤読で固着していたため、実表示を確認して変更" onChange={(e) => setReason(e.target.value)} /></label>
            <label>操作者（必須・自己申告）<input value={operator} placeholder="氏名など" onChange={(e) => setOperator(e.target.value)} /></label>
            {force && (
              <div className="alert warning">
                {BASELINE_FAR_MESSAGE}（入力値 {force.requested} / 最新のAI読取値 {force.candidate}。目安の許容差 ±{force.tolerance}）
                <label style={{ display: "block", marginTop: 6 }}><input type="checkbox" checked={forceChecked} onChange={(e) => setForceChecked(e.target.checked)} /> 確認した上で、この値へ変更する</label>
              </div>
            )}
            <div className="settings-actions" style={{ gap: 8, display: "flex", flexWrap: "wrap" }}>
              <button type="button" className="save-button" disabled={disabled || !inputsReady || value.trim() === "" || (force !== null && !forceChecked)} onClick={() => setConfirmingRebase(true)}>読取基準値を変更</button>
              <button type="button" className="secondary" disabled={disabled || !inputsReady} onClick={reset}>{BASELINE_CLEAR_TITLE}</button>
            </div>
            <p className="muted status-note">「未設定に戻す」は、次に正常確定したAI読取値を新しい読取基準値にします（表示中の現在値はすぐには変わりません）。読取が不安定なときは、実メーターで確認した値を指定する「変更」を使ってください。</p>
            {!inputsReady && <p className="muted status-note">理由と操作者を入力すると操作できます。</p>}
            {message && <div className="alert success">{message}</div>}
            {error && <div className="alert error">{error}</div>}
            <details style={{ marginTop: 10 }}>
              <summary>監査履歴（{events?.length ?? 0}件）</summary>
              {events && events.length === 0 && <p className="muted">操作の履歴はありません。</p>}
              {events && events.length > 0 && (
                <div className="baseline-events">
                  {events.map((event) => (
                    <div key={event.id} className="baseline-event">
                      <strong>{baselineActionLabel(event.action)}</strong>
                      <span>{formatDateTimeJst(event.occurred_at)}</span>
                      <span>{event.old_value ?? "--"} → {event.new_value ?? "（次の正常なAI読取値）"}</span>
                      <span className="muted">{event.operator}{event.client_host ? ` (${event.client_host})` : ""} / {event.reason}</span>
                    </div>
                  ))}
                </div>
              )}
            </details>
          </>
        )}
      </div>
      {confirmingRebase && status && <div className="modal-backdrop" role="alertdialog" aria-modal="true" aria-label="読取基準値の変更の確認">
        <div className="modal export-modal">
          <div className="modal-head"><h2>読取基準値を変更しますか？</h2></div>
          <p className="muted">{BASELINE_CHANGE_HELP}実メーターの表示を確認した値だけを指定してください。この操作は監査履歴に残ります。</p>
          <dl className="rebase-confirm-values">
            <dt>現在の読取基準値</dt><dd>{pending ? "未設定" : baseline?.value ?? "なし"}</dd>
            <dt>最新のAI読取値</dt><dd>{status.latest_raw ?? "--"}</dd>
            <dt>採用候補</dt><dd>{status.candidate ? `${status.candidate.value}（一致 ${status.candidate.agreement_count}）` : "--"}</dd>
            <dt>新しい読取基準値</dt><dd>{value.trim()}</dd>
            <dt>理由</dt><dd>{reason.trim()}</dd>
            <dt>操作者</dt><dd>{operator.trim()}</dd>
          </dl>
          {force !== null && forceChecked && <div className="alert warning">最新のAI読取値と大きく異なる値へ変更します。</div>}
          <div className="modal-actions"><button type="button" className="secondary" onClick={() => setConfirmingRebase(false)}>キャンセル</button><button type="button" className="danger" onClick={rebase}>この値へ変更</button></div>
        </div>
      </div>}
    </section>
  );
}
