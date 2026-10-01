// argus_cpp_onnx_worker: 常駐プロセス（Issue #37）。
//
// Argus backend（Python）からstdin/stdoutの長さプレフィックス付きフレーミングで
// 1フレームずつ受け取り、推論結果を返す。毎フレームprocess起動はしない
// （プロセス自体は1回起動され、複数リクエストを順番に処理し続ける）。
//
// Request（stdinから読む）:
//   [4 bytes LE uint32: header_json_len][header_json_len bytes: JSON]
//   [4 bytes LE uint32: payload_len][payload_len bytes: raw BGR pixel data, width*height*3]
// header JSON: {"profile":"digital"|"drum", "onnx_path":"...", "frame_id":"...",
//               "width":<int>, "height":<int>, "timestamp":<number, optional>}
//
// payloadは生のBGR24(HWC, uint8)ピクセルデータそのもの（JPEG等の圧縮を経由しない）。
// JPEG再encode/decodeを挟むと、カメラ由来の圧縮に加えて追加の非可逆劣化が生じ、
// production parityの僅かな破れに繋がることが実測で判明したため（Issue #37、
// 当初JPEGフレーミングで試作した際にconfidence差が最大0.015まで悪化した）、
// 可逆な生ピクセル転送に変更した。
//
// Response（stdoutへ書く）:
//   [4 bytes LE uint32: json_len][json_len bytes: JSON]
// response JSON: {"frame_id":..., "profile":..., "detections":[{"cls":,"class_name":,
//                 "conf":,"bbox":[x1,y1,x2,y2]}], "reading":<簡易reading、参考値>,
//                 "latency_ms":{"inference":,"postprocess":,"total":}, "error":null|"CODE"}
//
// onnx_pathごとにセッションを一度だけ構築しキャッシュする（毎推論load禁止、Issue #37 §35）。
// 1プロセスあたり同時に処理するリクエストは1件のみ（呼び出し元Python側が直列化する、
// Issue #37 §33/34方針）。
#include "argus_cpp_onnx/letterbox.hpp"
#include "argus_cpp_onnx/model_profile.hpp"
#include "argus_cpp_onnx/nms.hpp"
#include "argus_cpp_onnx/onnx_model.hpp"

#include <opencv2/imgproc.hpp>

#include <cctype>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace {

using Clock = std::chrono::high_resolution_clock;
double ms_since(Clock::time_point t0) {
  return std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
}

bool read_exact(std::istream& in, char* buf, size_t n) {
  in.read(buf, static_cast<std::streamsize>(n));
  return in.good() || (in.eof() && in.gcount() == static_cast<std::streamsize>(n));
}

bool read_u32(std::istream& in, uint32_t* out) {
  unsigned char b[4];
  if (!read_exact(in, reinterpret_cast<char*>(b), 4)) return false;
  *out = static_cast<uint32_t>(b[0]) | (static_cast<uint32_t>(b[1]) << 8) |
         (static_cast<uint32_t>(b[2]) << 16) | (static_cast<uint32_t>(b[3]) << 24);
  return true;
}

void write_u32(std::ostream& out, uint32_t v) {
  unsigned char b[4] = {static_cast<unsigned char>(v & 0xFF),
                        static_cast<unsigned char>((v >> 8) & 0xFF),
                        static_cast<unsigned char>((v >> 16) & 0xFF),
                        static_cast<unsigned char>((v >> 24) & 0xFF)};
  out.write(reinterpret_cast<char*>(b), 4);
}

// 制御された内部IPC用の最小限のJSON文字列値抽出（"key":"value" / "key":number）。
// 外部・未信頼入力ではなく、Python側プロセスが生成する既知の固定shapeのみを扱うため、
// 汎用JSON parserは導入しない（Issue #37 §16の範囲、過剰実装を避ける）。
std::string json_extract_string(const std::string& json, const std::string& key) {
  const std::string needle = "\"" + key + "\"";
  const auto pos = json.find(needle);
  if (pos == std::string::npos) return "";
  auto colon = json.find(':', pos + needle.size());
  if (colon == std::string::npos) return "";
  auto quote1 = json.find('"', colon);
  if (quote1 == std::string::npos) return "";
  auto quote2 = json.find('"', quote1 + 1);
  if (quote2 == std::string::npos) return "";
  return json.substr(quote1 + 1, quote2 - quote1 - 1);
}

