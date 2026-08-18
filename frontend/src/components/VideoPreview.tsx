import {useEffect,useState} from "react";
import {api} from "../api/client";
export function VideoPreview({monitorId,large=false}:{monitorId:number;large?:boolean}){const [tick,setTick]=useState(0);useEffect(()=>{if(large)return;const t=window.setInterval(()=>setTick(v=>v+1),1000);return()=>window.clearInterval(t)},[large]);return large?<img className="video-image" src={api.stream(monitorId)} alt="ライブ映像"/>:<img className="video-image" src={`${api.snapshot(monitorId)}?t=${tick}`} alt="ライブ映像"/>}
