#include "argus_cpp_onnx/nms.hpp"

#include <algorithm>
#include <cmath>

namespace argus_cpp_onnx {

namespace {

constexpr float kMaxWh = 7680.0f;

float iou_xyxy(const Detection& a, const Detection& b) {
  const float ix1 = std::max(a.x1, b.x1);
  const float iy1 = std::max(a.y1, b.y1);
  const float ix2 = std::min(a.x2, b.x2);
  const float iy2 = std::min(a.y2, b.y2);
  const float iw = std::max(0.0f, ix2 - ix1);
  const float ih = std::max(0.0f, iy2 - iy1);
  const float inter = iw * ih;
  const float area_a = std::max(0.0f, a.x2 - a.x1) * std::max(0.0f, a.y2 - a.y1);
  const float area_b = std::max(0.0f, b.x2 - b.x1) * std::max(0.0f, b.y2 - b.y1);
  const float uni = area_a + area_b - inter;
  return uni > 0.0f ? inter / uni : 0.0f;
}

}  // namespace

std::vector<Detection> decode_and_nms(const float* raw, int channels, int num_anchors,
                                       int num_classes, float conf_thres, float iou_thres,
                                       int max_det, bool agnostic) {
  (void)channels;
  std::vector<Detection> candidates;
  candidates.reserve(256);

  for (int a = 0; a < num_anchors; ++a) {
    float best_score = -1.0f;
    int best_cls = -1;
    for (int c = 0; c < num_classes; ++c) {
      const float score = raw[(4 + c) * num_anchors + a];
      if (score > best_score) {
        best_score = score;
        best_cls = c;
      }
    }
    if (best_score <= conf_thres) continue;

    const float cx = raw[0 * num_anchors + a];
    const float cy = raw[1 * num_anchors + a];
    const float w = raw[2 * num_anchors + a];
    const float h = raw[3 * num_anchors + a];

    Detection d;
    d.x1 = cx - w / 2.0f;
    d.y1 = cy - h / 2.0f;
    d.x2 = cx + w / 2.0f;
    d.y2 = cy + h / 2.0f;
    d.conf = best_score;
    d.cls = best_cls;
    candidates.push_back(d);
  }

  std::sort(candidates.begin(), candidates.end(),
            [](const Detection& a, const Detection& b) { return a.conf > b.conf; });

  std::vector<Detection> offset = candidates;
  if (!agnostic) {
    for (auto& d : offset) {
      const float off = static_cast<float>(d.cls) * kMaxWh;
      d.x1 += off; d.x2 += off; d.y1 += off; d.y2 += off;
    }
  }

  std::vector<bool> suppressed(candidates.size(), false);
  std::vector<Detection> kept;
  kept.reserve(std::min<size_t>(candidates.size(), static_cast<size_t>(max_det)));

  for (size_t i = 0; i < candidates.size() && static_cast<int>(kept.size()) < max_det; ++i) {
    if (suppressed[i]) continue;
    kept.push_back(candidates[i]);
    for (size_t j = i + 1; j < candidates.size(); ++j) {
      if (suppressed[j]) continue;
      if (iou_xyxy(offset[i], offset[j]) > iou_thres) suppressed[j] = true;
    }
  }
  return kept;
}

void scale_boxes_inplace(std::vector<Detection>& dets, double ratio, int pad_left, int pad_top,
                          int orig_h, int orig_w) {
  for (auto& d : dets) {
    d.x1 = static_cast<float>((d.x1 - pad_left) / ratio);
    d.y1 = static_cast<float>((d.y1 - pad_top) / ratio);
    d.x2 = static_cast<float>((d.x2 - pad_left) / ratio);
    d.y2 = static_cast<float>((d.y2 - pad_top) / ratio);
    d.x1 = std::clamp(d.x1, 0.0f, static_cast<float>(orig_w));
    d.x2 = std::clamp(d.x2, 0.0f, static_cast<float>(orig_w));
    d.y1 = std::clamp(d.y1, 0.0f, static_cast<float>(orig_h));
    d.y2 = std::clamp(d.y2, 0.0f, static_cast<float>(orig_h));
  }
}

}  // namespace argus_cpp_onnx