int json_extract_int(const std::string& json, const std::string& key, int fallback = 0) {
  const std::string needle = "\"" + key + "\"";
  const auto pos = json.find(needle);
  if (pos == std::string::npos) return fallback;
  auto colon = json.find(':', pos + needle.size());
  if (colon == std::string::npos) return fallback;
  auto start = colon + 1;
  while (start < json.size() && (json[start] == ' ' || json[start] == '\t')) ++start;
  auto end = start;
  while (end < json.size() && (isdigit(static_cast<unsigned char>(json[end])) || json[end] == '-')) ++end;
  if (end == start) return fallback;
  try {
    return std::stoi(json.substr(start, end - start));
  } catch (...) {
    return fallback;
  }
}

std::string json_escape(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  for (char c : s) {
    if (c == '"' || c == '\\') out += '\\';
    out += c;
  }
  return out;
}

struct LoadedModel {
  argus_cpp_onnx::ModelProfile profile;
  std::unique_ptr<argus_cpp_onnx::OnnxModel> model;
};

std::map<std::string, LoadedModel>& model_cache() {
  static std::map<std::string, LoadedModel> cache;
  return cache;
}

LoadedModel& get_or_load(const std::string& onnx_path, const std::string& profile_name,
                         const std::string& provider) {
  auto& cache = model_cache();
  auto it = cache.find(onnx_path);
  if (it != cache.end()) return it->second;
  LoadedModel entry;
  entry.profile = argus_cpp_onnx::profile_by_name(profile_name);
  entry.model = std::make_unique<argus_cpp_onnx::OnnxModel>(onnx_path, provider);
  auto [inserted_it, _] = cache.emplace(onnx_path, std::move(entry));
  return inserted_it->second;
}

