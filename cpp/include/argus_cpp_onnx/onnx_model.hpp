#pragma once

#include <onnxruntime_cxx_api.h>

#include <string>
#include <vector>

namespace argus_cpp_onnx {

struct OnnxOutputInfo {
  std::string name;
  std::vector<int64_t> shape;
};

class OnnxModel {
 public:
  // provider: "cpu" | "cuda"（Issue #37ではcpuをbaselineとする。cudaはyolo_pipeline_studio
  // Issue #48で検証済みの実装をそのまま流用できるよう残してある）。
  OnnxModel(const std::string& onnx_path, const std::string& provider);

  std::vector<float> run(const std::vector<float>& input_nchw,
                          const std::vector<int64_t>& input_shape, OnnxOutputInfo* out_info);

 private:
  Ort::Env env_;
  Ort::SessionOptions session_options_;
  Ort::Session session_{nullptr};
  Ort::MemoryInfo memory_info_{nullptr};
  std::string input_name_;
  std::string output_name_;
  std::string provider_;
};

}  // namespace argus_cpp_onnx
