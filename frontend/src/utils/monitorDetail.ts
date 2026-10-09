import type { Monitor } from "../types";

// 推論エラーコード -> ユーザー向け日本語メッセージ。Pythonの例外や内部詳細は表示しない。
// Issue #28調査: MODEL_NOT_CONFIGUREDはBackend(app/inference/engines.py)では
// 「model_id未設定」ではなく「ultralyticsライブラリをimportできない」場合にのみ
// 発生するコードであり、かつLatestResult.last_errorは値が変わる(=新たにConfirmed
// できる)まで更新されず残り続ける("粘着性")。そのため、モデルを後から正しく設定
// しても、ROI内で検出が続かない限りこの文言が残り「設定済みなのに未設定と表示
// される」という誤解を招いていた。実際に「model_idが空」であることは以下の
// modelMissing(現在のinference設定を直接参照)で別途判定して表示するため、この
// メッセージ自体はコードの実際の意味に合わせて表現を改める。
// Issue #32: last_inference_error自体の粘着性(上記)は、MODEL_NOT_CONFIGURED以外の
// 一時的なエラー(NO_DETECTION等)でも同様に発生し、実際には解消済みでも赤い警告として
// 表示され続けていた。現在は「現在の状態」専用のcurrent_inference_error(直近のRaw
// Readingが成功していればnull)を赤警告の判定に使い、last_inference_errorは解消済みの
// 履歴注記としてのみ表示する(下のJSX参照)。
const inferenceErrorMessages: Record<string, string> = {
  MODEL_NOT_CONFIGURED: "ultralyticsライブラリを利用できません（Backend環境エラー。モデル自体の設定とは別の問題です）",
  CPP_WORKER_ERROR: "C++ ONNX workerでエラーが発生しました（worker未ビルド/異常終了の可能性があります）",
  MODEL_NOT_FOUND: "指定されたモデルファイルが見つかりません",
  DEVICE_UNAVAILABLE: "指定されたDevice（GPU/CPU）が利用できません",
  OCR_ENGINE_UNAVAILABLE: "OCRエンジンがインストールされていません",
  TESSERACT_NOT_INSTALLED: "Tesseractがインストールされていません",
  NO_DETECTION: "検出結果がありません",
  INFERENCE_FAILED: "推論処理でエラーが発生しました",
};

export function inferenceErrorText(code: string, engine: string): string {
  // Issue #38: cpp_onnxのMODEL_NOT_CONFIGUREDは「ultralytics」とは無関係。モデル未配置・
  // registry未登録・SHA256不一致のいずれか(Backendは原因を区別せずこのコードで返す)。
  if (engine === "cpp_onnx") {
    if (code === "MODEL_NOT_CONFIGURED") return "C++ ONNXモデルを利用できません（モデルファイル未配置、registry.json未登録、またはSHA256不一致）";
    if (code === "MODEL_NOT_FOUND") return "C++ ONNXモデルファイルが見つかりません";
  }
  if (code === "OCR_ENGINE_UNAVAILABLE") {
    return engine === "tesseract" ? "pytesseractがインストールされていません" : "EasyOCRがインストールされていません";
  }
  return inferenceErrorMessages[code] ?? `推論エラー: ${code}`;
}

export function currentValueText(monitor: Monitor): string {
  // pending(まだConsensusが取れていない)はcurrent_valueが必ずnullのため専用文言を出す。
  if (monitor.inference_status === "pending") return "判定中...";
  return monitor.current_value ?? "--";
}

export function formatDiff(current: string | null, previous: string | null): string {
  if (current == null || previous == null) return "--";
  const a = Number(current);
  const b = Number(previous);
  if (Number.isNaN(a) || Number.isNaN(b)) return "--";
  const diff = a - b;
  return `${diff >= 0 ? "+" : ""}${diff}`;
}
