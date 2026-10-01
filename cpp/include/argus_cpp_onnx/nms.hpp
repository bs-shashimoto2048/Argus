// Ultralytics `ultralytics.utils.nms.non_max_suppression`相当（best class onlyパス、
// multi_label=False）。yolo_pipeline_studio Issue #48検証済みロジックのvendor複製。
#pragma once

#include <string>
#include <vector>

namespace argus_cpp_onnx {

struct Detection {
  float x1, y1, x2, y2;  // xyxy
  float conf;
  int cls;
};

// raw: ONNX生出力 [4+num_classes, num_anchors] をrow-majorでflattenしたもの（batch=1）。
// 戻り値のbboxはletterbox座標系。
std::vector<Detection> decode_and_nms(const float* raw, int channels, int num_anchors,
                                       int num_classes, float conf_thres, float iou_thres,
                                       int max_det, bool agnostic);

// Ultralytics `scale_boxes`相当: letterbox座標系 -> 元画像座標系。
void scale_boxes_inplace(std::vector<Detection>& dets, double ratio, int pad_left, int pad_top,
                          int orig_h, int orig_w);

}  // namespace argus_cpp_onnx
