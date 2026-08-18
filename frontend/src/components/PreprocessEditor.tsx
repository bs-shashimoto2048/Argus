import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Roi } from "../types";

export type PreprocessSettings = { grayscale:boolean; binary:boolean; threshold:number; invert:boolean; brightness:number; contrast:number; clahe:boolean; sharpen:boolean; resize:number|null };
const defaults: PreprocessSettings = { grayscale:false, binary:false, threshold:128, invert:false, brightness:1, contrast:1, clahe:false, sharpen:false, resize:null };

type Props = { monitorId:number; roi:Roi; initial:Record<string, unknown>; onClose:()=>void; onSaved:(settings:PreprocessSettings)=>void };

export function PreprocessEditor({ monitorId, roi, initial, onClose, onSaved }: Props) {
  const [settings, setSettings] = useState<PreprocessSettings>({ ...defaults, ...initial } as PreprocessSettings);
  const [processed, setProcessed] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => { const timer = window.setTimeout(async () => { try { const url = await api.preprocessPreview(monitorId, { settings, roi }); setProcessed((old) => { if (old) URL.revokeObjectURL(old); return url; }); } catch { setProcessed(""); } }, 180); return () => window.clearTimeout(timer); }, [monitorId, roi, settings, tick]);
  const update = <K extends keyof PreprocessSettings>(key: K, value: PreprocessSettings[K]) => setSettings((current) => ({ ...current, [key]: value }));
  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="前処理編集">
    <div className="modal preprocess-editor">
      <div className="modal-head"><h2>前処理を編集</h2><button className="icon-button" onClick={onClose}>×</button></div>
      <div className="preprocess-preview"><div><small>Original</small><img src={`${api.preview(monitorId)}?preprocess=${tick}`} alt="Original" /></div><div><small>Processed</small>{processed ? <img src={processed} alt="Processed" /> : <div className="no-video">Preview待機中</div>}</div></div>
      <div className="preprocess-grid">
        <label><input type="checkbox" checked={settings.grayscale} onChange={(e) => update("grayscale", e.target.checked)} /> Grayscale</label>
        <label><input type="checkbox" checked={settings.binary} onChange={(e) => update("binary", e.target.checked)} /> Binary</label>
        <label>Threshold<input type="number" min="0" max="255" value={settings.threshold} onChange={(e) => update("threshold", Number(e.target.value))} /></label>
        <label><input type="checkbox" checked={settings.invert} onChange={(e) => update("invert", e.target.checked)} /> Invert</label>
        <label>Brightness<input type="number" step="0.1" min="0.1" max="3" value={settings.brightness} onChange={(e) => update("brightness", Number(e.target.value))} /></label>
        <label>Contrast<input type="number" step="0.1" min="0.1" max="3" value={settings.contrast} onChange={(e) => update("contrast", Number(e.target.value))} /></label>
        <label><input type="checkbox" checked={settings.clahe} onChange={(e) => update("clahe", e.target.checked)} /> CLAHE</label>
        <label><input type="checkbox" checked={settings.sharpen} onChange={(e) => update("sharpen", e.target.checked)} /> Sharpen</label>
        <label>Resize width<input type="number" min="32" max="4096" value={settings.resize ?? ""} onChange={(e) => update("resize", e.target.value ? Number(e.target.value) : null)} /></label>
      </div>
      <div className="modal-actions"><button className="secondary" onClick={onClose}>キャンセル</button><button className="primary" onClick={() => { onSaved(settings); onClose(); }}>設定を保存</button></div>
    </div>
  </div>;
}
