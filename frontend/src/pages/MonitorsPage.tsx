import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Monitor } from "../types";
import { combinedMonitorStatus, monitorStatusLabels } from "../utils/monitorStatus";
import { formatDateTimeJst } from "../utils/datetime";

type SaveState = "idle" | "saving" | "saved" | "error";

function move<T>(items: T[], from: number, to: number): T[] {
  const next = items.slice();
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

// モニター管理: 登録済みMonitorの一覧と、表示順の変更(Dashboardの並びと同じ)・詳細(既存のMonitor Detail)・新規追加への導線。
// 表示順は、ドラッグ&ドロップまたは↑↓ボタンで変更でき、操作の完了時に自動保存する(PUT /api/monitors/order)。
// 保存中は楽観的に新しい順を表示し、失敗したときは元の順へ戻してエラーを表示する。
export function MonitorsPage() {
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [orderError, setOrderError] = useState("");
  const [dragId, setDragId] = useState<number | null>(null);
  const [overId, setOverId] = useState<number | null>(null);
  const navigate = useNavigate();
  // 並べ替えの保存中は、定期取得の結果で表示順を上書きしない(一瞬別の順に戻るちらつきを防ぐ)。
  const savingRef = useRef(false);
  const savedTimer = useRef<number | undefined>(undefined);

  const load = () => api.monitors().then((result) => {
    if (!savingRef.current) setMonitors(result.monitors);
    setError("");
  }).catch((reason: Error) => setError(reason.message)).finally(() => setLoaded(true));

  useEffect(() => {
    load();
    const timer = window.setInterval(() => { if (!document.hidden) load(); }, 5000);
    return () => { window.clearInterval(timer); window.clearTimeout(savedTimer.current); };
  }, []);

  const reorder = async (from: number, to: number) => {
    if (savingRef.current || from === to || to < 0 || to >= monitors.length) return;
    const previous = monitors;
    const next = move(monitors, from, to);
    savingRef.current = true;
    setMonitors(next); // 楽観的更新
    setSaveState("saving"); setOrderError("");
    try {
      await api.reorderMonitors(next.map((monitor) => monitor.id));
      setSaveState("saved");
      window.clearTimeout(savedTimer.current);
      savedTimer.current = window.setTimeout(() => setSaveState("idle"), 2500);
    } catch (reason) {
      setMonitors(previous); // 失敗したら元の順へ戻す
      setSaveState("error");
      const stale = reason instanceof ApiError && reason.status === 409;
      setOrderError(`表示順を保存できませんでした。元の順に戻しました（${reason instanceof Error ? reason.message : String(reason)}）${stale ? "。モニター一覧が更新されているため、再読み込みしました" : ""}`);
    } finally {
      savingRef.current = false;
      load(); // サーバーの確定した順で再同期する
    }
  };

  const busy = saveState === "saving";
  const endDrag = () => { setDragId(null); setOverId(null); };

  return <main className="page monitors-page">
    <div className="page-head">
      <h1>モニター管理</h1>
      <div className="order-status-slot" aria-live="polite">
        {saveState === "saving" && <span className="order-status saving">保存中...</span>}
        {saveState === "saved" && <span className="order-status saved">保存済み</span>}
      </div>
      <button onClick={() => navigate("/monitors/new")}>＋ 新規モニター</button>
    </div>
    {error && <div className="alert error">{error}</div>}
    {orderError && <div className="alert error" role="alert">{orderError}</div>}
    <section className="panel">
      {loaded && monitors.length === 0 && <div className="records-empty">モニターがありません。「新規モニター」から追加してください。</div>}
      {monitors.length > 0 && <>
        <p className="muted order-hint">表示順（Dashboardのカードの並び）は、行をドラッグするか、↑↓ボタンで変更できます。変更は自動で保存されます。</p>
        <div className="records-table-wrap"><table className="records-table monitors-table">
          <thead><tr><th className="order-col" aria-label="並べ替え" /><th>モニター</th><th>状態</th><th>engine</th><th>model</th><th className="num">現在値</th><th>最終更新</th><th>順序</th><th>詳細</th></tr></thead>
          <tbody>
            {monitors.map((monitor, index) => {
              const status = combinedMonitorStatus(monitor);
              const name = monitor.display_name.trim();
              return <tr key={monitor.id} data-monitor-id={monitor.id} draggable={!busy}
                className={`${dragId === monitor.id ? "row-dragging" : ""}${overId === monitor.id && dragId !== monitor.id ? " row-drop-target" : ""}`}
                onDragStart={(event) => { setDragId(monitor.id); event.dataTransfer?.setData("text/plain", String(monitor.id)); if (event.dataTransfer) event.dataTransfer.effectAllowed = "move"; }}
                onDragOver={(event) => { if (dragId !== null) { event.preventDefault(); setOverId(monitor.id); } }}
                onDrop={(event) => { event.preventDefault(); const from = monitors.findIndex((item) => item.id === dragId); endDrag(); if (from >= 0) void reorder(from, index); }}
                onDragEnd={endDrag}>
                <td className="order-col"><span className="drag-handle" aria-hidden="true" title="ドラッグして並べ替え">≡</span></td>
                <td><strong>{name}</strong><small className="record-raw">ID {monitor.id}{monitor.location ? ` / ${monitor.location}` : ""}{monitor.enabled ? "" : " / 無効"}</small></td>
                <td><span className={`status-badge ${status}`}>{monitorStatusLabels[status]}</span></td>
                <td>{monitor.inference.engine}</td>
                <td className="cell-model" title={monitor.inference.model_id ?? undefined}>{monitor.inference.model_id ?? "--"}</td>
                <td className="num"><strong className="record-value">{monitor.current_value ?? "--"}</strong></td>
                <td className="nowrap">{formatDateTimeJst(monitor.last_updated)}</td>
                <td className="order-buttons">
                  <button type="button" className="secondary small-button" onClick={() => void reorder(index, index - 1)} disabled={busy || index === 0} aria-label={`${name} を上へ`}>↑</button>
                  <button type="button" className="secondary small-button" onClick={() => void reorder(index, index + 1)} disabled={busy || index === monitors.length - 1} aria-label={`${name} を下へ`}>↓</button>
                </td>
                <td><button type="button" className="secondary small-button" onClick={() => navigate(`/monitors/${monitor.id}`)} aria-label={`${name} の詳細`}>詳細へ</button></td>
              </tr>;
            })}
          </tbody>
        </table></div>
      </>}
    </section>
  </main>;
}
