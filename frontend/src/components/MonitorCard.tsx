import type { Monitor } from "../types";
import { VideoPreview } from "./VideoPreview";

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

type Props = { monitor: Monitor; onClick: () => void };

export function MonitorCard({ monitor, onClick }: Props) {
  return (
    <button className="monitor-card" onClick={onClick}>
      <div className="card-head">
        <span className={`status-dot ${monitor.status}`} aria-hidden="true">●</span>
        <span>{monitor.display_name}</span>
        <small className={`status-badge ${monitor.status}`}>
          {labels[monitor.status] || monitor.status}
        </small>
      </div>
      <div className="preview-wrap">
        {monitor.source ? <VideoPreview monitorId={monitor.id} /> : <div className="no-video">映像ソース未設定</div>}
      </div>
      <div className="card-values">
        <div><small>現在値</small><strong>{monitor.current_value ?? "--"}</strong></div>
        <div><small>信頼度</small><strong>{monitor.confidence == null ? "--" : `${(monitor.confidence * 100).toFixed(1)}%`}</strong></div>
        <div><small>更新</small><strong>{monitor.last_updated ? new Date(monitor.last_updated).toLocaleTimeString() : "--"}</strong></div>
      </div>
    </button>
  );
}
