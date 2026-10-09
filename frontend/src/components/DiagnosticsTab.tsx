import { useState } from "react";
import type { Monitor, ReadingDiagnostics, RuntimeDiagnostics } from "../types";
import { VideoPreview } from "./VideoPreview";
import { ReadingBaselinePanel } from "./ReadingBaselinePanel";
import { formatDateTimeJst } from "../utils/datetime";
import { inferenceErrorText } from "../utils/monitorDetail";
import type { Lightbox } from "./MonitoringTab";

type Props = {
  monitor: Monitor;
  readingDiagnostics: ReadingDiagnostics | null;
  runtimeDiagnostics: RuntimeDiagnostics | null;
  lightbox: Lightbox;
  onLightbox: (value: Lightbox) => void;
};

const dash = "--";
const percent = (value: number | null | undefined) => (value == null ? dash : `${(value * 100).toFixed(1)}%`);

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <tr><th scope="row">{label}</th><td>{children}</td></tr>;
}

// 「診断」タブ: 技術確認用。要点は上段のカードに並べ(2〜3列)、詳細(Pipeline診断・管理操作)はアコーディオンにして、ページを縦に長くしない。
// 項目名は日本語、実際の内部値(cpp_onnx / decrease_detected 等)は原文のまま表示する。
export function DiagnosticsTab({ monitor, readingDiagnostics, runtimeDiagnostics, lightbox, onLightbox }: Props) {
  const [adminOpen, setAdminOpen] = useState(false);
  const runtime = runtimeDiagnostics;
  const reading = readingDiagnostics;
  const confirmed = reading?.confirmed;
  const baseline = reading?.baseline ?? null;
  const conflict = reading?.conflict ?? null;
  const pipeline = runtime?.pipeline ?? null;
  return <div className="diag-layout">
    <div className="diag-grid">
      {/* 上段: 稼働状態 / 推論エンジン・モデル / 推論の状態 */}
      <section className="diag-card" aria-label="稼働状態">
        <h3>稼働状態</h3>
        <table className="diag-table"><tbody>
          <Row label="映像の状態">{runtime ? runtime.state : "--（停止中または取得不可）"}</Row>
          {runtime?.frame_width != null && <Row label="解像度">{runtime.frame_width}×{runtime.frame_height}</Row>}
          <Row label="映像取得">{runtime?.source_fps != null ? `${runtime.source_fps.toFixed(1)} fps` : dash}{runtime?.frame_age != null && ` / 最新フレーム ${runtime.frame_age.toFixed(1)}秒前`}{runtime?.stale && " / 停滞中"}</Row>
          {runtime && runtime.reconnect_count > 0 && <Row label="再接続">{runtime.reconnect_count}回</Row>}
          {runtime?.last_error && <Row label="映像エラー">{runtime.last_error}</Row>}
        </tbody></table>
      </section>

      <section className="diag-card" aria-label="推論エンジン / モデル">
        <h3>推論エンジン / モデル</h3>
        <table className="diag-table"><tbody>
          <Row label="推論方法">{monitor.inference.method}</Row>
          <Row label="推論エンジン">{monitor.inference.engine}</Row>
          <Row label="モデル">{monitor.inference.model_id ?? dash}</Row>
          <Row label="映像 / 推論FPS（設定）">{monitor.inference.video_fps} / {monitor.inference.inference_fps}</Row>
        </tbody></table>
      </section>

      <section className="diag-card" aria-label="推論の状態">
        <h3>推論の状態</h3>
        <table className="diag-table"><tbody>
          <Row label="推論エラー">{monitor.current_inference_error ? inferenceErrorText(monitor.current_inference_error, monitor.inference.engine) : "なし"}</Row>
          <Row label="過去のエラー履歴">{monitor.last_inference_error ? inferenceErrorText(monitor.last_inference_error, monitor.inference.engine) : "なし"}</Row>
          <Row label="最終更新">{monitor.last_updated ? formatDateTimeJst(monitor.last_updated) : dash}</Row>
          <Row label="推論処理時間">{dash}</Row>
        </tbody></table>
      </section>

      {/* 中段: 読取判定 / 読取基準値 / 基準値競合 */}
      <section className="diag-card" aria-label="読取判定">
        <h3>読取判定</h3>
        <table className="diag-table"><tbody>
          <Row label="最新推論値（Raw）">{confirmed?.raw_value ?? dash}{confirmed?.raw_confidence != null && `（信頼度 ${(confirmed.raw_confidence * 100).toFixed(0)}%）`}</Row>
          <Row label="読取判定"><code>{confirmed?.validation_status ?? dash}</code></Row>
          <Row label="一致回数">{confirmed ? `${confirmed.agreement_count} / ${confirmed.raw_count}` : dash}{reading && reading.consecutive_failures > 0 && `（連続失敗 ${reading.consecutive_failures}）`}</Row>
          <Row label="合意候補">{reading?.candidate ? `${reading.candidate.value}（一致 ${reading.candidate.agreement_count}）` : dash}</Row>
        </tbody></table>
      </section>

      <section className="diag-card" aria-label="読取基準値">
        <h3>読取基準値</h3>
        <table className="diag-table"><tbody>
          <Row label="基準値">{baseline?.value ?? monitor.reading_baseline?.value ?? dash}</Row>
          <Row label="確定日時">{baseline?.confirmed_at ? formatDateTimeJst(baseline.confirmed_at) : dash}</Row>
          <Row label="世代（epoch）">{baseline?.epoch ?? dash}</Row>
          <Row label="状態">{monitor.reading_baseline ? (monitor.reading_baseline.state === "pending_reset" ? "リセット済み" : "有効") : dash}</Row>
        </tbody></table>
      </section>

      <section className="diag-card" aria-label="基準値競合">
        <h3>基準値競合</h3>
        <table className="diag-table"><tbody>
          <Row label="競合">{conflict?.active ? "あり" : "なし"}</Row>
          <Row label="判定"><code>{conflict ? conflict.status : dash}</code></Row>
          <Row label="競合する読取">{conflict ? conflict.candidate : dash}</Row>
          <Row label="継続">{conflict ? `${conflict.count}回` : dash}</Row>
        </tbody></table>
      </section>

      {/* 下段: 推論入力画像 / 推論オーバーレイ(固定サイズの枠) */}
      {monitor.source && <section className="diag-card diag-image" aria-label="推論入力画像">
        <h3>推論入力画像</h3>
        <div className="diag-frame">
          {lightbox === "inferenceInput" ? <div className="no-video">拡大表示中</div> : <VideoPreview monitorId={monitor.id} inferenceInput onImageClick={() => onLightbox("inferenceInput")} />}
        </div>
        <p className="muted tiny">実際にモデルへ渡した画像（{pipeline?.roi_mode === "crop_context" ? "全体 → ROI周辺をcrop → 前処理" : "全体 → 前処理（ROIではcropしない）"}）</p>
      </section>}
      {monitor.source && <section className="diag-card diag-image" aria-label="推論オーバーレイ">
        <h3>推論オーバーレイ</h3>
        <div className="diag-frame">
          {lightbox === "overlay" ? <div className="no-video">拡大表示中</div> : <VideoPreview monitorId={monitor.id} overlay onImageClick={() => onLightbox("overlay")} />}
        </div>
        <p className="muted tiny">{pipeline ? `検出 ${pipeline.roi_filtered_detection_count}/${pipeline.raw_detection_count} 件（ROI内/全体）` : "検出bbox（推論値/確信度）を前処理後の画像に描画"}</p>
      </section>}
    </div>

    <div className="diag-accordions">
      {pipeline && <details className="diag-accordion">
        <summary>推論Pipeline診断（詳細）</summary>
        <table className="diag-table wide"><tbody>
          <Row label="フレーム">{pipeline.frame_width}×{pipeline.frame_height}</Row>
          <Row label="ROIモード">{pipeline.roi_mode ?? "--（OCR等はROIそのものをcrop）"}</Row>
          {pipeline.roi_mode === "crop_context" && <Row label="コンテキスト余白">{pipeline.context_margin}</Row>}
          <Row label="ROI（正規化）">x={pipeline.roi_normalized.x.toFixed(3)} y={pipeline.roi_normalized.y.toFixed(3)} w={pipeline.roi_normalized.width.toFixed(3)} h={pipeline.roi_normalized.height.toFixed(3)}</Row>
          <Row label="ROI（pixel）">{pipeline.roi_pixel.join(", ")}</Row>
          <Row label="推論crop（pixel）">{pipeline.inference_crop_pixel.join(", ")}</Row>
          <Row label="crop後の形状">{pipeline.crop_shape.join(" × ")}</Row>
          <Row label="前処理後の形状">{pipeline.preprocess_output_shape.join(" × ")}</Row>
          <Row label="モデル入力の形状">{pipeline.model_input_shape.join(" × ")}</Row>
          <Row label="検出数（ROI filter前）">{pipeline.raw_detection_count}</Row>
          <Row label="検出数（ROI filter後）">{pipeline.roi_filtered_detection_count}</Row>
          <Row label="推論エンジン / モデル">{pipeline.engine} / {pipeline.model_id ?? dash}</Row>
        </tbody></table>
      </details>}

      <details className="diag-accordion admin-operations" aria-label="管理操作" onToggle={(event) => setAdminOpen((event.currentTarget as HTMLDetailsElement).open)}>
        <summary>管理操作（読取基準値の再設定・リセット）</summary>
        <p className="muted tiny">通常の設定とは別の、監査履歴が残る操作です。</p>
        <ReadingBaselinePanel monitorId={monitor.id} currentValue={monitor.current_value} open={adminOpen} onToggleOpen={() => undefined} />
      </details>
    </div>
  </div>;
}
