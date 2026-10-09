import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";

// intervalMs/pausedはDashboard表示専用の負荷制御に使う(Detail画面のPreview FPS・
// 推論FPSには一切影響しない)。省略時は既存どおり1000ms固定・常時pollingで、
// Detail画面(MonitorDetailPage)の挙動を変えない。
// onImageClickはMonitor Detailの拡大表示(lightbox)用のUIフックで、取得頻度・
// APIには一切影響しない(クリック時にコールバックを呼ぶだけ)。
type Props = { monitorId: number; large?: boolean; overlay?: boolean; inferenceInput?: boolean; intervalMs?: number; paused?: boolean; onImageClick?: () => void };

export function VideoPreview({ monitorId, large = false, overlay = false, inferenceInput = false, intervalMs = 1000, paused = false, onImageClick }: Props) {
  const [tick, setTick] = useState(0);
  const [failed, setFailed] = useState(false);
  // 前の画像の取得が終わっていない間は、次のリクエストを出さない(高いFPSでも未完了のリクエストを積み上げず、
  // src差し替えによる取得の取り消し(画像が更新されない)も起こさない)。
  const loadingSince = useRef(0); // 取得開始時刻(0=待ちなし)。応答が無いまま5秒たったら次を出す

  useEffect(() => {
    if (large && !overlay && !inferenceInput) return undefined;
    if (paused) return undefined;
    loadingSince.current = 0;
    const timer = window.setInterval(() => {
      if (loadingSince.current && Date.now() - loadingSince.current < 5000) return;
      loadingSince.current = Date.now();
      setTick((value) => value + 1);
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [large, overlay, inferenceInput, intervalMs, paused]);

  useEffect(() => setFailed(false), [monitorId, large, overlay, inferenceInput]);

  if (failed) return <div className="no-video">{inferenceInput ? "推論入力画像を取得できません" : "映像を取得できません"}</div>;
  const base = inferenceInput ? api.inferenceInput(monitorId) : overlay ? api.overlay(monitorId) : large ? api.mjpg(monitorId) : api.preview(monitorId);
  const source = large && !overlay && !inferenceInput ? base : `${base}?t=${tick}`;
  return (
    <img
      className={`video-image${onImageClick ? " video-image-clickable" : ""}`}
      src={source}
      alt="ライブ映像"
      onLoad={() => { loadingSince.current = 0; }}
      onError={() => { loadingSince.current = 0; setFailed(true); }}
      onClick={onImageClick}
    />
  );
}
