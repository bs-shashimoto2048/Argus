# C++ ONNX Inference Backend Integration（Issue #37）

yolo_pipeline_studio Issue #47/#48で100% parity確認済みのDigital/Drum production
ONNX推論（`production_combined_v2_5z` conf=0.60 tensor 1x3x384x640、
`candidate_roi_v4_hardneg` conf=0.80 tensor 1x3x160x640）を、Argusの既存
architecture（camera → runtime/scheduler → inference backend abstraction →
ReadingStabilizer → ConfirmedReading）へ、既存Python推論経路(`engine=ultralytics`)
をfallbackとして保持したまま統合したもの。

**このIssueではdefault backendをcpp_onnxへ切り替えていない。** 既定は引き続き
`engine=ultralytics`。cpp_onnxはMonitorごとに明示的に選択するexperimental
production candidateという位置づけ（詳細は「Migration status」節）。

## Architecture

```
camera
  ↓ (既存、変更なし)
VideoReader / MonitorRuntime / InferenceScheduler
  ↓ ROI crop + preprocess_service.apply()（既存、変更なし）
InferenceEngine.infer(image, settings)
  ├─ YoloInferenceEngine (engine=ultralytics)   既存、legacy fallback
  └─ CppOnnxInferenceEngine (engine=cpp_onnx)   Issue #37で新規追加
        ↓ 生BGR24ピクセルを長さプレフィックス付きIPCで送信
      argus_cpp_onnx_worker.exe（常駐C++ worker、1プロセスを全Monitorで共有）
        letterbox → ONNX Runtime(CPUExecutionProvider) → NMS → 座標復元
        ↓ detections(class/confidence/bbox)をJSONで返す
      app.inference.meter_interpreter.interpret_digits()（既存、再利用）
  ↓ (既存、変更なし)
ReadingStabilizer.update(InferenceResult) → ConfirmedReading
```

**ReadingStabilizer/ConfirmedReadingより後段は一切変更していない。** 変更したのは
`InferenceEngine.infer()`が「1フレームからdetectionを生成する部分」のみ。

## Build手順

third-party binary（ONNX Runtime/OpenCV）はGitへ一切commitしない
（`cpp/third_party/`はgitignore対象）。yolo_pipeline_studio Issue #48と同一手順。

```powershell
# ONNX Runtime C++ (CPU) 1.23.2 — Python側(onnxruntime 1.23.2)と完全一致
# https://github.com/microsoft/onnxruntime/releases/download/v1.23.2/onnxruntime-win-x64-1.23.2.zip
# 展開先: cpp/third_party/onnxruntime/

# OpenCV 4.10.0 (prebuilt Windows, vc16)
# https://github.com/opencv/opencv/releases/download/4.10.0/opencv-4.10.0-windows.exe
# 自己解凍7z。`opencv-4.10.0-windows.exe -o<dir> -y`で展開し、<dir>/opencv/build を
# cpp/third_party/opencv2/ へ配置（sources/は不要）。

cmake -S cpp -B cpp\build -A x64
cmake --build cpp\build --config Release
```

ビルド成果物（`cpp\build\Release\argus_cpp_onnx_worker.exe` + 依存DLL）はpost-build
で自動生成される。Argus backendはデフォルトでこのパスを参照する
（`ARGUS_CPP_ONNX_WORKER`環境変数で上書き可能、`backend/app/core/config.py`参照）。

## Model artifact配置

```
data/models/digital_production_v1.onnx   (gitignore対象、要手動配置)
data/models/drum_production_v1.onnx      (gitignore対象、要手動配置)
data/models/registry.json                (commit対象、path/sha256/profile/contract_versionを記録)
```

yolo_pipeline_studio側のexport済みONNX（`projects/meter_src002/exports/onnx/
digital_production_v1/model.onnx` 等）をコピーする。SHA256は
`data/models/registry.json`の`sha256`フィールドと一致している必要がある
（起動時チェック、後述）。

既存のArgus独自`meter_digits_v*.pt`系モデル（同一の物理Aichi Tokei gas meter向け、
Git管理下）とは完全に別系統。cpp_onnx統合はyolo_pipeline_studio由来の別モデルを
Argusのarchitectureで使えるようにするものであり、既存モデルを置き換えない。

