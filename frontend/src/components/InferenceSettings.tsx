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

  // Issue #38: engine切替時は互換しないmodel_idを残さない(cpp_onnx専用ONNXとultralytics用
  // .ptは相互に使えない)。Backendもengine/modelの組合せを検証するが、UIでも誤選択を防ぐ。
  const handleEngineChange = (engine: "ultralytics" | "cpp_onnx") => {
    if (engine === value.engine) return;
    onChange({ ...value, engine, model_id: null });
  };

  // cpp_onnxはC++ worker側でprofile固有のthreshold/input shapeを適用するため、モデル選択時に
  // production profileの値(registry.jsonのrecommended_conf/iou)をMonitor設定へ反映する。
  const handleCppModelChange = (modelId: string) => {
    const entry = models.find((item) => item.model_id === modelId);
    onChange({
      ...value,
      model_id: modelId || null,
      ...(entry?.recommended_conf != null ? { confidence: entry.recommended_conf } : {}),
      ...(entry?.recommended_iou != null ? { iou: entry.recommended_iou } : {}),
    });
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
  const isCpp = value.method === "object_detection" && value.engine === "cpp_onnx";
  // cpp_onnx: engine=cpp_onnxとして登録されたモデルのみ。ultralytics: cpp_onnx専用ONNXは除外。
  const cppModels = models.filter((entry) => entry.engine === "cpp_onnx");
  const ultralyticsModels = models.filter((entry) => entry.engine !== "cpp_onnx");
  const cppEntry = cppModels.find((entry) => entry.model_id === value.model_id);
  const inputShape = cppEntry?.input_shape?.join("x");
  // cpp_onnx選択中はproduction profile由来の値を表示する(保存済みのMonitor設定値ではなく、
  // 実際にworkerが適用する値)。
  const shownConfidence = isCpp && cppEntry?.recommended_conf != null ? cppEntry.recommended_conf : value.confidence;
  const shownIou = isCpp && cppEntry?.recommended_iou != null ? cppEntry.recommended_iou : value.iou;

  return <section className="panel collapsible-panel"><button type="button" className="collapsible-header" onClick={onToggleOpen} aria-expanded={open}><span className="chevron" aria-hidden="true">{open?"▾":"▸"}</span><h3>推論設定（次フェーズ）</h3></button><div className="collapsible-body" style={open?undefined:{display:"none"}}><label>推論方法<select value={value.method} onChange={e=>handleMethodChange(e.target.value as Inference["method"])}><option value="object_detection">Object Detection</option><option value="ocr">OCR</option></select></label>{value.method==="ocr"?<label>OCR Engine<select value={value.engine} onChange={e=>set({engine:e.target.value as Inference["engine"]})}><option value="easyocr">EasyOCR</option><option value="tesseract">Tesseract</option></select></label>:<label>実行エンジン<select value={value.engine==="cpp_onnx"?"cpp_onnx":"ultralytics"} onChange={e=>handleEngineChange(e.target.value as "ultralytics"|"cpp_onnx")}><option value="ultralytics">Ultralytics（既定）</option><option value="cpp_onnx">C++ ONNX（Production Candidate）</option></select></label>}{value.method==="ocr"?null:isCpp?<label>モデル<select value={cppEntry?cppEntry.model_id:""} onChange={e=>handleCppModelChange(e.target.value)}><option value="">選択してください</option>{cppModels.map((entry)=><option key={entry.model_id} value={entry.model_id}>{entry.model_id}{entry.profile?` (${entry.profile})`:""}{entry.exists?"":" - ファイル無し"}</option>)}</select>{!cppEntry&&<small className="muted">C++ ONNXではモデルの選択が必要です（未選択のままでは保存できません）。</small>}{cppEntry&&!cppEntry.exists&&<small className="muted">モデルファイルが配置されていません（実行時にMODEL_NOT_CONFIGUREDとなります）。</small>}</label>:<label>モデル{models.length>0?<select value={modelKnown&&!cppModels.some((entry)=>entry.model_id===value.model_id)?(value.model_id??""):""} onChange={e=>set({model_id:e.target.value||null})}><option value="">未設定</option>{ultralyticsModels.map((entry)=><option key={entry.model_id} value={entry.model_id}>{entry.model_id} ({entry.role}){entry.exists?"":" - ファイル無し"}</option>)}{!(modelKnown&&!cppModels.some((entry)=>entry.model_id===value.model_id))&&value.model_id&&<option value={value.model_id}>{value.model_id}</option>}</select>:<input value={value.model_id??""} placeholder="未設定" onChange={e=>set({model_id:e.target.value||null})}/>}</label>}{isCpp?<div className="readonly-field"><small>Device</small><strong>CPU（CPUExecutionProvider固定）</strong></div>:<label>Device<select value={value.device} onChange={e=>set({device:e.target.value})}>{deviceOptions.map((option)=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>}<div className="two-col"><label>映像FPS<input type="number" min="1" value={value.video_fps} onChange={e=>set({video_fps:Number(e.target.value)})}/></label><label>推論FPS<input type="number" min="1" value={value.inference_fps} onChange={e=>set({inference_fps:Number(e.target.value)})}/></label></div>{value.method==="object_detection"&&<div className="two-col"><label>Conf<input type="number" min="0" max="1" step=".05" value={shownConfidence} disabled={isCpp} onChange={e=>set({confidence:Number(e.target.value)})}/></label><label>IoU<input type="number" min="0" max="1" step=".05" value={shownIou} disabled={isCpp} onChange={e=>set({iou:Number(e.target.value)})}/></label></div>}{isCpp&&<p className="muted" style={{fontSize:"0.76rem",margin:"0 0 8px"}}>C++ ONNXでは検証済みProduction Profileの推論条件を使用します（Conf/IoU/入力shapeは編集できません）。</p>}{isCpp?<div className="readonly-field"><small>ImageSize</small><strong>{inputShape?`profile固定 ${inputShape}（1x3xHxW）`:"profile固定shape（モデル選択後に表示）"}</strong></div>:<label>ImageSize<input type="number" min="1" value={value.image_size} onChange={e=>set({image_size:Number(e.target.value)})}/></label>}</div></section>;
}
