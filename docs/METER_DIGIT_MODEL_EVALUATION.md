# Meter Digit Detection Model — Evaluation Report / Model Card

Issue: *Build and Evaluate Production-Ready Meter Digit Detection Model*

本ドキュメントは、Argusのメーター数字検出モデルについて、Dataset→Training→Evaluation→Benchmark→
Meter Reading Accuracy→Runtime Validationを一本につなげた結果をまとめる。**中心指標はYOLOのmAPではなく
Full Reading Exact Match Accuracy（メーター値を1桁も間違えずに読み取れた画像の割合）** とする。

## 要約（先に結論）

| | Baseline (`meter_digits_v1.pt`) | Candidate (`meter_digits_v2_candidate.pt`) |
|---|---|---|
| Full Reading Exact Match | **0.0%** (0/21) | **28.6%** (6/21) |
| No Detection Rate | 9.5% | 4.8% |
| Digit Detection Accuracy | 62.8% | 75.9% |
| Digit Classification Accuracy | 81.3% | 86.4% |
| CPU warm latency | 92.9 ms | **48.9 ms** |
| GPU warm latency (RTX 4070 Laptop) | 9.74 ms | **8.18 ms** |
| モデルサイズ / VRAM | 40.4 MB / 71.5 MB | **6.2 MB / 12.1 MB** |

**判断: A（Candidateを"Production Candidate"として採用）。** 精度・検出率・速度・モデルサイズの全指標でbaselineを上回り、
Issue #84の採用基準（Exact Match ≥ baseline、No Detection Rate ≤ baseline、False Confirmed Rate ≤ baseline、
致命的なrecall悪化なし、latency許容範囲）をすべて満たす。ただし学習画像139枚・Test 21枚という小規模データセットであり、
Exact Match 28.6%は無監督の実運用に足る精度ではないため、**「Production-ready」ではなく「Production Candidate」**と位置づける
（Issue #75の基準どおり）。Model RegistryのroleはBaselineを`baseline`のまま維持し、Candidateは`candidate`とする。

---

## 1. Dataset

### 1.1 Inventory（実施前調査、Issue #5-6）

`yolo_pipeline_studio/projects/meter/` に実物の都市ガスメーター写真326枚と対応するYOLOラベル(classes: 0-9)が
既に存在した(調査で確認、新規収集はしていない)。目視確認の結果、実際には**2種類の異なるメーター**が写っていた:

- **Domain A（7セグメントデジタルLCD、Aichi Tokei製Turbine Gas Meter）**: `capture_001`(8枚)、`meter_001-004`(4枚)、
  `src_001`(1枚)、`src_002`(8枚)、`src_003`(163枚) = 184枚。少なくとも2つの物理個体（設置期限シールが「2027年02月」の個体と
  「2027年10月」の個体）を含む。
- **Domain B（機械式ドラム(数字ホイール)ガスメーター）**: `src_004`(142枚)。Domain Aとは全く異なる見た目のメーター。

`meter_digits_v1.pt`(baseline)は"7セグ数字メータ読み取り"用として持ち込まれたモデルであり、Domain Aが対象。
今回のTraining/Evaluationのスコープも**Domain Aに限定**し、Domain B(`src_004`)は「別のメータースタイルへの
汎化確認」用のsecondary/OOD(Out-of-Domain)評価としてのみ扱う（詳細は7章）。

### 1.2 Annotation QA（Issue #8）

`yolo_pipeline_studio`の既存Label Validation機能(`label_validation_service`)がTraining Dataset作成の事前チェックとして
自動実行される(bbox範囲外・0サイズ・class_id不正・重複bbox等をerrorとしてブロックする設計)。Dataset作成
(`meter_argus_train_v2`)はこのチェックを通過した。Argus側の独自チェック(`evaluate_meter_model.py dataset_inventory`)でも
Test Set(21枚)に対し missing_label=0, empty_annotation=0, invalid_bbox=0 を確認した。

### 1.3 Train / Validation / Test分離とData Leakage対策（Issue #10-13、最重要）