## Startup validation

`CppOnnxInferenceEngine.__init__`が以下を同期的に確認する（Issue #37 §13）:

1. `data/models/registry.json`にmodel_idが登録されているか
2. `profile`が`digital`/`drum`のいずれかか
3. ONNXファイルが実在するか
4. SHA256が`registry.json`記載値と一致するか

**この段階の失敗はRuntime起動自体をクラッシュさせない。** `create_engine()`が
`CppOnnxEngineConfigError`を捕捉し、`InferenceResult(error="MODEL_NOT_CONFIGURED")`
を毎フレーム返す`_UnavailableEngine`へ差し替える（既存のYOLO/EasyOCR/Tesseract
backendと同じfail-safe方針）。ONNX Runtimeのsession構築自体の失敗（破損ファイル等）
は、実際に推論を試みた最初のフレームで`CPP_WORKER_ERROR`として表面化する。

## IPC protocol

常駐C++ workerプロセス（`argus_cpp_onnx_worker.exe`）1つを、`ModelRegistry`経由で
process全体として共有する（Monitorごとにプロセスを起動しない、Issue #37 §7/§35）。
リクエストはプロセス全体で直列化する（同時に2フレームを投げない、§33/§34）。
プロセスが異常終了した場合、次回呼び出し時に自動再起動する（engine選択自体は
変更しない、§15）。

```
request:  [4B LE u32 header_len][header JSON][4B LE u32 payload_len][raw BGR24 pixels]
header:   {"profile":"digital"|"drum","onnx_path":"...","frame_id":"...","width":W,"height":H}
response: [4B LE u32 json_len][response JSON]
response JSON: {"frame_id":...,"profile":...,
                "detections":[{"cls":,"class_name":,"conf":,"bbox":[x1,y1,x2,y2]}],
                "reading":<簡易reading、参考値>,
                "latency_ms":{"inference":,"postprocess":,"total":},
                "error":null|"CODE"}
```

**重要な設計変更の経緯**: 当初JPEGフレーミング（`cv2.imencode`→送信→`cv2.imdecode`）
で試作したところ、カメラ由来の圧縮に加えて追加の非可逆劣化が重なり、30サンプル中
28件でconfidence差が許容値(1e-3)を超え、1件はdetection countも実際に食い違った
（1件はreading自体も異なる結果になった）。原因を切り分けた結果、JPEG再encode/decode
の往復が原因と判明したため、**生のBGR24ピクセル転送へ変更**し、Python/ONNX側と
bit-identicalな結果（confidence差<=0.000001）を得られるようになった。カメラフレーム
をIPCで転送する設計では、この二重圧縮の罠に注意すること。

## Reading construction

C++ workerは`detections`（class/confidence/bbox）のみを返し、reading文字列の
構成は既存の`app.inference.meter_interpreter.interpret_digits()`を再利用する
（既存`YoloInferenceEngine`と同一のinput semantics、Issue #37 §25）。
dedup（重複bbox除去）・decimal_position挿入・confidence平均化は、この既存関数が
担う（C++側で重複実装しない）。

## Preprocessing（既知の制約）

ROI crop・resize・grayscale・sharpenは、既存の`InferenceScheduler`/
`preprocess_service.apply()`が行う（C++側では実装していない）。

**Argus既存のpreprocess実装（PIL, LANCZOS resize + 独自sharpen）は、
yolo_pipeline_studio production前処理（PIL BICUBIC + UnsharpMask）とは
アルゴリズムが異なり、ビット完全一致ではない。** Monitor側でgrayscale/sharpen/
resize=640を設定することで近似できるが、厳密なpixel-level parityは保証しない。

このため、本Issueのparity主判定（30+30件）は、**既にproduction前処理済みの
fixture画像をInferenceEngine.infer()へ直接渡す**方式で行った（Argus自身のROI/
preprocess_serviceをbypassする、yolo_pipeline_studio Issue #47と同じ方法論）。
実カメラ経由の end-to-end確認（後述）では、Argus既存のpreprocessingをそのまま
使い、「最終readingが正しいか」を確認した（pixel-level diffの確認は行っていない）。

## Parity結果（Digital/Drum 各30件、CPUExecutionProvider）

