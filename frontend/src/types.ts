export type Status = "stopped"|"connecting"|"normal"|"warning"|"connection_error"|"read_error";
export type Source = {source_type:"camera"|"url";device_id:number|null;url:string|null;username:string|null;has_password:boolean;history_id?:number};
export type Inference = {method:"object_detection"|"ocr";engine:"ultralytics"|"easyocr"|"tesseract";model_id:string|null;device:string;video_fps:number;inference_fps:number;confidence:number;iou:number;image_size:number;preprocessing:Record<string,unknown>;roi:{x:number;y:number;width:number;height:number};engine_options:Record<string,unknown>};
export type Monitor = {id:number;name:string;display_name:string;location:string;enabled:boolean;status:Status;created_at:string;updated_at:string;source:Source|null;inference:Inference;current_value:string|null;previous_value:string|null;confidence:number|null;last_updated:string|null};
export type History = {id:number;url:string;username:string|null;last_verified_at:string;has_password:boolean};
