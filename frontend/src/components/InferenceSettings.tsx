import { useEffect, useState } from "react";
import type {DeviceOption,Inference,ModelCatalogEntry} from "../types";
import { api } from "../api/client";

const FALLBACK_DEVICES: DeviceOption[] = [{ value: "auto", label: "Auto" }, { value: "cpu", label: "CPU" }];

export function InferenceSettings({value,onChange,open,onToggleOpen}:{value:Inference;onChange:(v:Inference)=>void;open:boolean;onToggleOpen:()=>void}){
  const set=(p:Partial<Inference>)=>onChange({...value,...p});
  const [devices, setDevices] = useState<DeviceOption[]>(FALLBACK_DEVICES);
  const [models, setModels] = useState<ModelCatalogEntry[]>([]);

  // Backendのcreate_engine()は method=="object_detection" && engine=="ultralytics" の時だけ
  // YOLOへ分岐し、それ以外はengineの値だけでOCRエンジンを選ぶ(methodを見ない)。保存時は
  // Backend側(monitor_service._normalize_engine)でも同じ規則に正規化されるが、保存前の
  // フォーム表示・送信payloadの時点でも矛盾した組合せ(例: object_detection+tesseract)を
  // 作らないよう、ここでも同じ規則でengineを合わせる(Issue #16)。
  const handleMethodChange = (method: Inference["method"]) => {
    const engine: Inference["engine"] = method === "object_detection" ? "ultralytics" : (value.engine === "tesseract" || value.engine === "easyocr" ? value.engine : "easyocr");
    onChange({ ...value, method, engine });
  };

  useEffect(() => {
    api.systemInference()
      .then((diagnostics) => { if (diagnostics.devices?.length) setDevices(diagnostics.devices); })
      .catch(() => undefined);
    api.systemModels()
      .then((response) => setModels(response.models || []))
      .catch(() => undefined);
  }, []);

  // 保存済みのdeviceが一覧に無くても(実行環境が変わった等)選択肢から消さない。
  const deviceOptions = devices.some((option) => option.value === value.device) ? devices : [...devices, { value: value.device, label: value.device }];
  const modelKnown = models.some((entry) => entry.model_id === value.model_id);

  return <section className="panel collapsible-panel"><button type="button" className="collapsible-header" onClick={onToggleOpen} aria-expanded={open}><span className="chevron" aria-hidden="true">{open?"▾":"▸"}</span><h3>推論設定（次フェーズ）</h3></button><div className="collapsible-body" style={open?undefined:{display:"none"}}><label>推論方法<select value={value.method} onChange={e=>handleMethodChange(e.target.value as Inference["method"])}><option value="object_detection">Object Detection</option><option value="ocr">OCR</option></select></label>{value.method==="ocr"?<label>OCR Engine<select value={value.engine} onChange={e=>set({engine:e.target.value as Inference["engine"]})}><option value="easyocr">EasyOCR</option><option value="tesseract">Tesseract</option></select></label>:<div className="readonly-field"><small>実行エンジン</small><strong>Ultralytics</strong></div>}{value.method==="ocr"?null:<label>モデル{models.length>0?<select value={modelKnown?(value.model_id??""):""} onChange={e=>set({model_id:e.target.value||null})}><option value="">未設定</option>{models.map((entry)=><option key={entry.model_id} value={entry.model_id}>{entry.model_id} ({entry.role}){entry.exists?"":" - ファイル無し"}</option>)}{!modelKnown&&value.model_id&&<option value={value.model_id}>{value.model_id}</option>}</select>:<input value={value.model_id??""} placeholder="未設定" onChange={e=>set({model_id:e.target.value||null})}/>}</label>}<label>Device<select value={value.device} onChange={e=>set({device:e.target.value})}>{deviceOptions.map((option)=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label><div className="two-col"><label>映像FPS<input type="number" min="1" value={value.video_fps} onChange={e=>set({video_fps:Number(e.target.value)})}/></label><label>推論FPS<input type="number" min="1" value={value.inference_fps} onChange={e=>set({inference_fps:Number(e.target.value)})}/></label></div>{value.method==="object_detection"&&<div className="two-col"><label>Conf<input type="number" min="0" max="1" step=".05" value={value.confidence} onChange={e=>set({confidence:Number(e.target.value)})}/></label><label>IoU<input type="number" min="0" max="1" step=".05" value={value.iou} onChange={e=>set({iou:Number(e.target.value)})}/></label></div>}<label>ImageSize<input type="number" min="1" value={value.image_size} onChange={e=>set({image_size:Number(e.target.value)})}/></label></div></section>;
}
