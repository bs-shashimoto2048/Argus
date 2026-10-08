import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { BaselineEvent, BaselineStatus } from "../types";
import { formatDateTimeJst } from "../utils/datetime";
import { conflictMessage, formatDuration } from "../utils/readingFormat";

const OPERATOR_KEY = "argus.baseline.operator";

// 操作者は自己申告(認証機構が未導入のため)。直前に入力した名前だけをブラウザへ覚えておく。
function loadOperator(): string {
  try { return window.localStorage.getItem(OPERATOR_KEY) ?? ""; } catch { return ""; }
}
function saveOperator(value: string) {
  try { window.localStorage.setItem(OPERATOR_KEY, value); } catch { /* 保存できなくても動作に影響しない */ }
}

const actionLabels: Record<string, string> = { reset: "リセット", rebase: "基準値を指定", auto_semantic_reset: "自動クリア（読取設定の変更）" };

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

  const rebase = () => run(() => api.rebaseBaseline(monitorId, { value: value.trim(), reason: reason.trim(), operator: operator.trim(), force: force !== null && forceChecked }), "基準値を再設定しました。次の確定値から反映されます。");
  const reset = () => {
    if (!window.confirm("基準値をリセットします。次に正常に確定した値が新しい基準になります（表示中の現在値はすぐには変わりません）。よろしいですか？")) return;
    run(() => api.resetBaseline(monitorId, { reason: reason.trim(), operator: operator.trim() }), "基準値をリセットしました。次の確定値を新しい基準にします。");
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
          積算値が減らないことの検証（monotonic）に使う基準値です。誤った値が確定して固着した場合や、メーター交換・リセットを行った場合に、ここから明示的に再設定します（低い値が自動で採用されることはありません）。
        </p>
        {!status && <p className="muted">読み込み中…</p>}
        {status && !status.reading.enabled && <div className="alert error">読取安定化が無効のため、基準値はありません（再設定もできません）。</div>}
        {status && (
          <>
            {conflict?.active && conflict.alert && (
              <div className="alert warning">⚠ {conflictMessage(conflict.status, baseline?.value, conflict.candidate, conflict.duration_seconds)}</div>
            )}
            {conflict?.active && !conflict.alert && (
              <p className="muted status-note">基準値と矛盾する読取（{conflict.candidate}）を検知しています（{formatDuration(conflict.duration_seconds)}。{formatDuration(status.alert_seconds)}続くと警告します）。</p>
            )}
            <div className="readonly-field"><small>現在の基準値</small>
              <strong>{pending ? "リセット済み（次の確定値を新しい基準にします）" : baseline?.value ?? "なし（最初に確定した値が基準になります）"}</strong>
            </div>
            {baseline && !pending && baseline.confirmed_at && (
              <p className="muted status-note">確定日時: {formatDateTimeJst(baseline.confirmed_at)}（{formatDuration(baseline.age_seconds)}前） / 由来: {baseline.source}</p>
            )}
            <div className="two-col">
              <div className="readonly-field"><small>現在のConfirmed</small><strong>{status.current_confirmed ?? currentValue ?? "--"}</strong></div>
              <div className="readonly-field"><small>最新のRaw（元の桁列）</small><strong>{status.latest_raw ?? "--"}</strong></div>
            </div>
            <div className="readonly-field"><small>合意候補（先頭0除去後）</small>
              <strong>{status.candidate ? `${status.candidate.value}（一致 ${status.candidate.agreement_count}）` : "--"}</strong>
            </div>
            <h4 style={{ margin: "12px 0 6px" }}>基準値の再設定</h4>
            <label>実メーターで確認した値（基準値）
              <input value={value} placeholder="例: 265754 / 372398.5" onChange={(e) => { setValue(e.target.value); setForce(null); setForceChecked(false); }} />
            </label>
            <label>理由（必須）<input value={reason} placeholder="例: 誤読で固着していたため、実表示を確認して再設定" onChange={(e) => setReason(e.target.value)} /></label>
            <label>操作者（必須・自己申告）<input value={operator} placeholder="氏名など" onChange={(e) => setOperator(e.target.value)} /></label>
            {force && (
              <div className="alert warning">
                指定した値 {force.requested} は、最新のRaw合意値 {force.candidate} と大きく異なります（許容 ±{force.tolerance}）。実メーターの表示を確認してください。
                <label style={{ display: "block", marginTop: 6 }}><input type="checkbox" checked={forceChecked} onChange={(e) => setForceChecked(e.target.checked)} /> 確認した上で、この値で強制的に再設定する</label>
              </div>
            )}
            <div className="settings-actions" style={{ gap: 8, display: "flex", flexWrap: "wrap" }}>
              <button type="button" className="save-button" disabled={disabled || !inputsReady || value.trim() === "" || (force !== null && !forceChecked)} onClick={rebase}>基準値を指定して再設定</button>
              <button type="button" className="secondary" disabled={disabled || !inputsReady} onClick={reset}>基準値をリセット</button>
            </div>
            <p className="muted status-note">「リセット」は、次に正常に確定した値を新しい基準にします（表示中の現在値はすぐには変わりません）。読取が不安定なときは、実メーターで確認した値を指定する再設定を使ってください。</p>
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
                      <strong>{actionLabels[event.action] ?? event.action}</strong>
                      <span>{formatDateTimeJst(event.occurred_at)}</span>
                      <span>{event.old_value ?? "--"} → {event.new_value ?? "（次の確定値）"}</span>
                      <span className="muted">{event.operator}{event.client_host ? ` (${event.client_host})` : ""} / {event.reason}</span>
                    </div>
                  ))}
                </div>
              )}
            </details>
          </>
        )}
      </div>
    </section>
  );
}
