import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { History, Source } from "../types";

type EditableSource = Source & { password?: string };

export function SourceSettings({ source, onChange, onCheck, open, onToggleOpen }: { source: Source | null; onChange: (s: EditableSource) => void; onCheck: (s: EditableSource) => void; open: boolean; onToggleOpen: () => void }) {
  const [cameras, setCameras] = useState<{ device_id: number; label: string }[]>([]);
  const [history, setHistory] = useState<History[]>([]);
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const current = source ?? { source_type: "camera" as const, device_id: 0, url: "", username: "", has_password: false };
  const update = (patch: Partial<Source>) => onChange({ ...current, ...patch, password });
  // passwordはSourceSettings内のlocal stateにしか保持されないため、他のフィールド変更を
  // 経由しない限り親(source state)へ伝わらなかった(パスワードだけ入力してすぐ保存すると
  // 消えるバグ)。入力の都度、直接onChangeへ渡して親stateへ確実に反映する。
  const handlePasswordChange = (value: string) => {
    setPassword(value);
    onChange({ ...current, password: value });
  };

  useEffect(() => {
    api.cameras().then((r) => setCameras(r.cameras)).catch(() => undefined);
    api.history().then((r) => setHistory(r.items)).catch(() => undefined);
  }, []);

  return <section className="panel collapsible-panel">
    <button type="button" className="collapsible-header" onClick={onToggleOpen} aria-expanded={open}>
      <span className="chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
      <h3>カメラ / 映像URL</h3>
    </button>
    <div className="collapsible-body" style={open ? undefined : { display: "none" }}>
      <label>入力方式<select value={current.source_type} onChange={(e) => update({ source_type: e.target.value as Source["source_type"] })}><option value="camera">接続カメラ</option><option value="url">URL</option></select></label>
      {current.source_type === "camera" ? <label>接続カメラ<select value={current.device_id ?? 0} onChange={(e) => update({ device_id: Number(e.target.value) })}>{cameras.length ? cameras.map((camera) => <option key={camera.device_id} value={camera.device_id}>{camera.label}</option>) : <option value="0">Camera 0（未検出）</option>}</select></label> : <>
        <label>保存済みURL<select value="" onChange={(e) => { const selected = history.find((item) => String(item.id) === e.target.value); if (selected) update({ url: selected.url, username: selected.username, history_id: selected.id, has_password: selected.has_password }); }}><option value="">選択してください</option>{history.map((item) => <option key={item.id} value={item.id}>{item.url}</option>)}</select></label>
        <label>URL<input value={current.url ?? ""} onChange={(e) => update({ url: e.target.value, history_id: undefined })} placeholder="rtsp:// または http://" /></label>
      </>}
      <h3>Basic認証</h3>
      <label>ユーザー名<input value={current.username ?? ""} onChange={(e) => update({ username: e.target.value })} /></label>
      <label>パスワード{current.has_password && !password && <span className="password-saved-badge">🔒 保存済み</span>}<div className="password-row"><input type={showPassword ? "text" : "password"} value={password} placeholder={current.has_password ? "保存済み（変更時のみ入力）" : "未設定"} onChange={(e) => handlePasswordChange(e.target.value)} /><button type="button" className="icon-button" onClick={() => setShowPassword((v) => !v)}>{showPassword ? "◉" : "◉̸"}</button></div></label>
      <button className="secondary" onClick={() => onCheck({ ...current, password })}>接続確認</button>
    </div>
  </section>;
}
