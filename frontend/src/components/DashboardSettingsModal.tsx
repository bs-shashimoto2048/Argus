import { DASHBOARD_DISPLAY_FPS_DEFAULT, DASHBOARD_DISPLAY_FPS_OPTIONS, DASHBOARD_HIGH_FPS, DASHBOARD_RELOAD_OPTIONS } from "../hooks/useDashboardSettings";
import type { DashboardDisplayFps, DashboardReloadMinutes, DashboardSettings } from "../hooks/useDashboardSettings";
import { CsvExportSettingsPanel } from "./CsvExportSettingsPanel";

type Props = {
  settings: DashboardSettings;
  onChange: (patch: Partial<DashboardSettings>) => void;
  onClose: () => void;
};

// 将来の拡張を見据え「表示設定」セクションを設ける。今回はDashboard表示FPSのみ配置する。
export function DashboardSettingsModal({ settings, onChange, onClose }: Props) {
  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Dashboard設定">
    <div className="modal dashboard-settings-modal">
      <div className="modal-head"><h2>Dashboard設定</h2><button className="icon-button" onClick={onClose}>×</button></div>
      <section className="panel">
        <h3>表示設定</h3>
        <label>
          Dashboard表示FPS
          <select
            value={settings.displayFps}
            onChange={(event) => onChange({ displayFps: Number(event.target.value) as DashboardDisplayFps })}
          >
            {DASHBOARD_DISPLAY_FPS_OPTIONS.map((fps) => <option key={fps} value={fps}>{fps} FPS{fps === DASHBOARD_DISPLAY_FPS_DEFAULT ? "（推奨）" : ""}</option>)}
          </select>
        </label>
        {settings.displayFps >= DASHBOARD_HIGH_FPS && <p className="muted small fps-warning" role="note">高いFPSでは、Monitor台数やネットワーク環境によりブラウザ・通信負荷が増加します。</p>}
        <p className="muted">
          Dashboard一覧に表示するプレビュー映像の更新頻度です。既存の映像取得・推論設定
          (video_fps / inference_fps)には影響しません。全モニターへ一括で適用され、
          ブラウザを閉じても保持されます。画面の外にあるMonitorカードや、
          非表示のタブでは、画像の更新を止めます。
        </p>
        <label>
          画面自動リロード
          <select
            value={settings.reloadIntervalMinutes}
            onChange={(event) => onChange({ reloadIntervalMinutes: Number(event.target.value) as DashboardReloadMinutes })}
          >
            {DASHBOARD_RELOAD_OPTIONS.map((option) => <option key={option.minutes} value={option.minutes}>{option.label}</option>)}
          </select>
        </label>
        <p className="muted">
          長時間表示時に画面を再読み込みします。映像取得・推論設定には影響しません
          (Monitor Runtimeの再起動やBackendの再起動は行いません)。
          タブが非表示の間や、メモ編集・読取値修正・この設定画面の表示中は再読み込みせず、終わってから期限を過ぎていれば再読み込みします。
        </p>
      </section>
      {/* CSV出力(Issue #17)は表示設定(Frontend-only/localStorage)とは独立させ、
          Backendで永続化・出力する(CsvExportSettingsPanel内でBackend APIを直接叩く)。 */}
      <CsvExportSettingsPanel />
      <div className="modal-actions"><button className="primary" onClick={onClose}>閉じる</button></div>
    </div>
  </div>;
}
