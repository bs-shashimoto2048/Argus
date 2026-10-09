// Issue #29: statusは映像Runtime接続状態専用(RuntimeManager/MonitorRuntimeのみが書き込む)。
// 読取・推論状態はinference_status(InferenceStatus)で別途表現する(互いに上書きしない)。
export type Status = "stopped"|"connecting"|"running"|"reconnecting"|"error";
export type InferenceStatus = "disabled"|"pending"|"ok"|"low_confidence"|"read_error";
export type Source = {source_type:"camera"|"local_camera"|"url";device_id:number|null;url:string|null;username:string|null;has_password:boolean;history_id?:number};
export type ReadingSettings = {
  enabled:boolean;
  mode:"majority"|"consecutive";
  window_size:number;
  required_matches:number;
  min_confidence:number|null;
  expected_digits:number|null;
  decimal_position:number|null;
  monotonic:boolean;
  max_rate_per_minute:number|null;
  max_consecutive_failures:number;
  allow_rollover:boolean;
  rollover_max:number|null;
};
export type RoiMode = "filter_only"|"crop_context";
export type Inference = {method:"object_detection"|"ocr";engine:"ultralytics"|"easyocr"|"tesseract"|"cpp_onnx";model_id:string|null;device:string;video_fps:number;inference_fps:number;confidence:number;iou:number;image_size:number;preprocessing:Record<string,unknown>;roi:{x:number;y:number;width:number;height:number};roi_mode:RoiMode;context_margin:number;reading:ReadingSettings;engine_options:Record<string,unknown>};
export type Roi = {x:number;y:number;width:number;height:number};
export type Monitor = {id:number;name:string;display_name:string;display_order?:number|null;location:string;enabled:boolean;status:Status;created_at:string;updated_at:string;source:Source|null;inference:Inference;current_value:string|null;previous_value:string|null;confidence:number|null;last_updated:string|null;previous_confidence:number|null;previous_confirmed_at:string|null;inference_status:InferenceStatus;last_inference_error:string|null;current_inference_error:string|null;reading_baseline:ReadingBaselineSummary|null};
export type History = {id:number;url:string;username:string|null;last_verified_at:string;has_password:boolean};
export type DeviceOption = {value:string;label:string};
export type SystemInference = {
  torch:{available:boolean;version:string|null;cuda_available:boolean;cuda_version:string|null;device_count:number;devices:{index:number;name:string}[]};
  ultralytics:{available:boolean;version?:string|null};
  easyocr:{available:boolean};
  tesseract:{python_package:boolean;executable:boolean;version?:string|null};
  devices:DeviceOption[];
};
export type ModelCatalogEntry = {
  model_id: string;
  role: "baseline"|"candidate"|"production"|"deprecated"|string;
  exists: boolean;
  engine?: string;
  profile?: "digital"|"drum"|string;
  input_shape?: number[];
  recommended_conf?: number;
  recommended_iou?: number;
  recommended_imgsz?: number;
  notes?: string;
};
export type PipelineDiagnostics = {
  frame_width: number;
  frame_height: number;
  roi_mode: RoiMode|null;
  context_margin: number|null;
  roi_normalized: Roi;
  roi_pixel: [number, number, number, number];
  inference_crop_pixel: [number, number, number, number];
  crop_shape: [number, number];
  preprocess_output_shape: [number, number];
  model_input_shape: [number, number];
  raw_detection_count: number;
  roi_filtered_detection_count: number;
  engine: string;
  model_id: string|null;
};
export type RuntimeDiagnostics = {
  source_type: string;
  state: string;
  frame_width: number|null;
  frame_height: number|null;
  source_fps: number|null;
  last_frame_timestamp: number|null;
  reconnect_count: number;
  last_error: string|null;
  frame_age: number|null;
  stale: boolean;
  inference_enabled: boolean;
  inference_result: string|null;
  pipeline: PipelineDiagnostics|null;
};
export type CsvExportMonitorStatus = {monitor_id:number;display_name:string;last_exported_hour:string|null;last_exported_at:string|null;last_error:string|null};
export type CsvExportStatus = {enabled:boolean;output_folder:string|null;worker_running:boolean;last_tick_at:string|null;last_test_run_at:string|null;monitors:CsvExportMonitorStatus[]};
export type CsvExportRunOutcome = {monitor_id:number;display_name:string;status:"written"|"skipped_already_exported"|"error";detail:string|null};
export type RawReadingDiagnostic = {value:string|null;confidence:number|null;timestamp:string|null;engine:string;error:string|null;detection_count:number};
export type ReadingBaselineSummary = {value:string|null;state:"active"|"pending_reset"|string;confirmed_at:string|null;conflict:boolean;conflict_status:string|null;conflict_candidate:string|null;conflict_since:string|null;conflict_seconds:number};
export type BaselineConflict = {status:string;candidate:string;count:number;started_at:string;last_at:string;duration_seconds:number;active:boolean;alert:boolean};
export type BaselineStatus = {
  monitor_id:number;
  baseline:{value:string|null;numeric_value:string|null;confirmed_at:string|null;age_seconds:number|null;source:string;state:"active"|"pending_reset"|string;epoch:number;decimal_position:number|null;expected_digits:number|null}|null;
  conflict:BaselineConflict|null;
  candidate:{value:string;agreement_count:number}|null;
  latest_raw:string|null;
  current_confirmed:string|null;
  reading:{enabled:boolean;monotonic:boolean;allow_rollover:boolean;max_rate_per_minute:number|null;decimal_position:number|null;expected_digits:number|null};
  alert_seconds:number;
  runtime_active:boolean;
};
export type BaselineEvent = {id:number;monitor_id:number;monitor_name:string;occurred_at:string|null;action:"reset"|"rebase"|"auto_semantic_reset"|string;old_value:string|null;old_confirmed_at:string|null;new_value:string|null;reason:string;operator:string;client_host:string;context:Record<string,unknown>};
export type ReadingDiagnostics = {
  enabled:boolean;
  mode:"majority"|"consecutive";
  consecutive_failures:number;
  recent_raw:RawReadingDiagnostic[];
  baseline?:{value:string|null;numeric_value:string;epoch:number;confirmed_at:string|null}|null;
  candidate?:{value:string;agreement_count:number}|null;
  conflict?:BaselineConflict|null;
  confirmed:{
    value:string|null;
    confidence:number|null;
    confirmed_at:string|null;
    raw_count:number;
    agreement_count:number;
    engine:string|null;
    validation_status:string|null;
    raw_value:string|null;
    raw_confidence:number|null;
  };
};

