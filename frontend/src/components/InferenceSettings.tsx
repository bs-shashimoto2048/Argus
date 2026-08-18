import { useEffect, useState } from "react";
import type {DeviceOption,Inference} from "../types";
import { api } from "../api/client";

const FALLBACK_DEVICES: DeviceOption[] = [{ value: "auto", label: "Auto" }, { value: "cpu", label: "CPU" }];

export function InferenceSettings({value,onChange}:{value:Inference;onChange:(v:Inference)=>void}){
  const set=(p:Partial<Inference>)=>onChange({...value,...p});
  const [devices, setDevices] = useState<DeviceOption[]>(FALLBACK_DEVICES);

  useEffect(() => {
    api.systemInference()
      .then((diagnostics) => { if (diagnostics.devices?.length) setDevices(diagnostics.devices); })
      .catch(() => undefined);
  }, []);

  // 保存済みのdeviceが一覧に無くても(実行環境が変わった等)選択肢から消さない。
  const deviceOptions = devices.some((option) => option.value === value.device) ? devices : [...devices, { value: value.device, label: value.device }];

  return <section className="panel"><h3>推論設定（次フェーズ）</h3><label>推論方法<select value={value.method} onChange={e=>set({method:e.target.value as Inference["method"]})}><option value="object_detection">Object Detection</option><option value="ocr">OCR</option></select></label>{value.method==="ocr"?<label>OCR Engine<select value={value.engine} onChange={e=>set({engine:e.target.value as Inference["engine"]})}><option value="easyocr">EasyOCR</option><option value="tesseract">Tesseract</option></select></label>:<label>モデル<input value={value.model_id??""} placeholder="未設定" onChange={e=>set({model_id:e.target.value||null})}/></label>}<label>Device<select value={value.device} onChange={e=>set({device:e.target.value})}>{deviceOptions.map((option)=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label><div className="two-col"><label>映像FPS<input type="number" min="1" value={value.video_fps} onChange={e=>set({video_fps:Number(e.target.value)})}/></label><label>推論FPS<input type="number" min="1" value={value.inference_fps} onChange={e=>set({inference_fps:Number(e.target.value)})}/></label></div>{value.method==="object_detection"&&<div className="two-col"><label>Conf<input type="number" min="0" max="1" step=".05" value={value.confidence} onChange={e=>set({confidence:Number(e.target.value)})}/></label><label>IoU<input type="number" min="0" max="1" step=".05" value={value.iou} onChange={e=>set({iou:Number(e.target.value)})}/></label></div>}<label>ImageSize<input type="number" min="1" value={value.image_size} onChange={e=>set({image_size:Number(e.target.value)})}/></label></section>;
}
