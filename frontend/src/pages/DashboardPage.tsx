import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Monitor, ReadingRecord } from "../types";
import { MonitorCard } from "../components/MonitorCard";
import { RecordsSection } from "../components/RecordsSection";
import { TrendChart } from "../components/TrendChart";
import type { RecordFilterValue } from "../components/RecordFilters";
import { DashboardSettingsModal } from "../components/DashboardSettingsModal";
import { useDashboardSettings } from "../hooks/useDashboardSettings";
import { combinedMonitorStatus } from "../utils/monitorStatus";
import { addDays, startOfDayJst, todayJst } from "../utils/records";

/** Monitorカード領域で、実際に見えているカードの数(領域内に半分以上入っているカード)。レイアウトを測れない環境では先頭の1行ぶん。 */
export function countVisibleCards(region: HTMLElement, total: number): number {
  const box = region.getBoundingClientRect();
  if (box.height === 0) return Math.min(3, total);
  const cards = [...region.querySelectorAll<HTMLElement>(".monitor-card")];
  const visible = cards.filter((card) => { const r = card.getBoundingClientRect(); const overlap = Math.min(r.bottom, box.bottom) - Math.max(r.top, box.top); return overlap >= r.height / 2; }).length;
  return Math.max(1, Math.min(visible, total));
}

export function DashboardPage() {
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [trendReload, setTrendReload] = useState(0);
  const [latestRecords, setLatestRecords] = useState<Record<number, ReadingRecord>>({});
  const [error, setError] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  // 計測履歴とグラフで共有する条件(Monitor・期間)。コントロールは履歴ヘッダーにあり、グラフも同じ条件で描く。
  const [filter, setFilter] = useState<RecordFilterValue>({ monitorIds: [], period: { mode: "today", startDate: todayJst(), endDate: todayJst() } });
  const [visibleCards, setVisibleCards] = useState(3);
  const regionRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const { settings, update } = useDashboardSettings();

  const load = () => api.monitors().then((result) => setMonitors(result.monitors)).catch((reason: Error) => setError(reason.message));
  // 各Monitorの最新の1時間記録(carried_forwardの補助表示用)。直近3日分の新しい順から、Monitorごとに先頭を採用する。
  const loadLatestRecords = () => {
    const today = todayJst();
    return api.records({ monitorIds: [], from: startOfDayJst(addDays(today, -2)), to: startOfDayJst(addDays(today, 1)), limit: 100, offset: 0 })
      .then((page) => {
        const latest: Record<number, ReadingRecord> = {};
        for (const record of page.items) if (!(record.monitor_id in latest)) latest[record.monitor_id] = record;
        setLatestRecords(latest);
      })
      .catch(() => { /* 補助表示なので、取得できなくてもDashboardは動かす */ });
  };
  useEffect(() => {
    load();
    loadLatestRecords();
    // タブが非表示の間はモニター一覧の定期取得も止める(Dashboard全体の負荷を下げる)。
    const timer = window.setInterval(() => { if (!document.hidden) load(); }, 5000);
    const recordsTimer = window.setInterval(() => { if (!document.hidden) loadLatestRecords(); }, 60000);
    return () => { window.clearInterval(timer); window.clearInterval(recordsTimer); };
  }, []);

  // Issue #29: monitor.status(映像Runtime接続状態)とmonitor.inference_status(読取・推論状態)を
  // 合成した表示状態で集計する(Monitor Card/Detailと同じルール)。
  const counts = useMemo(() => {
    const displayStatuses = monitors.map(combinedMonitorStatus);
    return {
      normal: displayStatuses.filter((status) => status === "normal").length,
      warning: displayStatuses.filter((status) => status === "warning").length,
      error: displayStatuses.filter((status) => status === "read_error" || status === "error").length,
    };
  }, [monitors]);

  const updateVisible = useCallback(() => { if (regionRef.current) setVisibleCards(countVisibleCards(regionRef.current, monitors.length)); }, [monitors.length]);
  useLayoutEffect(() => {
    updateVisible();
    window.addEventListener("resize", updateVisible);
    return () => window.removeEventListener("resize", updateVisible);
  }, [updateVisible]);

  const running = monitors.filter((monitor) => monitor.status === "running").length;
  return <main className="page dashboard-page">
    {/* ページタイトルは置かない(上部ナビゲーションに「ダッシュボード」があるため)。 */}
    <div className="dashboard-toolbar">
      <div className="summary-chips" aria-label="状態サマリー">
        <span className="summary-chip tone-ok"><span className="chip-label">正常</span><strong data-testid="count-normal">{counts.normal}</strong></span>
        <span className="summary-chip tone-caution"><span className="chip-label">要確認</span><strong data-testid="count-warning">{counts.warning}</strong></span>
        <span className="summary-chip tone-danger"><span className="chip-label">通信異常</span><strong data-testid="count-error">{counts.error}</strong></span>
      </div>
      {monitors.length > 3 && <span className="card-count-hint" aria-live="polite" title="カード領域を縦にスクロールすると、残りのモニターを表示します">{visibleCards} / {monitors.length}台表示<small>（スクロールで続きを表示）</small></span>}
      {/* [モニター追加] と Monitoring表示は同じ操作グループ(同じ高さ・角丸・枠線のトーン)として横並びにする。 */}
      <div className="action-group" role="group" aria-label="ダッシュボード操作">
        <button className="action-button" onClick={() => navigate("/monitors/new")}><span className="btn-plus">＋</span> モニター追加</button>
        <div className="monitoring-control" aria-label="Monitoring">
          <span className={`monitoring-status${running > 0 ? " live" : ""}`} title={`稼働中 ${running} / ${monitors.length}`}><i aria-hidden="true">●</i>Monitoring</span>
          <span className="monitoring-fps" title="Dashboardのプレビュー表示FPS(video_fps/inference_fpsとは無関係)">{settings.displayFps} FPS</span>
          <button className="monitoring-gear" aria-label="Dashboard設定" title="Dashboard設定" onClick={() => setShowSettings(true)}>⚙</button>
        </div>
      </div>
    </div>
    {error && <div className="alert error">{error}</div>}
    {/* 最大3列。4台以上はこの領域の中だけが縦スクロールする(ページは伸びない)。表示順(display_order)のまま並べ、異常を前へ出さない。 */}
    <div className="monitor-region" ref={regionRef} onScroll={updateVisible} data-testid="monitor-region">
    <div className="monitor-grid">
      {monitors.map((monitor) => <MonitorCard key={monitor.id} monitor={monitor} displayFps={settings.displayFps} latestRecord={latestRecords[monitor.id]} onClick={() => navigate(`/monitors/${monitor.id}`)} />)}
      {monitors.length === 0 && <div className="empty"><h2>モニターがありません</h2><p>最初のモニターを追加してください。</p><button onClick={() => navigate("/monitors/new")}>モニター追加</button></div>}
    </div>
    </div>
    <TrendChart monitors={monitors} filter={filter} refreshMs={60000} reloadToken={trendReload} />
    <RecordsSection monitors={monitors} title="計測履歴" description="1時間ごとに自動記録（毎時00分）。詳細な検索・Excel出力は「履歴・データ」から行えます。" refreshMs={60000} filter={filter} onFilterChange={setFilter} showExportXl onRecordCorrected={() => setTrendReload((n) => n + 1)} />
    {showSettings && <DashboardSettingsModal settings={settings} onChange={update} onClose={() => setShowSettings(false)} />}
  </main>;
}
