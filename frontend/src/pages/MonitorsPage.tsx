import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Monitor } from "../types";
import { combinedMonitorStatus, monitorStatusLabels } from "../utils/monitorStatus";
import { formatDateTimeJst } from "../utils/datetime";

// モニター管理: 登録済みMonitorの一覧と、詳細(既存のMonitor Detail)・新規追加への導線。
export function MonitorsPage() {
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const navigate = useNavigate();
  useEffect(() => {
    const load = () => api.monitors().then((result) => { setMonitors(result.monitors); setError(""); }).catch((reason: Error) => setError(reason.message)).finally(() => setLoaded(true));
    load();
    const timer = window.setInterval(() => { if (!document.hidden) load(); }, 5000);
    return () => window.clearInterval(timer);
  }, []);
  return <main className="page monitors-page">
    <div className="page-head"><h1>モニター管理</h1><button onClick={() => navigate("/monitors/new")}>＋ 新規モニター</button></div>
    {error && <div className="alert error">{error}</div>}
    <section className="panel">
      {loaded && monitors.length === 0 && <div className="records-empty">モニターがありません。「新規モニター」から追加してください。</div>}
      {monitors.length > 0 && <div className="records-table-wrap"><table className="records-table monitors-table">
        <thead><tr><th>モニター</th><th>状態</th><th>engine</th><th>model</th><th className="num">現在値</th><th>最終更新</th><th>詳細</th></tr></thead>
        <tbody>
          {monitors.map((monitor) => {
            const status = combinedMonitorStatus(monitor);
            return <tr key={monitor.id} data-monitor-id={monitor.id}>
              <td><strong>{monitor.display_name.trim()}</strong><small className="record-raw">ID {monitor.id}{monitor.location ? ` / ${monitor.location}` : ""}{monitor.enabled ? "" : " / 無効"}</small></td>
              <td><span className={`status-badge ${status}`}>{monitorStatusLabels[status]}</span></td>
              <td>{monitor.inference.engine}</td>
              <td className="cell-model" title={monitor.inference.model_id ?? undefined}>{monitor.inference.model_id ?? "--"}</td>
              <td className="num"><strong className="record-value">{monitor.current_value ?? "--"}</strong></td>
              <td className="nowrap">{formatDateTimeJst(monitor.last_updated)}</td>
              <td><button type="button" className="secondary small-button" onClick={() => navigate(`/monitors/${monitor.id}`)} aria-label={`${monitor.display_name.trim()} の詳細`}>詳細へ</button></td>
            </tr>;
          })}
        </tbody>
      </table></div>}
    </section>
  </main>;
}