`backend/scripts/cpp_onnx_parity_check.py`で、Argusの実`CppOnnxInferenceEngine.
infer()`（ModelRegistry経由の常駐worker込み）と、yolo_pipeline_studio Issue #47の
Python ONNX Runtime参照実装を比較した。Test/Hard-Valは一切使用していない。

| | Digital | Drum |
|---|---|---|
| 件数 | 30/30 PASS | 30/30 PASS |
| reading一致 | 100% | 100% |
| detection count一致 | 100% | 100% |
| confidence最大差 | 0.000001 | 0.000001 |
| bbox最大差 | 0.001px | 0.000px |

## Integration latency（Argus統合後、worker自己申告値）

`argus_cpp_onnx_worker.exe`のJSONレスポンス`latency_ms`（letterbox〜NMS〜座標復元を
含むC++側実測値、IPC転送時間やPython側オーバーヘッドは含まない）を、同一fixture画像
へ繰り返し推論させて採取した（ウォームアップ2回を除く6回の平均）。

| | Digital (384x640) | Drum (160x640) | Issue #48参考値(単体C++ベンチ) |
|---|---|---|---|
| inference | 24.9ms | 10.5ms | <25ms / <20ms(両方analysis target) |
| postprocess | <0.1ms | <0.1ms | - |
| total(C++側) | 26.6ms | 11.1ms | - |

Digital/Drumともanalysis target範囲内。この値はONNX Runtime session threadingの
調整後（後述「CPU使用率」参照）のもの。Python↔C++間のIPC往復・JSON encode/decode・
生BGR24転送を含む「Argus `InferenceEngine.infer()`呼び出し全体」のend-to-endは、
フルフレーム(約640x480〜)を直接転送する条件でDigital 100〜180ms程度（IPC/JSON
オーバーヘッドが支配的）。ただし実運用では`InferenceScheduler`が先にROI crop/resize
済みの小さいフレームを渡すため、実際のIPC転送コストはこれより小さい
（本Issueでは個別に計測していない。残存リスクとして記載）。

いずれも`inference_fps=3`（約333ms間隔）に対して十分小さく、soak test中も
キュー滞留・推論遅延の兆候は観測されなかった。

## CPU使用率（発見した問題と対処）

Regression/soak検証中、`argus_cpp_onnx_worker.exe`が**推論していない間も**
常時CPUを大量消費していることを発見した（`Get-Counter '\Process(...)\% Processor
Time'`で実測、32論理コア機で約2297%＝23コア相当が常時busy）。原因は
`Ort::SessionOptions::SetIntraOpNumThreads(0)`（自動）が32コア分のintra-opスレッド
プールを生成し、ONNX Runtimeの既定spin-wait挙動と組み合わさって、アイドル中も
スレッドがbusy pollingし続けていたこと。

対処として`onnx_model.cpp`のSessionOptionsを変更した:

```cpp
session_options_.SetIntraOpNumThreads(2);
session_options_.SetInterOpNumThreads(1);
session_options_.AddConfigEntry("session.intra_op.allow_spinning", "0");
session_options_.AddConfigEntry("session.inter_op.allow_spinning", "0");
```

IPC側で既にリクエストを直列化しており（`cpp_worker_process.py`の`threading.Lock`）
同時に複数フレームを処理しないため、大きなintra-opスレッドプールは不要。対処後、
実soak環境下での継続CPU使用率は約14.3%（1コア換算）まで低下し（約160分の1）、
30+30parityは全件bit-identicalのまま変化なし（スレッド数変更が数値結果に影響
しないことを確認済み）。スレッド数は1でも動作確認済みだが、2の方がDigital推論を
約45ms→約25msへ改善できたため最終的に2を採用した。

この問題はIssue #37で新規に発見したものであり、yolo_pipeline_studio Issue #48の
単体C++ベンチマークでは（常駐プロセスではなく都度起動だったため）表面化していな
かった。常駐worker特有の問題として本Issueで修正したことを明記する。

## 実カメラ確認

