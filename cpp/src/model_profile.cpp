#include "argus_cpp_onnx/model_profile.hpp"

#include <stdexcept>

namespace argus_cpp_onnx {

ModelProfile digital_profile() {
  ModelProfile p;
  p.name = "digital";
  p.input_h = 384;
  p.input_w = 640;
  p.num_classes = 10;
  p.conf = 0.60f;
  p.iou = 0.70f;
  p.max_det = 300;
  p.agnostic_nms = false;
  return p;
}

ModelProfile drum_profile() {
  ModelProfile p;
  p.name = "drum";
  p.input_h = 160;
  p.input_w = 640;
  p.num_classes = 10;
  p.conf = 0.80f;
  p.iou = 0.70f;
  p.max_det = 300;
  p.agnostic_nms = false;
  return p;
}

ModelProfile profile_by_name(const std::string& name) {
  if (name == "digital") return digital_profile();
  if (name == "drum") return drum_profile();
  throw std::runtime_error("unknown profile: " + name);
}

}  // namespace argus_cpp_onnx