std::string process_frame(const std::string& header_json, const std::vector<unsigned char>& payload,
                           const std::string& provider) {
  const std::string profile_name = json_extract_string(header_json, "profile");
  const std::string onnx_path = json_extract_string(header_json, "onnx_path");
  const std::string frame_id = json_extract_string(header_json, "frame_id");
  const int width = json_extract_int(header_json, "width");
  const int height = json_extract_int(header_json, "height");

  std::ostringstream os;
  os << "{\"frame_id\":\"" << json_escape(frame_id) << "\",\"profile\":\""
     << json_escape(profile_name) << "\",";

  const auto t_total0 = Clock::now();
  try {
    LoadedModel& lm = get_or_load(onnx_path, profile_name, provider);

    // payloadは生のBGR24(HWC, uint8)ピクセルデータ(JPEG等の圧縮を経由しない、ヘッダ
    // コメント参照)。width*height*3とpayloadサイズが一致することを確認してから
    // コピーする(cv::Matはpayloadの生存期間に依存しないよう.clone()する)。
    if (width <= 0 || height <= 0 ||
        payload.size() != static_cast<size_t>(width) * static_cast<size_t>(height) * 3) {
      os << "\"detections\":[],\"reading\":null,\"latency_ms\":{},\"error\":\"INVALID_FRAME\"}";
      return os.str();
    }
    cv::Mat img = cv::Mat(height, width, CV_8UC3, const_cast<unsigned char*>(payload.data())).clone();
    if (img.empty()) {
      os << "\"detections\":[],\"reading\":null,\"latency_ms\":{},\"error\":\"INVALID_FRAME\"}";
      return os.str();
    }

    argus_cpp_onnx::LetterBoxResult lb =
        argus_cpp_onnx::letterbox(img, lm.profile.input_h, lm.profile.input_w);
    cv::Mat rgb, rgb_f32;
    cv::cvtColor(lb.image, rgb, cv::COLOR_BGR2RGB);
    rgb.convertTo(rgb_f32, CV_32F, 1.0 / 255.0);
    const int H = rgb_f32.rows, W = rgb_f32.cols;
    std::vector<float> tensor(static_cast<size_t>(3) * H * W);
    std::vector<cv::Mat> channels(3);
    for (int c = 0; c < 3; ++c)
      channels[c] = cv::Mat(H, W, CV_32F, tensor.data() + static_cast<size_t>(c) * H * W);
    cv::split(rgb_f32, channels);

    const auto t_inf0 = Clock::now();
    std::vector<int64_t> shape = {1, 3, H, W};
    argus_cpp_onnx::OnnxOutputInfo out_info;
    std::vector<float> raw = lm.model->run(tensor, shape, &out_info);
    const double inference_ms = ms_since(t_inf0);

    if (out_info.shape.size() != 3 || out_info.shape[0] != 1 ||
        static_cast<int>(out_info.shape[1]) - 4 != lm.profile.num_classes) {
      os << "\"detections\":[],\"reading\":null,"
         << "\"latency_ms\":{\"inference\":" << inference_ms << "},"
         << "\"error\":\"OUTPUT_SHAPE_MISMATCH\"}";
      return os.str();
    }

    const auto t_post0 = Clock::now();
    const int channels_out = static_cast<int>(out_info.shape[1]);
    const int anchors_out = static_cast<int>(out_info.shape[2]);
    auto dets = argus_cpp_onnx::decode_and_nms(raw.data(), channels_out, anchors_out,
                                                lm.profile.num_classes, lm.profile.conf,
                                                lm.profile.iou, lm.profile.max_det,
                                                lm.profile.agnostic_nms);
    argus_cpp_onnx::scale_boxes_inplace(dets, lb.ratio, lb.pad_left, lb.pad_top, img.rows,
                                        img.cols);

    // 簡易reading（参考値）: bbox中心x昇順でclass_idを連結する。Argus側の正式な
    // reading構成はPython側app.inference.meter_interpreter.interpret_digits()が
    // detections（本レスポンス）から行う（Issue #37 §25: 既存engineと同じ
    // input semanticsに合わせるため、dedup/decimal_position等のロジックを
    // C++側で重複実装しない）。
    std::vector<size_t> order(dets.size());
    for (size_t i = 0; i < dets.size(); ++i) order[i] = i;
    std::sort(order.begin(), order.end(), [&](size_t a, size_t b) {
      return (dets[a].x1 + dets[a].x2) < (dets[b].x1 + dets[b].x2);
    });
    std::string reading;
    for (size_t idx : order) reading += std::to_string(dets[idx].cls);
    const double postprocess_ms = ms_since(t_post0);
    const double total_ms = ms_since(t_total0);

    os << "\"detections\":[";
    for (size_t i = 0; i < dets.size(); ++i) {
      const auto& d = dets[i];
      if (i) os << ",";
      os << "{\"cls\":" << d.cls << ",\"class_name\":\"" << d.cls << "\",\"conf\":" << d.conf
         << ",\"bbox\":[" << d.x1 << "," << d.y1 << "," << d.x2 << "," << d.y2 << "]}";
    }
    os << "],";
    os << "\"reading\":" << (reading.empty() ? "null" : ("\"" + reading + "\"")) << ",";
    os << "\"latency_ms\":{\"inference\":" << inference_ms << ",\"postprocess\":" << postprocess_ms
       << ",\"total\":" << total_ms << "},";
    os << "\"error\":null}";
    return os.str();
  } catch (const std::exception& e) {
    std::ostringstream err;
    err << "{\"frame_id\":\"" << json_escape(frame_id) << "\",\"profile\":\""
        << json_escape(profile_name) << "\",\"detections\":[],\"reading\":null,"
        << "\"latency_ms\":{},\"error\":\"ORT_ERROR: " << json_escape(e.what()) << "\"}";
    return err.str();
  }
}

}  // namespace

int main(int argc, char** argv) {
  std::string provider = "cpu";
  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--provider" && i + 1 < argc) provider = argv[++i];
  }

#ifdef _WIN32
  // stdin/stdoutをバイナリモードへ固定する（Windows既定のテキストモードは
  // 0x0A/0x0D変換を行い、バイナリフレーミングを破損させるため）。
  _setmode(_fileno(stdin), _O_BINARY);
  _setmode(_fileno(stdout), _O_BINARY);
#endif

  std::cerr << "[argus_cpp_onnx_worker] ready, provider=" << provider << std::endl;

  while (true) {
    uint32_t header_len = 0;
    if (!read_u32(std::cin, &header_len)) break;  // EOF: 呼び出し元がstdinを閉じた(終了要求)
    std::string header(header_len, '\0');
    if (!read_exact(std::cin, header.data(), header_len)) break;

    uint32_t payload_len = 0;
    if (!read_u32(std::cin, &payload_len)) break;
    std::vector<unsigned char> payload(payload_len);
    if (payload_len > 0 && !read_exact(std::cin, reinterpret_cast<char*>(payload.data()), payload_len)) break;

    std::string response = process_frame(header, payload, provider);
    write_u32(std::cout, static_cast<uint32_t>(response.size()));
    std::cout.write(response.data(), static_cast<std::streamsize>(response.size()));
    std::cout.flush();
  }
  std::cerr << "[argus_cpp_onnx_worker] stdin closed, exiting" << std::endl;
  return 0;
}