物理的なDigital/Drum計器カメラは本環境に接続されていないため、yolo_pipeline_studio
で実際にカメラ撮影された生画像（`projects/meter_src002/raw/images/`）を、ローカル
HTTP MJPEGサーバー（`multipart/x-mixed-replace`、標準的なIPカメラと同一プロトコル）
でループ配信し、Argusの**実VideoReader（cv2.VideoCaptureでHTTP URLを開く、モック
無し）**で接続・推論した。

確認手順:
1. ローカルMJPEGサーバーを起動（`http://127.0.0.1:<port>/stream`）
2. Argus Monitorを作成し、`source.source_type="url"`でそのURLへ接続
3. `inference.engine="cpp_onnx"`、`model_id="digital_production_v1.onnx"`を設定
4. Monitor.status→`running`（実接続成功）、Monitor.current_value→実際の
   ConfirmedReading値が確定することを確認

結果: 接続・推論・ReadingStabilizer・ConfirmedReadingまで正常に動作し、
`current_value`に妥当な7桁readingが確定することを確認した。

## Soak test

実MJPEGサーバー(`http://127.0.0.1:18765/stream`、実カメラ撮影済みDigital画像を
ループ配信)に接続したMonitor(`engine=cpp_onnx`, `inference_fps=3`)を、複数区間に
分けて連続稼働させた:

| 区間 | 継続時間 | 終了理由 |
|---|---|---|
| 1回目(reboot前) | 約52分 | ホストPCの強制終了（作業とは無関係の外部要因、下記参照） |
| 2回目(reboot後、回帰検証用) | 約69分 | CPU使用率の問題を修正するためworkerを計画的に再起動 |
| 3回目(CPU修正後、最終ビルド) | 継続中（本レポート作成時点で稼働確認済み） | - |

結果（全区間共通）:
- worker再起動回数: 2回（いずれもこちらが意図的に停止・再ビルドのため再起動したもの。
  予期しないクラッシュによる自動再起動は観測していない）
- crash: 無し（worker process自体は一度も異常終了していない）
- memory: worker working set 約83〜94MB の範囲で推移、増加トレンド無し（リーク無し）
- inference error数: 0件（`current_inference_error`は全期間`null`）
- queue growth: 観測した範囲では無し（`last_updated`は`inference_fps`間隔どおり更新され続けた）
- latency劣化: 無し（区間間でworker自己申告latencyに有意な変化無し）

## ホストPC強制終了について

作業中にホストPCが強制終了・再起動する事象が発生した。再起動後に以下を確認し、
今回のC++統合が原因である証拠は無いと判断した（`host reboot/interruption`として
記録、Issue #37実装起因とは断定しない）:

- リポジトリ: 再起動前の未commit変更（`git status --short`の対象ファイル一覧）が
  完全に保持されていた
- worker: 再ビルド無しでそのまま正常起動
- model: Digital/Drum ONNXのSHA256が`registry.json`記載値と完全一致
- inference: 再起動後、Digital fixtureで`0215234`、Drum fixtureで`3718333`と、
  再起動前と完全一致するreadingを得られた（上記「Parity結果」の値と同一）
- Argus本体: enabled状態のMonitorがFastAPI lifespan hookにより自動再開し、
  DB(WAL)も壊れていなかった

## Regression（per-file/full-suite）

`backend/tests`配下39ファイルすべてを個別プロセス（ファイル単位でfresh pytest
subprocess）で実行した。結果:

- 37/39ファイル: 単体実行でPASS（うち2ファイルはバッチ実行スクリプト自身の
  タイムアウト設定が短すぎただけで、個別に十分な時間を与えて再実行すると
  PASSした。実際の機能不全ではない）
- 2/39ファイル（`test_monitor_basic_info_update.py`, `test_monitors.py`）:
  "Windows fatal exception: access violation" で異常終了/タイムアウト。
  いずれも`cpp_onnx`を一切参照しないファイル（grep確認済み）で、スタック
  トレースはArgus既存の`monitor_runtime.py`/`inference_scheduler.py`の
  カメラ/スレッド処理、またはFastAPI TestClientのshutdown経路
  （`anyio`/`starlette.testclient`）の中で発生していた。

### clean main比較（原因切り分け）

`git stash -u`で本Issueの変更を完全に除去し、vanilla `main`(fb34dae)で同じ
`test_monitors.py`/`test_monitor_basic_info_update.py`を実行したところ、**同一の
"Windows fatal exception: access violation"がほぼ同じ位置で再現した**。この後
`git stash pop`で変更を復元し、`git status --short`が復元前と完全一致することを
確認した。

