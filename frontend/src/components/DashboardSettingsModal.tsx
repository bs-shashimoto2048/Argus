import { DASHBOARD_DISPLAY_FPS_OPTIONS } from "../hooks/useDashboardSettings";
import type { DashboardDisplayFps, DashboardSettings } from "../hooks/useDashboardSettings";

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
            {DASHBOARD_DISPLAY_FPS_OPTIONS.map((fps) => <option key={fps} value={fps}>{fps} FPS</option>)}
          </select>
        </label>
        <p className="muted">
          Dashboard一覧に表示するプレビュー映像の更新頻度です。既存の映像取得・推論設定
          (video_fps / inference_fps)には影響しません。全モニターへ一括で適用され、
          ブラウザを閉じても保持されます。
        </p>
      </section>
      <div className="modal-actions"><button className="primary" onClick={onClose}>閉じる</button></div>
    </div>
  </div>;
}