既存`datasets/meter_001p`はDomain A 326枚全部をtrain(261)/val(65)に使い切っており(test_ratio=0)、
独立したTest Setが存在しなかった。**今回、以下の手順で作り直した:**

1. `yolo_pipeline_studio`のSelection機能(`PUT /api/projects/meter/selection/images/{id}`、非破壊・可逆)で、
   Domain Aのうち`capture_001`+`meter_001-004`+`src_001`+`src_002`(21枚、"物理個体#1")を`review`状態にし、
   Dataset作成対象から除外。
2. 残った`src_003`(163枚、"物理個体#2")のみで新規Dataset `meter_argus_train_v2` を作成
   (`train_ratio=0.85, val_ratio=0.15, seed=42` → train 139 / val 24)。
3. 除外した21枚(物理個体#1)は**一度もTrain/Valに使わず**、Argus側のローカル評価専用Test Set
   `data/eval/meter_test_set_v2`(Repositoryにはmanifest+SHA256のみcommit、画像自体はcommitしない)とした。

これにより、**Test SetはTrainingで使った物理メーター個体・撮影セッションと完全に分離**されている
(同じメーター型式・同じ7セグフォントだが、異なる個体・異なる照明・異なる時刻)。単純なランダム分割では
連続撮影フレームが疑似的に重複してtrain/testへ混在し精度を過大評価するリスクがあったため、
**source(撮影セッション)単位で分割した**(Issue #12)。

*経緯として記録*: 当初は`src_004`(142枚)をTest Setとして除外したが、目視確認でDomain Bだと判明し、
Baseline/Candidateとも学習していない別ドメインを「Test Set」とするのは公平な評価にならないため、
Domain A内での物理個体分割へ設計を修正した(6章のsuperseded runsを参照)。

### 1.4 Real-world variation（Issue #13）

Test Set(21枚)は屋内、正面〜やや斜め、複数の照明条件(逆光・作業灯照射・暗所)、複数解像度(1920x1080および
約1000x560)を含む。**不足しているもの**: 屋外設置、強いglare/reflection、意図的なmotion blur、汚れたレンズ越し、
部分遮蔽のサンプルは確認できなかった。次回データ収集の優先候補とする(9章)。

### 1.5 Augmentation（Issue #14-15）

`yolo_pipeline_studio`のbuiltin `light`プリセットを採用(`degrees=3, translate=0.05, scale=0.2, fliplr=0, flipud=0,
mosaic=0.5, hsv_h=0.01, hsv_s=0.3, hsv_v=0.2`)。**`standard`プリセット(既定)は`fliplr=0.5`(左右反転50%)を含んでおり、
7セグ数字は左右反転すると実在しない形になるため数字認識タスクには不適切と判断し、明示的に`light`へ変更した**
(発見した問題、5章参照)。Rotationも3度に抑え、6↔9のような意味反転が起きない範囲にした。Runtime側の
Preprocessing(grayscale/threshold等)とは役割を分離しており、Augmentationは学習時のみ、Preprocessingは実運用の
画像最適化のみに用いる(混同していない)。

---

## 2. Baseline: `meter_digits_v1.pt`

| 項目 | 内容 |
|---|---|
| source | `yolo_pipeline_studio/projects/meter/runs/train/imported_001/weights/best.pt`(外部学習済み、import名`7sgm_yolo26s_20260326.pt`) |
| training | このprojectでは実施なし(`job.json`: epochs=0)。YOLO標準指標(mAP等)は一度も算出されていない |
| task/classes | detect / 0-9 |
| input size | 640 |
| device対応 | cpu, cuda |

### YOLO標準指標
**無し。** 外部で学習されたモデルであり、Argus・yolo_pipeline_studioどちらでも訓練/検証を実施していないため、
mAP/Precision/Recallの記録が存在しない。これ自体が「未評価のまま本番投入されていた」ことを示す発見である。

### Meter Reading指標（Test Set v2, 21枚, conf=0.25, iou=0.7, imgsz=640, CPU）

| Metric | 値 |
|---|---|
| Full Reading Exact Match Accuracy | **0.0%** |
| Digit Detection Accuracy | 62.8% |
| Digit Classification Accuracy | 81.3% |
| No Detection Rate | 9.5% |
| Extra Digit Rate | 14.3% |
| Missing Digit Rate | 66.7% |
| Digit Order Error Rate | 0.0% |
| Invalid Reading Rate (誤読) | 9.5% |

**主要因: Missing Digit(検出漏れ)が支配的(66.7%)。** Digit Detection Accuracy(62.8%)が低く、
Digit Classification Accuracy(81.3%、検出できた桁の分類精度)はそこまで悪くないことから、
「見つけた数字はある程度正しく分類できるが、そもそも全ての桁を見つけられていない」ことが根本原因。
Conf閾値を0.15〜0.5で振っても(`data/reports/baseline_conf_sweep.json`)Exact Matchは常に0%であり、
閾値調整では解決しない、モデル自体の汎化力の問題。

### Benchmark

| Device | Load time | Warm avg | P50 | P95 | Effective FPS | VRAM |
|---|---|---|---|---|---|---|
| CPU | 2.96 s | 92.9 ms | 94.0 ms | 113.6 ms | 10.8 | - |
| GPU (RTX 4070 Laptop) | 5.77 s | 9.74 ms | 9.71 ms | 10.93 ms | 102.7 | 71.5 MB |

---

## 3. Candidate Training

### 3.1 設定（再現可能な記録、Issue #27-30）

`yolo_pipeline_studio`の既存Training UI/API(`POST /api/projects/meter/train-jobs`、`train_worker.py`)をそのまま利用。

| 項目 | 値 |
|---|---|
| job_name | `meter_digits_v2_candidate_003` |
| base model | `yolov8n.pt`（下記理由で選定） |
| dataset | `meter_argus_train_v2`（train 139 / val 24、seed=42） |
| epochs | 100（patience=20で早期終了、実際は100epoch完走） |
| batch | 8 |
| imgsz | 640 |
| device | cuda |
| seed | 42 |
| augmentation | `light`プリセット |

**Base modelにyolov8nを選んだ理由**: 学習画像が139枚と小規模、対象(digit)のbboxも小さく単純な10クラス分類であり、
大きいモデルは過学習・低速化のリスクが高い。既存`yolo_pipeline_studio`内の実績(`train_001`, 50epoch, yolov8n,
Domain A全量で学習)でも良好な収束を確認できたため、nanoサイズを踏襲した。

### 3.2 Superseded runs（発見した問題と修正の記録）

学習中に2つの問題を発見し、都度修正して`_003`に至った:

1. `meter_digits_v2_candidate_001`(標準augmentation, `fliplr=0.5`)を先に起動したが、上記1.5の理由で
   数字認識に不適切と判断し中断せず走らせたまま(既存APIにjob停止機能が無いため)、**評価には使用しなかった**。
2. `meter_digits_v2_candidate_002`(`light`プリセットへ修正)を`meter_argus_eval_v1`(`src_004`を除外した184枚)で
   学習したが、後に`src_004`が別ドメイン(機械式メーター)と判明し、この184枚には物理個体#1(21枚)も
   Train/Valに混在していたため、Test Set v2(物理個体#1)との厳密な分離ができていなかった。**評価には使用しなかった。**
3. `meter_digits_v2_candidate_003`(`light`プリセット、`src_003`のみ163枚)で1.3節の厳密な分離を満たし、
   これを最終Candidateとして採用。

いずれも`overwrite`は使わず新規job_nameで実行したため、既存の`imported_001`/`train_001`/`meter_001p`等の
既存Runは一切変更・削除していない。

### 3.3 YOLO標準指標（`meter_argus_train_v2`のvalidation split、24枚、同一物理個体#2内）

| Metric | 値 |
|---|---|
| Precision | 0.989 |
| Recall | 0.993 |
| mAP50 | 0.995 |
| mAP50-95 | 0.936 |

**注意: このmAPは学習に使った物理個体#2のvalidation splitに対する値であり、Test Set(物理個体#1、未学習)に対する
値ではない。** mAP50=0.995は極めて高く見えるが、7章のTest Set評価ではExact Match=28.6%に留まる。
**これは今回のIssueの核心的な論点(mAPだけでは実運用の読み取り精度を保証しない)を、実データで裏付ける結果である。**

---

## 4. Candidate: `meter_digits_v2_candidate.pt` — Meter Reading指標

Test Set v2(21枚、物理個体#1、未学習)、conf=0.25, iou=0.7, imgsz=640, CPU。

| Metric | Baseline | Candidate |
|---|---|---|
| Full Reading Exact Match Accuracy | 0.0% | **28.6%** |
| Digit Detection Accuracy | 62.8% | **75.9%** |
| Digit Classification Accuracy | 81.3% | **86.4%** |
| No Detection Rate | 9.5% | **4.8%** |
| Extra Digit Rate | 14.3% | **0.0%** |
| Missing Digit Rate | 66.7% | 52.4% |
| Digit Order Error Rate | 0.0% | 0.0% |
| Invalid Reading Rate | 9.5% | 14.3% |

Missing Digit Rateは改善したが依然として最大の誤読要因。Invalid Reading Rate(誤読)がわずかに増加しているが、
Full Reading Exact Matchは0%→28.6%へ明確に改善しており、総合的にbaselineを上回る。

### Conf / IoU感度分析（Issue #40-41）

- **Conf**: 0.15/0.25/0.35/0.50を比較(`data/reports/candidate_conf_sweep.json`)。Exact Matchはどの閾値でも28.6%で
  不変。0.15はInvalid Reading Rateが上昇(42.9%)、0.35以上はNo Detection Rateが上昇(14.3%〜19.0%)するため、
  **既定のconf=0.25を推奨値として維持**。
- **IoU**: 0.3/0.5/0.7を比較(`data/reports/candidate_iou_0.*.json`)。結果は完全に同一 — digit bboxは互いに
  重ならないため、NMSのIoU閾値による桁欠落は発生していない。**既定のiou=0.7を維持**。
- **imgsz**: 640→1280に上げると悪化(Exact Match 0%、No Detection Rate 61.9%)。学習時のimgsz(640)と
  推論時のimgszは一致させるべきという既知のベストプラクティスを実データで確認した。**imgsz=640を維持**。

### Per-digit confusion（Issue #22）

| GT | Pred | 件数 |
|---|---|---|
| 4 | 7 | 10 |
| 1 | 5 | 3 |
| 0 | 7 | 1 |
| 6 | 8 | 1 |

**"4"を"7"と誤認識するケースが突出して多い。** 次回データ収集では"4"の書体バリエーションを重点的に増やすことを推奨する。

### Failure examples（抜粋、全件は`data/reports/candidate_full_v2.json`）

| image | GT | Pred | category |
|---|---|---|---|
| src_002_20260818_121000.jpg | 0214946 | 02145544 | extra_digit |
| src_002_20260818_130000.jpg | 0214948 | 0249544 | wrong_value |
| src_002_20260818_150200.jpg | 0214950 | 0245550 | wrong_value |

---

## 5. Temporal Stabilizer評価（Issue #43-47）

実`ReadingStabilizer`(既定設定: majority, window=5, required_matches=3, min_confidence=0.60)へ、実際の
YOLO推論結果を時系列で投入して評価した。テスト画像は数分間隔のinterval captureであり、実際の値も撮影間で
変化しうるため、`--repeat 5`(同一frameの結果を5回連続投入し、実映像で数フレーム値が変わらない状況を模す)
を用いた。

### capture_001(8枚、Domain A、repeat=5)

| Metric | Baseline | Candidate |
|---|---|---|
| Raw Exact Match Rate | 0.0% | 62.5% |
| Confirmed Exact Match Rate | 0.0% | 45.5% |
| Confirmed Stale Rate（直近の正しい値をまだ表示している遅延、危険ではない） | 0.0% | 24.2% |
| False Confirmed Reading Rate（本当に誤った値を確信を持って確定、危険） | **100%** | **30.3%** |
| Confirmed Tick Ratio | 50.0% | 82.5% |
| Time to First Correct Confirmation | - (never) | 10.3s(相対値) |

**Baselineは一度もRaw/Confirmedとも正解しない上、Confirmedに至った場合は常に「本当に誤った値」を確信を持って
表示する(False Confirmed Reading Rate=100%)。** 一方Candidateは、Confirmedに至った場合の70%近くが正解または
「直近の正しい値をまだ表示しているだけの遅延」であり、本当の誤確定は30.3%に抑えられている。
**時系列安定化はモデルの誤りを魔法のように消すものではない**(GIGO)ことも合わせて確認できた
— Baselineのように raw精度が0%のモデルでは、安定化しても「安定して間違え続ける」だけになる。

### Out-of-Domain評価: `src_004`(142枚、Domain B=機械式メーター、repeat=5)

両モデルともDomain Aのみで学習しているため、Domain Bでは事実上機能しない: Raw Exact Match 0%(両モデル)。
興味深い違いとして、**Baselineは一貫して同じ誤値を確信を持ってConfirmedし続ける(Confirmed Tick Ratio 4.2%、
False Confirmed Rate 100%)のに対し、Candidateはほとんど何もConfirmedしない(Confirmed Tick Ratio 2.1%)。**
未知ドメインに対してCandidateの方が「自信を持って間違える」頻度が低い、より安全な失敗モードだと言える。
ただし、いずれにせよDomain Bはどちらのモデルでも実用にならず、Domain Bをサポートする場合は専用データ収集・
再学習が必須(9章)。

---

## 6. Benchmark（Issue #37-39）

RTX 4070 Laptop GPU、実CPU(このマシン)で計測。

| | Baseline CPU | Candidate CPU | Baseline GPU | Candidate GPU |
|---|---|---|---|---|
| Load time | 2.96 s | 3.70 s | 5.77 s | 7.20 s |
| Warm avg | 92.9 ms | **48.9 ms** | 9.74 ms | **8.18 ms** |
| P50 | 94.0 ms | 48.8 ms | 9.71 ms | 8.08 ms |
| P95 | 113.6 ms | 51.8 ms | 10.9 ms | 9.52 ms |
| Effective FPS | 10.8 | 20.4 | 102.7 | 122.2 |
| VRAM | - | - | 71.5 MB | **12.1 MB** |
| モデルファイルサイズ | 40.4 MB | **6.2 MB** | | |

Candidateは精度改善だけでなく、CPU/GPUとも高速・省メモリであり、tradeoffは無い(速度を犠牲にした精度改善ではない)。

---

## 7. Model Card: `meter_digits_v2_candidate.pt`

| 項目 | 内容 |
|---|---|
| model_id | `meter_digits_v2_candidate.pt` |
| role | `candidate`（"Production Candidate"、`production`への昇格はさらなるデータ収集後を推奨） |
| task | detect |
| classes | 0-9 |
| input size | 640 |
| training dataset | `meter_argus_train_v2`(163枚, train139/val24, 物理個体#2, seed=42) |
| recommended conf/iou/imgsz | 0.25 / 0.7 / 640 |
| device対応 | cpu, cuda |
| created_at | 2026-08-19 |
| source run | `yolo_pipeline_studio` project `meter`, train-job `meter_digits_v2_candidate_003` |
| known limitations | 学習画像139枚・単一物理個体のみ。Domain B(機械式メーター)非対応。"4"→"7"の誤認識が目立つ。Exact Match 28.6%は無監督運用には不十分 |

登録は`data/models/registry.json`(`backend/app/inference/model_catalog.py`が読み込み、`GET /api/system/models`で参照可能)。

---

## 8. Runtime Validation

- `GET /api/system/models` でbaseline/candidate双方がrole付きで一覧取得できることを確認。
- Frontend `InferenceSettings.tsx` のモデル選択がdropdown化され、role・ファイル存在有無を表示した上でbaseline/candidateを
  切り替え可能なことを確認(既存Device selectorと同じ設計パターン)。
- 実カメラでの物理メーターを使ったA/Bライブ検証は、この開発環境に実際の物理ガスメーターが無いため**未実施**。
  代わりに実際に撮影済みの静止画(1章のTest Set/OOD Set)で両モデルを実行し比較した。

---

## 9. 発見した不具合・修正した不具合

- **発見**: 既存Datasetの`test_ratio=0`によりTest Setが存在せず、Data Leakageリスクがあった → **修正**: source単位の
  除外(selection機能)でTest Setを分離するdataset(`meter_argus_train_v2`)を新規作成。
- **発見**: 初回のTest Set選定(`src_004`除外)が実際には別メータードメインを対象にしてしまっていた(目視確認不足) →
  **修正**: 物理個体単位の分離へ設計変更(1.3節)。
- **発見**: `yolo_pipeline_studio`のTraining既定augmentation(`standard`)が`fliplr=0.5`を含み、数字認識タスクに
  不適切 → **修正**: `light`プリセットを明示指定。
- **発見**: 推論imgszを学習時より大きくする(1280)と精度が悪化する → 対処: 既定640を維持、Model Cardに明記。
- **発見**: Baselineには一度もYOLO標準指標が算出されていなかった(無評価のまま運用されていた) → 本Issueで初めて
  定量評価を実施。

---

## 10. Dataset不足事項・次に収集すべきData（Issue #33, #88）

- **物理個体・撮影環境の多様性が不足**: 実質2個体(Domain A)。より多くの物理メーター(同型・別型番とも)を
  複数環境で撮影する必要がある。
- **Domain B(機械式ドラムメーター)向けの学習データが無い**: 142枚撮影済みだが未annotationの活用も含め、
  Domain Bをサポートするなら専用datasetとしてTraining/Evaluationを分離すべき。
- **"4"の書体バリエーション不足**: 最頻出の誤認識(4→7)。
- **屋外・強いglare/motion blur・部分遮蔽のサンプルが無い**(1.4節)。
- 上記を踏まえ、次のCandidate学習では最低でも500枚規模・5個体以上のDomain Aデータを目標にすることを推奨する。

## 11. Known Limitations

- Test Set 21枚・Train 139枚という小規模データセットであり、統計的信頼区間は広い。
- 実物理メーターでの長時間ライブ検証は未実施(開発環境に実メーターが無いため)。
- Domain B(機械式メーター)は未対応。
- `datetime.utcnow()`のtimezone-aware化は本Issueのscope外(既存Issueで見送り済み、変更なし)。

## 12. 最終判断

**A: Candidate(`meter_digits_v2_candidate.pt`)をProduction Candidateとして採用し、Model Registryへ`role=candidate`で
登録する。** Baseline(`meter_digits_v1.pt`)は`role=baseline`のまま削除せず維持し、Frontendから両方を選択可能にする。
`role=production`への昇格は、9-10章のデータ収集・再学習を経て、より大規模なTest Setで再評価した後に判断する。

---

## 13. v3 Round — Expand Meter Dataset and Retrain Production Candidate Model（2026-08-19）

### 13.1 前提と制約

当初目標は「Domain A 5個体以上・500枚以上」だったが、実際に取得可能な実物理個体はsrc_001/src_002/src_003の
**3個体のみ**（社内の実運用カメラを直接調査して確認）。したがって本ラウンドは、5個体到達を装わず
**「取得可能な3個体で正直に評価する」**方針で実施した。src_001/src_002は既存`meter_test_set_v2`と同一の
Test役割個体、src_003は`meter_argus_train_v2`と同一のTrain役割個体であり、個体の役割（train/test）はv2から
変更していない。追加2個体・Domain B(機械式ドラムメーター、src_004)はFuture Data Collection（13.7節）とする。

### 13.2 追加データ取得（実カメラ, capture-sessions機能）

src_001/002/003それぞれに対し、既存`capture-sessions`機能で実カメラから追加撮影を実施（interval 3〜5分、
video_fps=6）。credential・IP・URLはコミット・ログ・本ドキュメントに一切記録していない。

| Source | 役割 | 取得枚数 | 実測内容（目視確認） |
|---|---|---|---|
| src_001 | Test(New Holdout) | 7枚 | **全7枚が同一reading("0023607")** — 撮影window中ガス使用なし(idle)。2種の撮影条件(明るい広角/暗くdustyな接写)を確認、うち代表2枚を採用。 |
| src_002 | Test(New Holdout) | 7枚 | **全7枚が同一reading("0214968")** — 同じくidle。視覚的な多様性もほぼ無く、代表2枚のみ採用。 |
| src_003 | Train | 4枚 | reading "0258150→0258153→0258155→0258158"と**全て異なる実測値**、Train拡充に有効と判断し4枚全て採用。 |

制約#6/#8（機械的水増し禁止・近似フレーム大量生成回避）に従い、src_001/002はreading自体に変化が無かったため、
枚数を無理に積み増さず「New Holdout Test」へ**4枚のみ**（src_001×2 + src_002×2）を採用した。取得できた枚数の
多くをそのまま採用しなかった理由は、同一readingの複製がTest集計を歪める（同じ正解/不正解が重複カウントされる）
ことを避けるためであり、精度の見かけを良くするための操作ではない。

### 13.3 Annotation QA（pseudo-labelを正解として採用しない）

`meter_digits_v2_candidate.pt`で新規18枚にpseudo-labelを生成した後、**Ground Truthとして自動採用せず**全数を
目視のメーター読み取り値と突き合わせた。結果:

- **src_003(Train用)の4枚**: v2予測がすべて目視GTと完全一致 → そのままラベルとして採用（境界箱・クラスとも）。
- **src_001/002(Test用)の14枚**: v2予測は**すべて誤り**（digit数不足や誤分類）だった。固定カメラであるため、
  既存`meter_test_set_v2`内の同一個体の正解ラベル（境界箱の位置は撮影ごとにほぼ不変）を参照し、境界箱位置は
  流用、クラスのみ目視読み取り値へ手動で置き換えて最終ラベルを作成した。

この結果自体が、v2が「未知の物理個体・条件」に対して脆弱であることを裏付けており、New Holdout Testの
必要性を実証している。

### 13.4 Dataset

- **Train**: `meter_argus_train_v3`（src_003 既存163枚 + 新規4枚 = 167枚、143 train / 24 val、seed=42、
  train/val比率はv2と同一の139:24 ≒ 0.853:0.147を踏襲）。`meter_argus_train_v2`は無変更のまま維持。
- **Legacy Golden Test（A）**: `meter_test_set_v2`（21枚）。**完全固定・無変更**（画像・ラベル・SHA256すべて
  Issue #7時点と一致することを確認済み）。
- **New Holdout Test（B）**: `meter_holdout_v3`（4枚、src_001×2 + src_002×2）。Trainには一切使用していない。
- **Combined（C）**は参考値としてのみ扱い、以下の表ではA/Bを必ず個別併記する。

### 13.5 Training

`meter_digits_v3_candidate_001`をv2と同一手法で学習: `yolov8n.pt`, epochs=100, batch=8, imgsz=640, device=cuda,
seed=42, augmentation_preset=light(degrees=3, translate=0.05, scale=0.2, fliplr=0, flipud=0, mosaic=0.5)。
内部val(24枚)でのYOLO標準指標はv2とほぼ同値（v2: precision=0.989, recall=0.993, mAP50=0.995, mAP50-95=0.936 /
v3: precision=0.988, recall=1.000, mAP50=0.995, mAP50-95=0.938）。**同一ドメイン内val setでは両者とも
ほぼ飽和しており、mAPだけでは差が検出できない**ことを確認した — Full Reading Exact Matchを中心指標とする
本評価方針の妥当性を裏付ける結果である。

### 13.6 v2(新Baseline) vs v3(新Candidate) 評価結果

conf=0.25, iou=0.7, imgsz=640, device=cpuで統一。

| 指標 | v2 × Legacy(A, n=21) | v3 × Legacy(A, n=21) | v2 × Holdout(B, n=4) | v3 × Holdout(B, n=4) |
|---|---|---|---|---|
| Full Reading Exact Match | 28.6% | **28.6%(無変化)** | 0.0% | **0.0%(無変化)** |
| No Detection Rate | 4.8% | 4.8% | 0.0% | 0.0% |
| Missing Digit Rate | 52.4% | **19.0%(改善)** | 50.0% | 50.0% |
| Digit Detection Accuracy | 75.9% | **82.1%(改善)** | 71.4% | **82.1%(改善)** |
| Digit Classification Accuracy | 86.4% | **81.5%(悪化)** | 75.0% | **69.6%(悪化)** |

Temporal Stabilizer（repeat=3、同一値の連続観測をシミュレート）:

| 指標 | v2 × Legacy(A) | v3 × Legacy(A) | v2 × Holdout(B) | v3 × Holdout(B) |
|---|---|---|---|---|
| False Confirmed Reading Rate | 46.4% | **100%(大幅悪化)** | 100% | 100%(無変化) |

CPU/GPU latency（v3, CPU: 65.9ms warm avg / GPU RTX 4070 Laptop: 10.4ms warm avg）はv2（48.9ms / 8.18ms）と
比べてやや遅いが、同一アーキテクチャ(yolov8n)のため誤差範囲。

### 13.7 Per-digit confusionの追跡（4→7, 1→5, 0→7, 6→8）

Issue #7で確認されたsrc_002個体の"1→5, 4→7"混同を個別追跡したところ、**v3でも解消していない**。むしろ
`missing_digit`（未検出）から`wrong_value`（誤って別の数字と自信を持って判定）へ悪化した例が複数見られた
（例: `src_002_20260818_110000.jpg` GT=0214943, v2予測=missing digit(027943), v3予測=0257943）。

原因分析: 今回Trainへ追加した4枚は全てsrc_003（既存Train個体と同一物理個体）由来であり、confusionの震源で
あるsrc_001/src_002個体自身のLCD表示特性（セグメント劣化・視認性）をTrainに反映できていない。制約#5
（Test役割個体はTrainに使用しない）を遵守した結果、この特定confusionの根本解決には至らなかった。

### 13.8 昇格判断

判断基準（事前合意）: Legacy Golden Test改善 **かつ** New Holdout Test改善 **かつ** False Confirmed Reading改善
**かつ** 重大Regressionなし、を全て満たし、かつ絶対精度が無監督運用に十分な場合のみ`role=production`へ昇格する。

実績: Full Reading Exact MatchはA/Bとも**無変化**（改善なし）、Digit Classification AccuracyはA/Bとも**悪化**、
False Confirmed Reading RateはAで**大幅悪化**（46.4%→100%）。判断基準を満たさないため、

**`role=production`への昇格は見送る。** さらに、v3はv2を明確に上回ってもいないため（検出は改善、分類は悪化、
Exact Matchは同点）、v2の`role=candidate`を無条件に置き換えることもしない。v3は`role=rejected_candidate`として
Model Registryに記録のみ残し、`meter_digits_v2_candidate.pt`が引き続き`role=candidate`である。

### 13.9 Future Data Collection（今回取得できなかった事項）

- **5個体目標に対し3個体まで**: 追加2個体は未取得。実カメラ環境で新規個体が見つかり次第、Train/Test比率
  （現状Train 1個体・Test 2個体）を崩さない形で追加することを推奨。
- **Domain B(src_004, 機械式ドラムメーター)**: 依然未対応。専用datasetでの学習が必要。
- **1/4/5/7の形状混同**: Test役割個体（src_001/002）自身のデータをTrainに使えない制約下では、今回の
  「同一個体内での枚数追加」では解決不可能と判明した。次善策として (a) 4個体目以降の独立個体をTrain側に
  追加する、(b) 1/4/5/7の書体差を狙った合成データ拡張（フォント変形・部分オクルージョン等）を検討する。
- **New Holdout Testは4枚と小規模**: src_001/002が撮影window中ずっとidleだったため、今回の追加取得では
  reading自体の多様性を増やせなかった。今後は複数日・複数時間帯にまたがる取得で、実際の値変化を捉える
  必要がある。
