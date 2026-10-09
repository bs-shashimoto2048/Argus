import type {BaselineEvent,BaselineStatus,History,Monitor,Source,Inference,SystemInference,ReadingDiagnostics,ModelCatalogEntry,RuntimeDiagnostics,CsvExportStatus,CsvExportRunOutcome,RecordsPage,RecordsQuery,ReadingRecord,RecordCorrection,CorrectionRequest,CorrectionResult,ExcelExportRequest,ExcelExportSaved,DataStorageSettings,DataStorageInput,DataStorageStatus,StorageTestResult} from "../types";
const request=async<T>(url:string,init?:RequestInit):Promise<T>=>{const r=await fetch(url,{headers:{"Content-Type":"application/json",...(init?.headers||{})},...init});if(!r.ok){const body=await r.json().catch(()=>({}));throw new Error(body.detail||`HTTP ${r.status}`)}return r.status===204?undefined as T:r.json()};
// baseline操作用: 409(FORCE_REQUIRED/READING_DISABLED)等のdetailがオブジェクトのため、statusとdetailを保持する。
export class ApiError extends Error{status:number;detail:unknown;constructor(status:number,detail:unknown){super(typeof detail==="string"?detail:(detail&&typeof detail==="object"&&"message" in detail?String((detail as {message:unknown}).message):`HTTP ${status}`));this.status=status;this.detail=detail}}
const baselineRequest=async<T>(url:string,init?:RequestInit):Promise<T>=>{const r=await fetch(url,{headers:{"Content-Type":"application/json"},...init});if(!r.ok){const body=await r.json().catch(()=>({}));const detail=Array.isArray(body.detail)?body.detail.map((d:{msg?:string})=>d.msg).join(" / "):body.detail;throw new ApiError(r.status,detail)}return r.json()};
export const api={
 monitors:()=>request<{monitors:Monitor[]}>('/api/monitors'),
 monitor:(id:number)=>request<Monitor>(`/api/monitors/${id}`),
 // Dashboard/モニター管理の表示順(全MonitorのIDを表示したい順に指定。1 transactionで更新される)
 reorderMonitors:(monitorIds:number[])=>baselineRequest<{monitor_ids:number[]}>('/api/monitors/order',{method:'PUT',body:JSON.stringify({monitor_ids:monitorIds})}),
 create:(data:{name:string;display_name:string;location:string})=>request<Monitor>('/api/monitors',{method:'POST',body:JSON.stringify(data)}),
 update:(id:number,data:unknown)=>request<Monitor>(`/api/monitors/${id}`,{method:'PATCH',body:JSON.stringify(data)}),
 remove:(id:number)=>request<void>(`/api/monitors/${id}`,{method:'DELETE'}),
 cameras:()=>request<{cameras:{device_id:number;label:string}[]}>('/api/cameras'),
 history:()=>request<{items:History[]}>('/api/url-history'),
 deleteHistory:(id:number)=>request<void>(`/api/url-history/${id}`,{method:'DELETE'}),
 check:(source:unknown)=>request<{success:boolean;message:string;detail?:string}>('/api/sources/check',{method:'POST',body:JSON.stringify(source)}),
 testSource:(id:number,source:unknown)=>request<{connected:boolean;source_type:string;width:number|null;height:number|null;fps:number|null;error_code:string|null;message:string;resolved_url_hint:string|null}>(`/api/monitors/${id}/source/test`,{method:'POST',body:JSON.stringify(source)}),
 snapshot:(id:number)=>`/api/monitors/${id}/snapshot`,
 stream:(id:number)=>`/api/monitors/${id}/stream`,
 preview:(id:number)=>`/api/monitors/${id}/preview.jpg`,
 mjpg:(id:number)=>`/api/monitors/${id}/stream.mjpg`,
 overlay:(id:number)=>`/api/monitors/${id}/overlay.jpg`,
 inferenceInput:(id:number)=>`/api/monitors/${id}/inference-input.jpg`,
 systemInference:()=>request<SystemInference>('/api/system/inference'),
 readingDiagnostics:(id:number)=>request<ReadingDiagnostics>(`/api/monitors/${id}/reading/diagnostics`),
 runtimeDiagnostics:(id:number)=>request<RuntimeDiagnostics>(`/api/monitors/${id}/runtime`),
 systemModels:()=>request<{models:ModelCatalogEntry[]}>('/api/system/models'),
 readingBaseline:(id:number)=>baselineRequest<BaselineStatus>(`/api/monitors/${id}/reading/baseline`),
 resetBaseline:(id:number,data:{reason:string;operator:string})=>baselineRequest<BaselineStatus>(`/api/monitors/${id}/reading/baseline/reset`,{method:'POST',body:JSON.stringify(data)}),
 rebaseBaseline:(id:number,data:{value:string;reason:string;operator:string;force?:boolean})=>baselineRequest<BaselineStatus>(`/api/monitors/${id}/reading/baseline/rebase`,{method:'POST',body:JSON.stringify(data)}),
 baselineEvents:(id:number,limit=50)=>baselineRequest<{events:BaselineEvent[]}>(`/api/monitors/${id}/reading/baseline/events?limit=${limit}`),
 roi:(id:number)=>request<import("../types").Roi>(`/api/monitors/${id}/roi`),
 saveRoi:(id:number,value:import("../types").Roi&{roi_mode?:import("../types").RoiMode;context_margin?:number})=>request<import("../types").Roi&{roi_mode:import("../types").RoiMode;context_margin:number}>(`/api/monitors/${id}/roi`,{method:'PUT',body:JSON.stringify(value)}),
 preprocessPreview:async(id:number,payload:unknown):Promise<string>=>{const r=await fetch(`/api/monitors/${id}/preprocess/preview`,{method:'POST',headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});if(!r.ok)throw new Error((await r.json().catch(()=>({}))).detail||`HTTP ${r.status}`);return URL.createObjectURL(await r.blob())},
 csvExportStatus:()=>request<CsvExportStatus>('/api/system/csv-export'),
 updateCsvExportSettings:(payload:{enabled:boolean;output_folder:string|null})=>request<{enabled:boolean;output_folder:string|null}>('/api/system/csv-export',{method:'PUT',body:JSON.stringify(payload)}),
 runCsvExportNow:()=>request<{outcomes:CsvExportRunOutcome[]}>('/api/system/csv-export/run-now',{method:'POST'}),
 // --- 計測記録 / Excel出力 / データ保存設定 (UI再設計 Phase 1〜3のAPI) ---
 records:(q:RecordsQuery)=>{const p=new URLSearchParams();q.monitorIds.forEach(id=>p.append("monitor_id",String(id)));if(q.from)p.set("from",q.from);if(q.to)p.set("to",q.to);p.set("limit",String(q.limit));p.set("offset",String(q.offset));return baselineRequest<RecordsPage>(`/api/records?${p}`)},
 record:(id:number)=>baselineRequest<ReadingRecord>(`/api/records/${id}`),
 // 読取値(正式値)の手動修正と、その監査履歴(carried_forward / 基準値競合の記録だけ修正できる。元証跡は変わらない)
 correctRecord:(id:number,body:CorrectionRequest)=>baselineRequest<CorrectionResult>(`/api/records/${id}/correct`,{method:'POST',body:JSON.stringify(body)}),
 recordCorrections:(id:number)=>baselineRequest<{record_id:number;corrections:RecordCorrection[]}>(`/api/records/${id}/corrections`),
 recordImage:(id:number,kind:"original"|"overlay")=>`/api/records/${id}/image/${kind}`,
 exportExcelSave:(body:ExcelExportRequest)=>baselineRequest<ExcelExportSaved>('/api/records/export/excel',{method:'POST',body:JSON.stringify(body)}),
 exportExcelDownload:async(body:ExcelExportRequest):Promise<{blob:Blob;filename:string;totalRows:number|null}>=>{
  const r=await fetch('/api/records/export/excel',{method:'POST',headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!r.ok){const b=await r.json().catch(()=>({}));const detail=Array.isArray(b.detail)?b.detail.map((d:{msg?:string})=>d.msg).join(" / "):b.detail;throw new ApiError(r.status,detail)}
  const m=/filename="?([^";]+)"?/.exec(r.headers.get("content-disposition")||"");const rows=r.headers.get("x-argus-total-rows");
  return {blob:await r.blob(),filename:m?m[1]:"Argus_MeterRecords.xlsx",totalRows:rows?Number(rows):null}},
 dataStorage:()=>baselineRequest<DataStorageSettings>('/api/system/data-storage'),
 updateDataStorage:(body:DataStorageInput)=>baselineRequest<DataStorageSettings>('/api/system/data-storage',{method:'PUT',body:JSON.stringify(body)}),
 dataStorageStatus:()=>baselineRequest<DataStorageStatus>('/api/system/data-storage/status'),
 testDataStorage:(target:"image"|"excel",path?:string)=>baselineRequest<StorageTestResult>('/api/system/data-storage/test',{method:'POST',body:JSON.stringify(path?{target,path}:{target})}),
};
export type {Source,Inference};
