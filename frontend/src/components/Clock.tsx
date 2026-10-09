import { useEffect, useState } from "react";

const PARTS = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });

/** 運用地域(JST / Asia/Tokyo)の時刻を「YYYY/MM/DD HH:mm:ss」(24時間表記)にする。ブラウザのタイムゾーン設定には依存しない。 */
export function formatJstClock(date: Date): string {
  const get = (type: string) => PARTS.formatToParts(date).find((p) => p.type === type)?.value ?? "";
  return `${get("year")}/${get("month")}/${get("day")} ${get("hour")}:${get("minute")}:${get("second")}`;
}

// 常時表示のリアルタイム時計(共通トップナビ)。Frontend側で1秒ごとに更新し、Backend APIは呼ばない。
export function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return <time className="app-nav-clock" dateTime={now.toISOString()} aria-label="現在時刻（JST）">{formatJstClock(now)}<span className="app-nav-clock-zone"> JST</span></time>;
}
