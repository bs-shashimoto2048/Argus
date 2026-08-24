import { useEffect, useState } from "react";
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

  useEffect(() => {
    if (large && !overlay && !inferenceInput) return undefined;
    if (paused) return undefined;
    const timer = window.setInterval(() => setTick((value) => value + 1), intervalMs);
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
      onError={() => setFailed(true)}
      onClick={onImageClick}
    />
  );
}
