import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { Roi, RoiMode } from "../types";

type Props = {
  monitorId: number;
  initial: Roi;
  // object_detection時のみROIモードのUIを表示する(OCR等ではroi_modeは無関係)。
  isObjectDetection: boolean;
  initialRoiMode: RoiMode;
  initialContextMargin: number;
  onClose: () => void;
  onSaved: (roi: Roi, roiMode: RoiMode, contextMargin: number) => void;
};
type Mode = "move" | "nw" | "ne" | "sw" | "se";

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

export function RoiEditor({ monitorId, initial, isObjectDetection, initialRoiMode, initialContextMargin, onClose, onSaved }: Props) {
  const [roi, setRoi] = useState<Roi>(initial);
  const [roiMode, setRoiMode] = useState<RoiMode>(initialRoiMode);
  const [contextMargin, setContextMargin] = useState(initialContextMargin);
  const [tick, setTick] = useState(0);
  const [saving, setSaving] = useState(false);
  const frameRef = useRef<HTMLDivElement>(null);
  const interaction = useRef<{ mode: Mode; x: number; y: number; roi: Roi } | null>(null);
  useEffect(() => { const timer = window.setInterval(() => setTick((value) => value + 1), 1000); return () => window.clearInterval(timer); }, []);
  const imageUrl = useMemo(() => `${api.preview(monitorId)}?roi-editor=${tick}`, [monitorId, tick]);

  const start = (event: React.PointerEvent, mode: Mode) => {
    event.preventDefault();
    interaction.current = { mode, x: event.clientX, y: event.clientY, roi };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  };
  const move = (event: React.PointerEvent) => {
    const active = interaction.current;
    const bounds = frameRef.current?.getBoundingClientRect();
    if (!active || !bounds) return;
    const dx = (event.clientX - active.x) / bounds.width;
    const dy = (event.clientY - active.y) / bounds.height;
    const base = active.roi;
    if (active.mode === "move") {
      setRoi({ ...base, x: clamp(base.x + dx, 0, 1 - base.width), y: clamp(base.y + dy, 0, 1 - base.height) });
      return;
    }
    let left = base.x; let top = base.y; let right = base.x + base.width; let bottom = base.y + base.height;
    if (active.mode.includes("w")) left = clamp(base.x + dx, 0, right - 0.02);
    if (active.mode.includes("e")) right = clamp(base.x + base.width + dx, left + 0.02, 1);
    if (active.mode.includes("n")) top = clamp(base.y + dy, 0, bottom - 0.02);
    if (active.mode.includes("s")) bottom = clamp(base.y + base.height + dy, top + 0.02, 1);
    setRoi({ x: left, y: top, width: right - left, height: bottom - top });
  };
  const stop = () => { interaction.current = null; };
  const save = async () => {
    setSaving(true);
    try {
      const saved = await api.saveRoi(monitorId, { ...roi, ...(isObjectDetection ? { roi_mode: roiMode, context_margin: contextMargin } : {}) });
      onSaved(roi, saved.roi_mode, saved.context_margin);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="ROI編集">
    <div className="modal roi-editor">
      <div className="modal-head"><h2>ROIを編集</h2><button className="icon-button" onClick={onClose}>×</button></div>
      <p className="muted">映像上の範囲をドラッグ、四隅のハンドルで調整できます。</p>
      <div className="roi-frame" ref={frameRef} onPointerMove={move} onPointerUp={stop}>
        <img src={imageUrl} alt="ROI対象映像" />
        <svg className="roi-overlay" viewBox="0 0 1 1" preserveAspectRatio="none">
          <rect x={roi.x} y={roi.y} width={roi.width} height={roi.height} className="roi-rect" onPointerDown={(event) => start(event, "move")} />
          <circle cx={roi.x} cy={roi.y} r="0.012" className="roi-handle" onPointerDown={(event) => start(event, "nw")} />
          <circle cx={roi.x + roi.width} cy={roi.y} r="0.012" className="roi-handle" onPointerDown={(event) => start(event, "ne")} />
          <circle cx={roi.x} cy={roi.y + roi.height} r="0.012" className="roi-handle" onPointerDown={(event) => start(event, "sw")} />
          <circle cx={roi.x + roi.width} cy={roi.y + roi.height} r="0.012" className="roi-handle" onPointerDown={(event) => start(event, "se")} />
        </svg>
      </div>
      <div className="roi-values"><span>x {roi.x.toFixed(3)}</span><span>y {roi.y.toFixed(3)}</span><span>w {roi.width.toFixed(3)}</span><span>h {roi.height.toFixed(3)}</span></div>
      {isObjectDetection && <div className="roi-mode-picker">
        <label className="roi-mode-option">
          <input type="radio" name="roi-mode" checked={roiMode === "filter_only"} onChange={() => setRoiMode("filter_only")} />
          検出結果をROI内に限定（推奨）
        </label>
        <label className="roi-mode-option">
          <input type="radio" name="roi-mode" checked={roiMode === "crop_context"} onChange={() => setRoiMode("crop_context")} />
          ROI周辺を切り出して推論（詳細設定）
        </label>
        {roiMode === "crop_context" && <label className="roi-margin-field">
          context margin（ROI自体の幅/高さに対する拡張比率）
          <input type="number" min={0} max={4} step={0.05} value={contextMargin} onChange={(event) => setContextMargin(Number(event.target.value))} />
        </label>}
        <p className="muted roi-mode-hint">
          {roiMode === "filter_only"
            ? "Full Frameで推論し、ROI内に中心があるDetectionだけ採用します（学習時と同じ文脈で推論できるため推奨）。"
            : "ROIの周辺へ文脈を確保するため広げてcropしてから推論します（ROIがタイトすぎると検出できない場合の詳細設定）。"}
        </p>
      </div>}
      <div className="modal-actions"><button className="secondary" onClick={() => setRoi({ x: 0, y: 0, width: 1, height: 1 })}>リセット</button><button className="secondary" onClick={onClose}>キャンセル</button><button className="primary" onClick={save} disabled={saving}>{saving ? "保存中..." : "保存"}</button></div>
    </div>
  </div>;
}
