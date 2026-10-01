# Argus - C++ ONNX Runtime inference worker (Issue #37)
#
# yolo_pipeline_studio Issue #47/#48で100% parity確認済みのDigital/Drum production
# ONNX推論を、Argus用の常駐workerプロセスとして再実装する。letterbox/NMS/座標逆変換の
# アルゴリズムはyolo_pipeline_studio cpp/（Issue #48）と同一ロジックを本repo内へ
# vendorしたもの（別repoへのクロスリポジトリ依存を避けるため、ソースを複製している。
# アルゴリズム変更時は両repoを手動で同期すること）。
#
# 依存はONNX Runtime C++とOpenCV C++のみ。vcpkg等のpackage managerは導入していない。
# 巨大binaryは一切Gitへcommitしない（third_party/はgitignore対象）。
# 取得・配置手順は docs/CPP_ONNX_INTEGRATION.md を参照。

cmake_minimum_required(VERSION 3.20)
project(argus_cpp_onnx_worker LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

if(MSVC)
  # ソース中の日本語コメント(UTF-8)が既定のシステムcodepageで誤解釈されるのを防ぐ
  # （yolo_pipeline_studio Issue #48の実ビルドで判明した問題と同じ対策）。
  add_compile_options(/utf-8)
endif()

set(THIRD_PARTY_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party" CACHE PATH
    "third-party dependency root (ONNX Runtime / OpenCV prebuilt)")
set(ORT_DIR "${THIRD_PARTY_DIR}/onnxruntime" CACHE PATH "ONNX Runtime C++ prebuilt root")
set(OpenCV_DIR "${THIRD_PARTY_DIR}/opencv2" CACHE PATH "OpenCV prebuilt root (contains OpenCVConfig.cmake)")

find_package(OpenCV REQUIRED)

find_path(ORT_INCLUDE_DIR onnxruntime_cxx_api.h PATHS "${ORT_DIR}/include" REQUIRED)
find_library(ORT_LIB onnxruntime PATHS "${ORT_DIR}/lib" REQUIRED)
set(ORT_DLL "${ORT_DIR}/lib/onnxruntime.dll")

add_library(argus_cpp_onnx_core
  src/letterbox.cpp
  src/nms.cpp
  src/model_profile.cpp
  src/onnx_model.cpp
)
target_include_directories(argus_cpp_onnx_core PUBLIC include "${ORT_INCLUDE_DIR}")
target_link_libraries(argus_cpp_onnx_core PUBLIC ${OpenCV_LIBS} "${ORT_LIB}")

add_executable(argus_cpp_onnx_worker src/worker_main.cpp)
target_link_libraries(argus_cpp_onnx_worker PRIVATE argus_cpp_onnx_core)

add_custom_command(TARGET argus_cpp_onnx_worker POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_if_different "${ORT_DLL}" "$<TARGET_FILE_DIR:argus_cpp_onnx_worker>"
  COMMAND ${CMAKE_COMMAND} -E copy_if_different "${ORT_DIR}/lib/onnxruntime_providers_shared.dll" "$<TARGET_FILE_DIR:argus_cpp_onnx_worker>"
)
if(WIN32)
  add_custom_command(TARGET argus_cpp_onnx_worker POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different "${OpenCV_DIR}/x64/vc16/bin/opencv_world4100.dll" "$<TARGET_FILE_DIR:argus_cpp_onnx_worker>"
  )
endif()
