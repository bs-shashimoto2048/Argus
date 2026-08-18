import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Brand } from "../components/Brand";

export function MonitorCreatePage() {
  const [form, setForm] = useState({ name: "", display_name: "", location: "" });
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const submit = async (event: React.FormEvent) => { event.preventDefault(); try { const monitor = await api.create(form); navigate(`/monitors/${monitor.id}`); } catch (reason) { setError(String(reason)); } };
  return <main className="page narrow"><header className="topbar"><Brand /><button className="secondary" onClick={() => navigate("/")}>＜ 戻る</button></header><section className="form-card"><h1>モニター追加</h1><p className="muted">登録後、詳細画面でカメラと推論設定を行います。</p>{error && <div className="alert error">{error}</div>}<form onSubmit={submit}><label>モニター名<input required pattern="[A-Za-z0-9_-]+" placeholder="meter_001" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label>表示名<input required placeholder="第1工場 ガスメーター" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} /></label><label>設置場所<input placeholder="第1工場" value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} /></label><button type="submit">作成して設定へ</button></form></section></main>;
}
