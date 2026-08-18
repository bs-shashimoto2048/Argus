import { useEffect, useState } from "react";
import { api } from "../api/client";

type Props = { monitorId: number; large?: boolean; overlay?: boolean };

export function VideoPreview({ monitorId, large = false, overlay = false }: Props) {
  const [tick, setTick] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (large && !overlay) return undefined;
    const timer = window.setInterval(() => setTick((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [large, overlay]);

  useEffect(() => setFailed(false), [monitorId, large, overlay]);

  if (failed) return <div className="no-video">映像を取得できません</div>;
  const base = overlay ? api.overlay(monitorId) : large ? api.mjpg(monitorId) : api.preview(monitorId);
  const source = large && !overlay ? base : `${base}?t=${tick}`;
  return <img className="video-image" src={source} alt="ライブ映像" onError={() => setFailed(true)} />;
}
