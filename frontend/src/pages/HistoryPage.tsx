import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Monitor } from "../types";
import { RecordsSection } from "../components/RecordsSection";

// 履歴・データ画面: Dashboard下部の計測履歴と同じ一覧に、Excel出力を加えたもの。
export function HistoryPage() {
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  useEffect(() => { api.monitors().then((result) => setMonitors(result.monitors)).catch(() => setMonitors([])); }, []);
  return <main className="page history-page">
    <div className="page-head"><h1>履歴・データ</h1></div>
    <RecordsSection monitors={monitors} pageSize={50} title="1時間ごとの計測履歴" description="reading_records（1 Monitor 1時間 1件の正式な記録）。終了日はその日の終わりまでを含みます。" showExport size="tall" />
  </main>;
}
