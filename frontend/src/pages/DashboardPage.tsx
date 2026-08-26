import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Monitor } from "../types";
import { Brand } from "../components/Brand";
import { MonitorCard } from "../components/MonitorCard";
import { DashboardSettingsModal } from "../components/DashboardSettingsModal";
import { useDashboardSettings } from "../hooks/useDashboardSettings";
import { combinedMonitorStatus } from "../utils/monitorStatus";

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

  // Issue #29: monitor.status(映像Runtime接続状態)とmonitor.inference_status(読取・推論状態)を
  // 合成した表示状態で集計する(Monitor Card/Detailと同じルール)。合成前のmonitor.statusだけを
  // 見ると、映像がrunning中でも読取がread_error/low_confidenceであることを見落とす。
  const counts = useMemo(() => {
    const displayStatuses = monitors.map(combinedMonitorStatus);
    return {
      normal: displayStatuses.filter((status) => status === "normal").length,
      warning: displayStatuses.filter((status) => status === "warning").length,
      error: displayStatuses.filter((status) => status === "read_error" || status === "error").length,
    };
  }, [monitors]);

  return <main className="page">
    <header className="topbar">
      {/* Issue #25: Dashboardではキャラクターアイコンを非表示にする(他画面のBrandは変更なし)。 */}
      <Brand showIcon={false} />
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
