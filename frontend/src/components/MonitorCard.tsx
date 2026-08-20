import { useRef } from "react";
import type { Monitor } from "../types";
import { VideoPreview } from "./VideoPreview";
import { useInView, usePageVisible } from "../hooks/useVisibility";
import type { DashboardDisplayFps } from "../hooks/useDashboardSettings";

const labels: Record<string, string> = {
  running: "正常",
  reconnecting: "再接続中",
  error: "映像取得エラー",
  stopped: "停止中",
  connecting: "接続中",
  normal: "正常",
  warning: "要確認",
  connection_error: "通信異常",
  read_error: "読取不能",
};

type Props = { monitor: Monitor; onClick: () => void; displayFps: DashboardDisplayFps };

export function MonitorCard({ monitor, onClick, displayFps }: Props) {
  const cardRef = useRef<HTMLButtonElement>(null);
  const pageVisible = usePageVisible();
  const inView = useInView(cardRef);
  // タブが非表示、またはカードが画面外にスクロールされている間はpollingを止める
  // (新しいCamera/VideoCapture接続は発生しない。既存MonitorRuntimeの最新フレームを
  // JPEG pollingするだけのため、止めても映像取得自体には影響しない)。
  const paused = !pageVisible || !inView;
  const intervalMs = 1000 / displayFps;

  return (
    <button className="monitor-card" onClick={onClick} ref={cardRef}>
      <div className="card-head">
        <span className={`status-dot ${monitor.status}`} aria-hidden="true">●</span>
        <span>{monitor.display_name}</span>
        <small className={`status-badge ${monitor.status}`}>
          {labels[monitor.status] || monitor.status}
        </small>
      </div>
      <div className="preview-wrap">
        {monitor.source ? <VideoPreview monitorId={monitor.id} intervalMs={intervalMs} paused={paused} /> : <div className="no-video">映像ソース未設定</div>}
      </div>
      <div className="card-values">
        <div><small>現在値</small><strong>{monitor.current_value ?? "--"}</strong></div>
        <div><small>信頼度</small><strong>{monitor.confidence == null ? "--" : `${(monitor.confidence * 100).toFixed(1)}%`}</strong></div>
        <div><small>更新</small><strong>{monitor.last_updated ? new Date(monitor.last_updated).toLocaleTimeString() : "--"}</strong></div>
      </div>
    </button>
  );
}
