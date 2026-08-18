import type {History,Monitor,Source,Inference,SystemInference} from "../types";
const request=async<T>(url:string,init?:RequestInit):Promise<T>=>{const r=await fetch(url,{headers:{"Content-Type":"application/json",...(init?.headers||{})},...init});if(!r.ok){const body=await r.json().catch(()=>({}));throw new Error(body.detail||`HTTP ${r.status}`)}return r.status===204?undefined as T:r.json()};
export const api={
 monitors:()=>request<{monitors:Monitor[]}>('/api/monitors'),
 monitor:(id:number)=>request<Monitor>(`/api/monitors/${id}`),
 create:(data:{name:string;display_name:string;location:string})=>request<Monitor>('/api/monitors',{method:'POST',body:JSON.stringify(data)}),
 update:(id:number,data:unknown)=>request<Monitor>(`/api/monitors/${id}`,{method:'PATCH',body:JSON.stringify(data)}),
 remove:(id:number)=>request<void>(`/api/monitors/${id}`,{method:'DELETE'}),
 cameras:()=>request<{cameras:{device_id:number;label:string}[]}>('/api/cameras'),
 history:()=>request<{items:History[]}>('/api/url-history'),
 deleteHistory:(id:number)=>request<void>(`/api/url-history/${id}`,{method:'DELETE'}),
 check:(source:unknown)=>request<{success:boolean;message:string;detail?:string}>('/api/sources/check',{method:'POST',body:JSON.stringify(source)}),
 testSource:(id:number,source:unknown)=>request<{connected:boolean;source_type:string;width:number|null;height:number|null;fps:number|null;error_code:string|null;message:string}>(`/api/monitors/${id}/source/test`,{method:'POST',body:JSON.stringify(source)}),
 snapshot:(id:number)=>`/api/monitors/${id}/snapshot`,
 stream:(id:number)=>`/api/monitors/${id}/stream`,
 preview:(id:number)=>`/api/monitors/${id}/preview.jpg`,
 mjpg:(id:number)=>`/api/monitors/${id}/stream.mjpg`,
 overlay:(id:number)=>`/api/monitors/${id}/overlay.jpg`,
 systemInference:()=>request<SystemInference>('/api/system/inference'),
 roi:(id:number)=>request<import("../types").Roi>(`/api/monitors/${id}/roi`),
 saveRoi:(id:number,value:import("../types").Roi)=>request<import("../types").Roi>(`/api/monitors/${id}/roi`,{method:'PUT',body:JSON.stringify(value)}),
 preprocessPreview:async(id:number,payload:unknown):Promise<string>=>{const r=await fetch(`/api/monitors/${id}/preprocess/preview`,{method:'POST',headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});if(!r.ok)throw new Error((await r.json().catch(()=>({}))).detail||`HTTP ${r.status}`);return URL.createObjectURL(await r.blob())},
};
export type {Source,Inference};
