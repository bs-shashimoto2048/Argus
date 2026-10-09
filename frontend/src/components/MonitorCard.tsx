import { useRef } from "react";
import type { Monitor, ReadingRecord } from "../types";
import { VideoPreview } from "./VideoPreview";
import { useInView, usePageVisible } from "../hooks/useVisibility";
import type { DashboardDisplayFps } from "../hooks/useDashboardSettings";
import { formatTimeJst } from "../utils/datetime";
import { combinedMonitorStatus, monitorStatusLabels } from "../utils/monitorStatus";
import { formatDuration } from "../utils/readingFormat";
import { formatRecordTime } from "../utils/records";

const fetchStateLabels: Record<string, string> = { running: "取得中", connecting: "接続中", reconnecting: "再接続中", stopped: "停止中", error: "取得エラー" };

// latestRecord: このMonitorの最新の1時間記録(carried_forwardの補助表示用)。無ければ補助表示なし。
type Props = { monitor: Monitor; onClick: () => void; displayFps: DashboardDisplayFps; latestRecord?: ReadingRecord | null };

export function MonitorCard({ monitor, onClick, displayFps, latestRecord }: Props) {
  const cardRef = useRef<HTMLButtonElement>(null);
  const pageVisible = usePageVisible();
  const inView = useInView(cardRef);
  // タブが非表示、またはカードが画面外にスクロールされている間はpollingを止める
  // (新しいCamera/VideoCapture接続は発生しない。既存MonitorRuntimeの最新フレームを
  // JPEG pollingするだけのため、止めても映像取得自体には影響しない)。
  const paused = !pageVisible || !inView;
  const intervalMs = 1000 / displayFps;
  // Issue #29: monitor.status(映像Runtime接続状態)とmonitor.inference_status(読取・推論状態)は
  // 互いに独立した値のため、バッジ表示用に1つへ合成する(Dashboard/Detail共通のルール)。
  const displayStatus = combinedMonitorStatus(monitor);

  return (
    <button className="monitor-card" onClick={onClick} ref={cardRef}>
      <div className="card-head">
        <span className={`status-dot ${displayStatus}`} aria-hidden="true">●</span>
        <span className="card-title">{monitor.display_name.trim()}</span>
        <small className={`status-badge ${displayStatus}`}>
          {monitorStatusLabels[displayStatus]}
        </small>
      </div>
      <div className="preview-wrap">
        {monitor.source ? <VideoPreview monitorId={monitor.id} intervalMs={intervalMs} paused={paused} /> : <div className="no-video">映像ソース未設定</div>}
      </div>
      {/* Issue #25: 日常監視で数値を短時間で読み取れるよう、3項目の視覚的な優先順位を
          明確にする(現在値を最も強調、信頼度はstatus連動色、更新時刻は控えめだが
          明瞭に)。status判定ロジック自体は変更せず、合成済みのdisplayStatusを
          表示色の切替にのみ使う。 */}
      <div className="card-values">
        <div className="card-value-primary"><small>現在値</small><strong>{monitor.current_value ?? "--"}</strong></div>
        <div className={`card-value-confidence status-${displayStatus}`}><small>信頼度</small><strong>{monitor.confidence == null ? "--" : `${(monitor.confidence * 100).toFixed(1)}%`}</strong></div>
        <div className="card-value-updated"><small>更新</small><strong>{formatTimeJst(monitor.last_updated)}</strong></div>
      </div>
      <div className="card-meta"><span>取得状態：{fetchStateLabels[monitor.status] ?? monitor.status}</span></div>
      {/* バッジの有無でカード高さが変わらないよう、通知欄は常に一定の高さを確保する。 */}
      <div className="card-notices">
        {/* 直近の1時間記録が前回確定値の保持(Raw棄却中)だった場合の補助表示。大きな現在値は常に正式値(先頭0除去後)。 */}
        {latestRecord?.value_source === "carried_forward" && (
          <div className="carried-badge" role="status">前回確定値を保持<small>{formatRecordTime(latestRecord.recorded_at)}の記録 / Raw {latestRecord.raw_value ?? "--"} / {latestRecord.validation_status ?? "--"}</small></div>
        )}
        {/* Issue #40: 合意候補がbaselineと矛盾して一定時間続いている(固着の疑い)場合の警告バッジ。 */}
        {monitor.reading_baseline?.conflict && (
          <div className="baseline-conflict-badge" role="status">⚠ 基準値 {monitor.reading_baseline.value ?? "--"} と矛盾する読取 {monitor.reading_baseline.conflict_candidate ?? "--"}（{formatDuration(monitor.reading_baseline.conflict_seconds)}）</div>
        )}
      </div>
    </button>
  );
}