// --- 1時間ごとの計測記録 (reading_records、UI再設計 Phase 1〜3のAPI) ---
export type ValueSource = "confirmed"|"carried_forward"|"none";
export type ImageStatus = "not_saved"|"pending"|"ok"|"failed"|"dropped"|"disabled";
export type ReadingRecord = {
  id:number;monitor_id:number;monitor_name:string;hour_bucket:string;recorded_at:string;
  value:string|null;value_source:ValueSource;numeric_value:string|null;raw_value:string|null;previous_value:string|null;usage:string|null;
  confidence:number|null;validation_status:string|null;display_status:string;baseline_conflict:boolean;
  engine:string|null;model_id:string|null;original_image_path:string|null;overlay_image_path:string|null;image_status:ImageStatus;image_error:string|null;
};
export type RecordsPage = {items:ReadingRecord[];total:number;limit:number;offset:number};
export type RecordsQuery = {monitorIds:number[];from?:string;to?:string;limit:number;offset:number};
export type ExcelExportRequest = {monitor_ids:number[];from?:string;to?:string;save_to_server:boolean};
export type ExcelExportSaved = {saved:true;path:string;filename:string;folder:string;size_bytes:number;total_rows:number;sheets:{monitor_id:number;sheet_name:string;rows:number}[];image_links:number;image_links_skipped:boolean};

// --- データ保存設定 (system_settings、Phase 2/3のAPI) ---
export type DataStorageSettings = {
  image_root_folder:string|null;effective_image_root:string;excel_output_folder:string|null;effective_excel_output_folder:string;
  save_original_image:boolean;save_overlay_image:boolean;storage_warn_free_gb:number;storage_stop_free_gb:number;
};
export type DataStorageInput = Partial<{image_root_folder:string;excel_output_folder:string;save_original_image:boolean;save_overlay_image:boolean;storage_warn_free_gb:number;storage_stop_free_gb:number}>;
export type DataStorageState = "ok"|"warning"|"stopped"|"failing"|"disabled";
export type DataStorageStatus = {
  state:DataStorageState;image_root:string;image_root_is_default:boolean;save_original_image:boolean;save_overlay_image:boolean;
  free_gb:number|null;warn_free_gb:number;stop_free_gb:number;space:string;
  worker_running:boolean;queue_length:number;writing_seconds:number|null;circuit_open:boolean;counts:{ok:number;failed:number;dropped:number};
  last_success_at:string|null;last_error:string|null;last_error_at:string|null;last_free_bytes:number|null;
};
export type StorageTestResult = {ok:boolean;path:string|null;message:string;free_gb:number|null};
