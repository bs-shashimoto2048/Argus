import type { Monitor, ReadingDiagnostics, RuntimeDiagnostics } from "../types";
import { VideoPreview } from "./VideoPreview";
import { formatDateTimeJst } from "../utils/datetime";
import { combinedMonitorStatus, monitorStatusLabels } from "../utils/monitorStatus";
import { conflictMessage } from "../utils/readingFormat";
import { currentValueText, formatDiff, inferenceErrorText } from "../utils/monitorDetail";

export type VideoTab = "video" | "overlay";
export type Lightbox = "video" | "overlay" | "inferenceInput" | null;

type Props = {
  monitor: Monitor;
  rawInferenceValue: string | null;
  rawDiffersFromConfirmed: boolean;
  modelMissing: boolean;
  readingDiagnostics: ReadingDiagnostics | null;
  runtimeDiagnostics: RuntimeDiagnostics | null;
  videoTab: VideoTab;
  onVideoTab: (tab: VideoTab) => void;
  lightbox: Lightbox;
  onLightbox: (value: Lightbox) => void;
};

const percent = (value: number | null | undefined) => (value == null ? "--" : `${(value * 100).toFixed(1)}%`);

// 「監視」タブ: 日常監視用のコンパクトな表示。左に映像(高さに上限)、右に現在値と読取の要点。
// 警告(モデル未設定/基準値競合/推論エラー)は右カラムの最下部に置き、上のセクションの位置を動かさない。
export function MonitoringTab({ monitor, rawInferenceValue, rawDiffersFromConfirmed, modelMissing, readingDiagnostics, runtimeDiagnostics, videoTab, onVideoTab, lightbox, onLightbox }: Props) {
  const status = combinedMonitorStatus(monitor);
  const baseline = monitor.reading_baseline;
  const reading = monitor.inference.reading;
  return <div className="mon-layout">
    <div className="panel video-panel primary-video compact">
      <div className="video-tabs compact" role="tablist" aria-label="映像の種類">
        <button type="button" role="tab" aria-selected={videoTab === "video"} className={`video-tab${videoTab === "video" ? " active" : ""}`} onClick={() => onVideoTab("video")}>モニター映像</button>
        <button type="button" role="tab" aria-selected={videoTab === "overlay"} className={`video-tab${videoTab === "overlay" ? " active" : ""}`} onClick={() => onVideoTab("overlay")} disabled={!monitor.source}>推論オーバーレイ</button>
      </div>
      {/* 映像の枠は固定の縦横比(16:9)・高さの上限つき。切替・読込の前後でも高さが変わらない。 */}
      <div className="video-frame">
        {!monitor.source ? (
          <div className="no-video large">映像ソースを設定してください</div>
        ) : lightbox === videoTab ? (
          <div className="no-video large">拡大表示中（×で閉じると再表示されます）</div>
        ) : videoTab === "video" ? (
          <VideoPreview monitorId={monitor.id} large onImageClick={() => onLightbox("video")} />
        ) : (
          <VideoPreview monitorId={monitor.id} overlay onImageClick={() => onLightbox("overlay")} />
        )}
      </div>
      {/* 凡例の欄は常に確保する(推論オーバーレイの切替で高さが変わらない)。 */}
      <div className="overlay-legend-slot">
        {videoTab === "overlay" && monitor.source && <div className="overlay-legend compact">
          {runtimeDiagnostics?.pipeline?.roi_mode && <span><i className="legend-swatch legend-roi" />ユーザー指定ROI</span>}
          <span><i className="legend-swatch legend-detection" />検出bbox（推論値/確信度）</span>
          {runtimeDiagnostics?.pipeline && (runtimeDiagnostics.pipeline.engine === "ultralytics" || runtimeDiagnostics.pipeline.engine === "cpp_onnx")
            ? <span>検出 {runtimeDiagnostics.pipeline.roi_filtered_detection_count}/{runtimeDiagnostics.pipeline.raw_detection_count} 件（ROI内/全体）</span>
            : runtimeDiagnostics?.pipeline && <span>このエンジンは文字ごとの位置を検出しないため、bboxは表示されません</span>}
        </div>}
      </div>
    </div>

    <div className="mon-info">
      <div className="panel mon-current" aria-live="polite">
        <div className="mon-current-main">
          <div className="mon-current-value"><small>現在値（確定）</small><strong>{currentValueText(monitor)}</strong></div>
          <div className="mon-item"><small>信頼度</small><strong>{percent(monitor.confidence)}</strong></div>
          <div className="mon-item"><small>状態</small><span className={`status-text ${status}`}>● {monitorStatusLabels[status]}</span></div>
        </div>
        <div className="mon-previous">
          <div className="mon-item"><small>前回値</small><strong>{monitor.previous_value ?? "--"}</strong></div>
          <div className="mon-item"><small>前回の信頼度</small><strong>{percent(monitor.previous_confidence)}</strong></div>
          <div className="mon-item"><small>確定日時</small><strong>{monitor.previous_confirmed_at ? formatDateTimeJst(monitor.previous_confirmed_at) : "--"}</strong></div>
          <div className="mon-item"><small>差分</small><strong>{formatDiff(monitor.current_value, monitor.previous_value)}</strong></div>
        </div>
      </div>

      <div className="monitoring-summary" aria-label="読取の詳細">
        <div className={rawDiffersFromConfirmed ? "raw-pending" : undefined}><small>最新推論値（未確定）</small><strong>{rawInferenceValue ?? readingDiagnostics?.confirmed.raw_value ?? "--"}</strong></div>
        <div><small>推論エンジン</small><strong>{monitor.inference.engine}</strong></div>
        <div><small>モデル</small><strong title={monitor.inference.model_id ?? undefined}>{monitor.inference.model_id ?? "--"}</strong></div>
        <div><small>最終更新</small><strong>{monitor.last_updated ? formatDateTimeJst(monitor.last_updated) : "--"}</strong></div>
        <div><small>読取基準値</small><strong>{baseline ? `${baseline.value ?? "--"}（${baseline.state === "pending_reset" ? "リセット済み" : "有効"}）` : "--"}</strong></div>
        <div><small>基準値競合</small><strong className={baseline?.conflict ? "conflict-yes" : undefined}>{baseline?.conflict ? `あり（${baseline.conflict_candidate ?? "--"}）` : "なし"}</strong></div>
      </div>

      <details className="mon-note">
        <summary>現在値の見方</summary>
        <p className="muted">
          「現在値（確定）」は読取安定化により確定した値です（直近{reading.window_size}回中{reading.required_matches}回以上一致で更新）。
          一致が取れていない間は直前の確定値を保持するため、最新の推論結果と一時的に異なる場合があります。「前回値」は直前に確定していた値（推論の途中経過ではありません）。
        </p>
      </details>

      {/* 警告は最下部へ(出ても上の要点の位置が動かない) */}
      {modelMissing && <div className="alert error compact">モデルが設定されていません。「設定」タブの「推論エンジン / モデル」でモデルを選択してください。</div>}
      {baseline?.conflict && (
        <div className="alert warning compact">⚠ {conflictMessage(baseline.conflict_status, baseline.value, baseline.conflict_candidate, baseline.conflict_seconds)}。実メーターを確認し、必要なら「診断」タブの「管理操作」から読取基準値を再設定してください。</div>
      )}
      {monitor.current_inference_error && !modelMissing && <div className="alert error compact">{inferenceErrorText(monitor.current_inference_error, monitor.inference.engine)}</div>}
      {!monitor.current_inference_error && monitor.last_inference_error && !modelMissing && (
        <p className="muted status-note">直近のエラー履歴（現在は解消済み）: {inferenceErrorText(monitor.last_inference_error, monitor.inference.engine)}</p>
      )}
    </div>
  </div>;
}