このことから、本crashは**Issue #37のC++統合が新規に持ち込んだものではなく、
既存Argusのnative/thread/camera runtime lifecycle起因の、既存open Issue
「#15 Isolate Monitor Video Runtimes to Prevent Native FFmpeg/OpenCV Crashes」と
同じ既知カテゴリの問題**と判断する。個別ファイル実行ではこの2ファイルを含め
全39ファイルが最終的にPASSしており、本Issueのblockerとはしない。

## Migration status

- `legacy_python`（`engine=ultralytics`）: 既存のfallback。既定値のまま維持。
- `cpp_onnx`（`engine=cpp_onnx`）: Issue #37で追加したproduction candidate。
  Monitorごとに明示的に選択する。Issue #38でMonitor詳細画面の「推論設定」から選択できる
  ようになった（下記「Monitor設定UI」）。
- **default backendはcpp_onnxへ切り替えていない。** 既定は引き続き`ultralytics`。
  default切替・production昇格は、物理Digital/Drum cameraのacceptance完了後に別判断する。

## Monitor設定UI（Issue #38）

Monitor詳細画面 → 推論設定（Object Detection時）で「実行エンジン」を選択する。

- **Ultralytics（既定）**: 従来どおり。モデル候補はcpp_onnx専用ONNXを除いた一覧。
  registry未登録の自由入力model pathの互換は維持。Conf/IoU/ImageSize/Deviceは編集可能。
- **C++ ONNX**: モデルは`digital_production_v1.onnx` / `drum_production_v1.onnx`の2件のみ。
  - Conf/IoUはモデル選択時にproduction profile（Digital 0.60/0.70、Drum 0.80/0.70）へ
    自動設定され、編集不可（C++ worker側でprofile固有thresholdが適用されるため）。
  - ImageSizeはprofile固定shape（Digital 1x3x384x640 / Drum 1x3x160x640）、
    DeviceはCPU（CPUExecutionProvider固定）として表示し、編集不可。既存DB値は書き換えない。
    cpp_onnx runtimeではprofile値が正式値。
  - ROIはROIそのものを切り出して推論する（ROIモードは適用されない）。
- engine切替時は`model_id`をnullへ戻し、互換しないmodelを残さない。

Backend validation（`monitor_service._validate_engine_model`、保存時、違反は400
`INVALID_ENGINE_MODEL`）:

- `cpp_onnx` + model_idなし / PT / registry未登録 / profileがdigital・drum以外 → 拒否
- `ultralytics` + cpp_onnx専用ONNX → 拒否
- ONNXファイル欠落・SHA256不一致は保存時には拒否せず、実行時の`MODEL_NOT_CONFIGURED`
  として扱う（上記Startup validation）。UIではengine別の文言で表示する。

## Runner/環境

- Python: Argus backend .venv（Python 3.12.8）
- C++: MSVC 19.43.34809.0 / CMake 3.30.5-msvc23（yolo_pipeline_studio Issue #48と同一toolchain）
- ONNX Runtime: 1.23.2（CPUExecutionProvider、CUDAは本Issueでは統合しない。Issue #37
  §8/§9の方針どおりCPUをbaselineとする）
- GPU self-hosted runnerは登録していない（Issue #37 §4禁止事項）

## 既知の制約・次候補

- `MODEL_NOT_CONFIGURED`は、モデル未配置・registry未登録・SHA256不一致を区別せず返す。
- CUDAExecutionProviderは統合していない（CPUをbaselineとする方針、将来必要になれば
  yolo_pipeline_studio Issue #48で検証済みの実装をそのまま流用できる）。
- Preprocessing（resize/sharpen）はArgus既存実装とyolo_pipeline_studio production
  実装でアルゴリズムが異なり、ビット完全一致ではない（上記「Preprocessing」参照）。
- 1 worker processを全Monitor/全profileで共有する設計のため、同時に大量の
  Monitorがcpp_onnxを使う場合はリクエストが直列化され、スループットが低下し得る
  （Issue #37 §33の方針により、本Issueでは並列化・複数worker化を行っていない）。
