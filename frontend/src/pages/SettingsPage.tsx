import { DataStorageSection } from "../components/DataStorageSection";

// システム設定。Phase 4では「データ保存」セクションのみ(他の設定はPhase 5以降/既存の画面にある)。
export function SettingsPage() {
  return <main className="page settings-page">
    <div className="page-head"><h1>システム設定</h1></div>
    <DataStorageSection />
  </main>;
}
