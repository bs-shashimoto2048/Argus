import { useEffect, useState } from "react";
import { api } from "../api/client";

// intervalMs/pausedはDashboard表示専用の負荷制御に使う(Detail画面のPreview FPS・
// 推論FPSには一切影響しない)。省略時は既存どおり1000ms固定・常時pollingで、
// Detail画面(MonitorDetailPage)の挙動を変えない。
type Props = { monitorId: number; large?: boolean; overlay?: boolean; intervalMs?: number; paused?: boolean };

export function VideoPreview({ monitorId, large = false, overlay = false, intervalMs = 1000, paused = false }: Props) {
  const [tick, setTick] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (large && !overlay) return undefined;
    if (paused) return undefined;
    const timer = window.setInterval(() => setTick((value) => value + 1), intervalMs);
    return () => window.clearInterval(timer);
  }, [large, overlay, intervalMs, paused]);

  useEffect(() => setFailed(false), [monitorId, large, overlay]);

  if (failed) return <div className="no-video">映像を取得できません</div>;
  const base = overlay ? api.overlay(monitorId) : large ? api.mjpg(monitorId) : api.preview(monitorId);
  const source = large && !overlay ? base : `${base}?t=${tick}`;
  return <img className="video-image" src={source} alt="ライブ映像" onError={() => setFailed(true)} />;
}
