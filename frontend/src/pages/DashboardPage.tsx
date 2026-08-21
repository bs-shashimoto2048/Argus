import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Monitor } from "../types";
import { Brand } from "../components/Brand";
import { MonitorCard } from "../components/MonitorCard";
import { DashboardSettingsModal } from "../components/DashboardSettingsModal";
import { useDashboardSettings } from "../hooks/useDashboardSettings";

export function DashboardPage() {
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [error, setError] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const navigate = useNavigate();
  const { settings, update } = useDashboardSettings();

  const load = () => api.monitors().then((result) => setMonitors(result.monitors)).catch((reason: Error) => setError(reason.message));
  useEffect(() => {
    load();
    // タブが非表示の間はモニター一覧の定期取得も止める(Dashboard全体の負荷を下げる)。
    const timer = window.setInterval(() => { if (!document.hidden) load(); }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const counts = useMemo(() => ({
    normal: monitors.filter((m) => ["normal", "running"].includes(m.status)).length,
    warning: monitors.filter((m) => m.status === "warning").length,
    error: monitors.filter((m) => ["connection_error", "read_error", "error"].includes(m.status)).length,
  }), [monitors]);

  return <main className="page">
    <header className="topbar">
      <Brand />
      <div className="topbar-actions">
        <span className="live-badge">● Monitoring</span>
        <span className="fps-badge" title="Dashboardのプレビュー表示FPS(video_fps/inference_fpsとは無関係)">表示 {settings.displayFps} FPS</span>
        <button className="icon-button" aria-label="Dashboard設定" title="Dashboard設定" onClick={() => setShowSettings(true)}>⚙</button>
      </div>
    </header>
    <div className="summary">
      <span>正常 <b>{counts.normal}</b></span>
      <span>要確認 <b>{counts.warning}</b></span>
      <span>通信異常 <b>{counts.error}</b></span>
      <button onClick={() => navigate("/monitors/new")}>＋ モニター追加</button>
    </div>
    {error && <div className="alert error">{error}</div>}
    <div className="monitor-grid">
      {monitors.map((monitor) => <MonitorCard key={monitor.id} monitor={monitor} displayFps={settings.displayFps} onClick={() => navigate(`/monitors/${monitor.id}`)} />)}
      {monitors.length === 0 && <div className="empty"><h2>モニターがありません</h2><p>最初のモニターを追加してください。</p><button onClick={() => navigate("/monitors/new")}>モニター追加</button></div>}
    </div>
    {showSettings && <DashboardSettingsModal settings={settings} onChange={update} onClose={() => setShowSettings(false)} />}
  </main>;
}
