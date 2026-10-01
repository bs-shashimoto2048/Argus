// Ultralytics `LetterBox`（auto=False, center=True, scale_fill=False, scaleup=True,
// stride=32, padding_value=114）の忠実な再移植。yolo_pipeline_studio Issue #48で
// 検証済みのロジックと同一（cpp/include/yps/letterbox.hpp参照、本fileはvendor複製）。
#pragma once

#include <opencv2/core.hpp>

namespace argus_cpp_onnx {

struct LetterBoxResult {
  cv::Mat image;
  double ratio = 1.0;
  int pad_left = 0;
  int pad_top = 0;
};

LetterBoxResult letterbox(const cv::Mat& img, int new_h, int new_w, int stride = 32,
                           int padding_value = 114);

}  // namespace argus_cpp_onnx
