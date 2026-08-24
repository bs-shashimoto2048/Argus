import { useRef } from "react";
import type { Monitor } from "../types";
import { VideoPreview } from "./VideoPreview";
import { useInView, usePageVisible } from "../hooks/useVisibility";
import type { DashboardDisplayFps } from "../hooks/useDashboardSettings";
import { formatTimeJst } from "../utils/datetime";

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
      {/* Issue #25: 日常監視で数値を短時間で読み取れるよう、3項目の視覚的な優先順位を
          明確にする(現在値を最も強調、信頼度はstatus連動色、更新時刻は控えめだが
          明瞭に)。status判定ロジック自体は変更せず、既存のmonitor.statusを
          表示色の切替にのみ使う。 */}
      <div className="card-values">
        <div className="card-value-primary"><small>現在値</small><strong>{monitor.current_value ?? "--"}</strong></div>
        <div className={`card-value-confidence status-${monitor.status}`}><small>信頼度</small><strong>{monitor.confidence == null ? "--" : `${(monitor.confidence * 100).toFixed(1)}%`}</strong></div>
        <div className="card-value-updated"><small>更新</small><strong>{formatTimeJst(monitor.last_updated)}</strong></div>
      </div>
    </button>
  );
}
