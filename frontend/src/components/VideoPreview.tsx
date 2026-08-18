import { useEffect, useState } from "react";
import { api } from "../api/client";

type Props = { monitorId: number; large?: boolean };

export function VideoPreview({ monitorId, large = false }: Props) {
  const [tick, setTick] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (large) return undefined;
    const timer = window.setInterval(() => setTick((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [large]);

  useEffect(() => setFailed(false), [monitorId, large]);

  if (failed) return <div className="no-video">映像を取得できません</div>;
  const source = large ? api.mjpg(monitorId) : `${api.preview(monitorId)}?t=${tick}`;
  return <img className="video-image" src={source} alt="ライブ映像" onError={() => setFailed(true)} />;
}
