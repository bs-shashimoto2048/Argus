#include "argus_cpp_onnx/onnx_model.hpp"

#include <stdexcept>

namespace argus_cpp_onnx {

namespace {
std::wstring to_wide(const std::string& s) { return std::wstring(s.begin(), s.end()); }
}  // namespace

OnnxModel::OnnxModel(const std::string& onnx_path, const std::string& provider)
    : env_(ORT_LOGGING_LEVEL_WARNING, "argus_cpp_onnx_worker"), provider_(provider) {
  // IntraOpNumThreads(0)=自動だと32コア機でスレッドプールが肥大化し、ORTの既定spin-wait
  // 挙動と合わさって推論していない間も常時数コアをビジーポーリングし続ける実測結果になった
  // (Issue #37レグレッション検証中に発見)。IPC側で既にリクエストを直列化しており
  // (cpp_worker_process.pyのthreading.Lock)1リクエストずつしか処理しないため、intra-op並列は
  // 不要。1に固定しspinningも無効化して、アイドル時はスレッドをスリープさせる。
  session_options_.SetIntraOpNumThreads(2);
  session_options_.SetInterOpNumThreads(1);
  session_options_.AddConfigEntry("session.intra_op.allow_spinning", "0");
  session_options_.AddConfigEntry("session.inter_op.allow_spinning", "0");
  session_options_.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);

  if (provider == "cuda") {
    OrtCUDAProviderOptions cuda_opts{};
    cuda_opts.device_id = 0;
    session_options_.AppendExecutionProvider_CUDA(cuda_opts);
  } else if (provider != "cpu") {
    throw std::runtime_error("unsupported provider: " + provider);
  }

  session_ = Ort::Session(env_, to_wide(onnx_path).c_str(), session_options_);
  memory_info_ = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);

  Ort::AllocatorWithDefaultOptions allocator;
  input_name_ = session_.GetInputNameAllocated(0, allocator).get();
  output_name_ = session_.GetOutputNameAllocated(0, allocator).get();
}

std::vector<float> OnnxModel::run(const std::vector<float>& input_nchw,
                                   const std::vector<int64_t>& input_shape,
                                   OnnxOutputInfo* out_info) {
  Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
      memory_info_, const_cast<float*>(input_nchw.data()), input_nchw.size(),
      input_shape.data(), input_shape.size());

  const char* input_names[] = {input_name_.c_str()};
  const char* output_names[] = {output_name_.c_str()};

  auto outputs = session_.Run(Ort::RunOptions{nullptr}, input_names, &input_tensor, 1,
                               output_names, 1);

  Ort::Value& out = outputs[0];
  auto out_shape_info = out.GetTensorTypeAndShapeInfo();
  std::vector<int64_t> shape = out_shape_info.GetShape();
  const size_t count = out_shape_info.GetElementCount();
  const float* data = out.GetTensorData<float>();

  if (out_info) {
    out_info->name = output_name_;
    out_info->shape = shape;
  }
  return std::vector<float>(data, data + count);
}

}  // namespace argus_cpp_onnx
