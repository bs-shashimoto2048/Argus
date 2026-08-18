import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Monitor } from "../types";
import { Brand } from "../components/Brand";
import { MonitorCard } from "../components/MonitorCard";

export function DashboardPage() {
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const load = () => api.monitors().then((result) => setMonitors(result.monitors)).catch((reason: Error) => setError(reason.message));
  useEffect(() => { load(); const timer = window.setInterval(load, 5000); return () => clearInterval(timer); }, []);
  const counts = useMemo(() => ({ normal: monitors.filter((m) => ["normal", "running"].includes(m.status)).length, warning: monitors.filter((m) => m.status === "warning").length, error: monitors.filter((m) => ["connection_error", "read_error", "error"].includes(m.status)).length }), [monitors]);
  return <main className="page"><header className="topbar"><Brand /><span className="live-badge">● Monitoring</span></header><div className="summary"><span>正常 <b>{counts.normal}</b></span><span>要確認 <b>{counts.warning}</b></span><span>通信異常 <b>{counts.error}</b></span><button onClick={() => navigate("/monitors/new")}>＋ モニター追加</button></div>{error && <div className="alert error">{error}</div>}<div className="monitor-grid">{monitors.map((monitor) => <MonitorCard key={monitor.id} monitor={monitor} onClick={() => navigate(`/monitors/${monitor.id}`)} />)}{monitors.length === 0 && <div className="empty"><h2>モニターがありません</h2><p>最初のモニターを追加してください。</p><button onClick={() => navigate("/monitors/new")}>モニター追加</button></div>}</div></main>;
}
