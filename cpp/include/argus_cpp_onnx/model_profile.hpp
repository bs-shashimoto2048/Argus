// production_deployment_baseline_v1（yolo_pipeline_studio Issue #47）/
// CPP_DEPLOYMENT_CONTRACT.md の契約値。Argus側はROI/resize/grayscale/sharpenを
// 既存のpreprocess_service/ROI機構で行うため（Issue #37 §25「既存input semantics」
// 方針）、ここではletterbox以降（ONNX input shape/NMS/confidence）のみを持つ。
#pragma once

#include <string>

namespace argus_cpp_onnx {

struct ModelProfile {
  std::string name;        // "digital" | "drum"
  int input_h = 0;         // Digital=384, Drum=160（非正方形rect shape、固定）
  int input_w = 640;
  int num_classes = 10;
  float conf = 0.0f;       // Digital=0.60, Drum=0.80
  float iou = 0.70f;
  int max_det = 300;
  bool agnostic_nms = false;
};

ModelProfile digital_profile();
ModelProfile drum_profile();
ModelProfile profile_by_name(const std::string& name);  // 不明な名前は例外

}  // namespace argus_cpp_onnx
