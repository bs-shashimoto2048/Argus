import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Inference, Monitor, ReadingDiagnostics, RuntimeDiagnostics, Source } from "../types";
import { formatDateTimeJst } from "../utils/datetime";
import { InferenceSettings } from "../components/InferenceSettings";
import { ReadingSettingsPanel } from "../components/ReadingSettingsPanel";
import { ReadingBaselinePanel } from "../components/ReadingBaselinePanel";
import { conflictMessage, stripLeadingZeros } from "../utils/readingFormat";
import { SourceSettings } from "../components/SourceSettings";
import { VideoPreview } from "../components/VideoPreview";
import { RecordsSection } from "../components/RecordsSection";
import { RoiEditor } from "../components/RoiEditor";
import { PreprocessEditor } from "../components/PreprocessEditor";
import { combinedMonitorStatus, monitorStatusLabels } from "../utils/monitorStatus";

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

function inferenceErrorText(code: string, engine: string): string {
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

function currentValueText(monitor: Monitor): string {
  // pending(まだConsensusが取れていない)はcurrent_valueが必ずnullのため専用文言を出す。
  if (monitor.inference_status === "pending") return "判定中...";
  return monitor.current_value ?? "--";
}

function formatDiff(current: string | null, previous: string | null): string {
  if (current == null || previous == null) return "--";
  const a = Number(current);
  const b = Number(previous);
  if (Number.isNaN(a) || Number.isNaN(b)) return "--";
  const diff = a - b;
  return `${diff >= 0 ? "+" : ""}${diff}`;
}

// 右ペインの各設定セクションを独立して開閉するための共通ラッパー。
// 閉じてもDOMからは外さず(display:noneのみ)、フォーム値・API呼び出しに一切影響しない。
type SectionKey = "basic" | "source" | "preprocess" | "roi" | "reading" | "baseline" | "inference" | "danger";

function CollapsibleSection({ title, open, onToggle, className, children }: { title: string; open: boolean; onToggle: () => void; className?: string; children: React.ReactNode }) {
  return <section className={`panel collapsible-panel${className ? ` ${className}` : ""}`}>
    <button type="button" className="collapsible-header" onClick={onToggle} aria-expanded={open}>
      <span className="chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
      <h3>{title}</h3>
    </button>
    <div className="collapsible-body" style={open ? undefined : { display: "none" }}>{children}</div>
  </section>;
}

export type DetailTab = "monitoring" | "history" | "settings" | "diagnostics";
const detailTabs: { key: DetailTab; label: string }[] = [
  { key: "monitoring", label: "Monitoring" },
  { key: "history", label: "History" },
  { key: "settings", label: "Settings" },
  { key: "diagnostics", label: "Diagnostics" },
];

export function MonitorDetailPage() {
  const { id } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const tab: DetailTab = detailTabs.some((item) => item.key === requestedTab) ? (requestedTab as DetailTab) : "monitoring";
  const selectTab = (key: DetailTab) => setSearchParams(key === "monitoring" ? {} : { tab: key }, { replace: true });
  const monitorId = Number(id);
  const navigate = useNavigate();
  const [monitor, setMonitor] = useState<Monitor | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [inference, setInference] = useState<Inference | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [editor, setEditor] = useState<"roi" | "preprocess" | null>(null);
  const [readingDiagnostics, setReadingDiagnostics] = useState<ReadingDiagnostics | null>(null);
  const [runtimeDiagnostics, setRuntimeDiagnostics] = useState<RuntimeDiagnostics | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // 表示レイアウトのみの状態(取得データ・API呼び出し頻度には影響しない)。
  const [lightbox, setLightbox] = useState<"video" | "overlay" | "inferenceInput" | null>(null);
  // Issue #28: 「モニター映像」「推論オーバーレイ」を縦に2枚並べず、タブで1枚だけ
  // 表示する(ページの縦スクロールを削減するため)。非表示側はunmountされるので、
  // 見えていない方のpolling(VideoPreviewのsetInterval)も自動的に止まる。
  const [videoTab, setVideoTab] = useState<"video" | "overlay">("video");
  // 右ペイン各セクションの開閉状態(Frontend表示のみ・永続化なし)。
  // 日常監視では設定編集の頻度が低いため、初期状態は全セクション折りたたみ(画面を短く保つ)。
  const [openSections, setOpenSections] = useState<Record<SectionKey, boolean>>({
    basic: true, source: true, preprocess: true, roi: true, reading: true, baseline: true, inference: true, danger: false,
  });
  const toggleSection = (key: SectionKey) => setOpenSections((current) => ({ ...current, [key]: !current[key] }));
  // Issue #20/#25: 基本情報(name/display_name/location)専用のフォーム状態。
  // source/inferenceとは別のstateにして、保存時にsource/inferenceを一切含まない
  // PATCHを送る(Backendが Runtime/VideoReader/InferenceSchedulerへ触れないための
  // 条件と対応させる)。nameはIssue #25で編集可能になった(内部識別名だが、
  // 実行時の識別には常にMonitor ID(id)が使われ、nameを参照する経路が無いことを
  // 確認済み。UNIQUE制約・フォーマット制約(^[A-Za-z0-9_-]+$)はBackend側で検証)。
  const [basicInfo, setBasicInfo] = useState<{ name: string; display_name: string; location: string }>({ name: "", display_name: "", location: "" });
  const [savingBasicInfo, setSavingBasicInfo] = useState(false);

  useEffect(() => {
    if (!lightbox) return undefined;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setLightbox(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightbox]);

  useEffect(() => {
    api.monitor(monitorId)
      .then((value) => {
        setMonitor(value);
        setSource(value.source);
        setInference(value.inference);
        setBasicInfo({ name: value.name, display_name: value.display_name, location: value.location });
      })
      .catch((reason: Error) => setError(reason.message));
  }, [monitorId]);

  // 現在値/信頼度/推論statusを画面を開いたまま更新できるよう定期的に取得する。
  // 編集中のsource/inferenceフォームは上書きしない（monitorのみ更新）。
  useEffect(() => {
    const timer = window.setInterval(() => {
      api.monitor(monitorId).then(setMonitor).catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [monitorId]);

  // Raw値(Debug用)。推論Runtime停止中は404/409になるため失敗は無視する。
  useEffect(() => {
    const poll = () => api.readingDiagnostics(monitorId).then(setReadingDiagnostics).catch(() => setReadingDiagnostics(null));
    poll();
    const timer = window.setInterval(poll, 5000);
    return () => window.clearInterval(timer);
  }, [monitorId]);

  // Runtime診断(state/last_error/last_frame等)。映像Runtime停止中は409になるため失敗は無視する。
  // credential/URLは含まれないため、そのまま画面表示してよい。
  useEffect(() => {
    const poll = () => api.runtimeDiagnostics(monitorId).then(setRuntimeDiagnostics).catch(() => setRuntimeDiagnostics(null));
    poll();
    const timer = window.setInterval(poll, 3000);
    return () => window.clearInterval(timer);
  }, [monitorId]);

  if (!monitor || !inference) {
    return <main className="page"><div className="loading">読み込み中...</div></main>;
  }

  const check = async (value: Source & { password?: string }) => {
    setMessage("接続確認中...");
    try {
      const result = await api.testSource(monitorId, value);
      const hint = result.resolved_url_hint ? `（実stream URL: ${result.resolved_url_hint} へ解決）` : "";
      setMessage(`${result.connected ? "●" : "×"} ${result.message}${hint}`);
    } catch (reason) {
      setMessage(String(reason));
    }
  };

  const deleteMonitor = async () => {
    setDeleting(true);
    try {
      await api.remove(monitorId);
      navigate("/monitors");
    } catch (reason) {
      setError(String(reason));
      setConfirmingDelete(false);
      setDeleting(false);
    }
  };

  // Confirmed(確定値)とRaw(最新推論値、未確定)の区別をUI上で示すための派生値。
  // どちらも既存の5秒/3秒ポーリングで取得済みのデータのみを使用し、新規API呼び出しは発生しない。
  const rawInferenceValue = runtimeDiagnostics?.inference_result ?? null;
  // 確定値は整数部の先頭0を除去した形のため、Raw(元の桁列)側も同じ形へ揃えて比較する。
  const rawDiffersFromConfirmed = rawInferenceValue != null && stripLeadingZeros(rawInferenceValue) !== stripLeadingZeros(monitor.current_value);
  // Issue #28調査: last_inference_error(DB由来、値が変わるまで残り続ける)だけを見ると、
  // 「model_idを設定し直した後もMODEL_NOT_CONFIGUREDの表示が残る」という誤解を招く。
  // 実際に現在のinference設定でmodel_idが空かどうかは、この派生値で直接判定する
  // (object_detection+ultralyticsのときだけ意味を持つ組み合わせ)。
  const modelMissing = monitor.inference.method === "object_detection" && monitor.inference.engine === "ultralytics" && !monitor.inference.model_id;

  // Issue #38: cpp_onnxはmodel_idが必須(Backendも拒否するが、UIでも保存前に止める)。
  const cppModelMissing = inference.method === "object_detection" && inference.engine === "cpp_onnx" && !inference.model_id;

  const save = async () => {
    try {
      const updated = await api.update(monitorId, {
        source: source ? { ...source, password: (source as Source & { password?: string }).password || undefined } : undefined,
        inference,
      });
      setMonitor(updated);
      setSource(updated.source);
      setInference(updated.inference);
      setMessage("設定を保存しました");
      setError("");
    } catch (reason) {
      setError(String(reason));
    }
  };

  // Issue #20/#25: 基本情報(内部名/表示名/設置場所)の保存。source/inferenceキーを
  // 一切含まないPATCHを送ることで、Backend側がRuntime/VideoReader/
  // InferenceSchedulerに触れない経路(update_monitorの基本情報のみ判定)を
  // 通るようにする。nameの重複/フォーマットエラーはBackendのvalidationに委ね、
  // 失敗時は既存のerror表示にそのまま乗せる。
  const saveBasicInfo = async () => {
    setSavingBasicInfo(true);
    try {
      const updated = await api.update(monitorId, { name: basicInfo.name, display_name: basicInfo.display_name, location: basicInfo.location });
      setMonitor(updated);
      setBasicInfo({ name: updated.name, display_name: updated.display_name, location: updated.location });
      setMessage("基本情報を保存しました");
      setError("");
    } catch (reason) {
      setError(String(reason));
    } finally {
      setSavingBasicInfo(false);
    }
  };

  return <main className="page monitor-detail-page">
    <header className="topbar">
      <div>
        <div className="breadcrumbs">モニター管理 / メーター詳細</div>
        <h1>{monitor.display_name}</h1>
        {/* 設定変更・デバッグ時に対象Monitorを取り違えないよう、display_nameとIDを常時明示する(Issue #16)。 */}
        <div className="monitor-id-badge">Monitor ID: {monitor.id}</div>
      </div>
      <div className="topbar-actions">
        <button className="secondary" onClick={() => navigate("/monitors")}>＜ モニター管理へ</button>
      </div>
    </header>

    <div className="detail-tabs" role="tablist" aria-label="モニター詳細">
      {detailTabs.map((item) => <button key={item.key} type="button" role="tab" id={`tab-${item.key}`} aria-selected={tab === item.key} className={`detail-tab${tab === item.key ? " active" : ""}`} onClick={() => selectTab(item.key)}>{item.label}</button>)}
    </div>

    {(error || message) && <div className={`alert ${error ? "error" : "success"}`}>{error || message}</div>}

    <div className="detail-tab-body" role="tabpanel" aria-labelledby={`tab-${tab}`}>
      {tab === "monitoring" && <section className="monitor-column">
        {/* Issue #28: 現在値/前回値を左右2グループに分けたサマリー(1画面に収める
            ためのレイアウト方針の一部)。取得元は既存の5秒ポーリングのみで、
            APIコール自体は追加していない(previous_confidence/previous_confirmed_atは
            MonitorResponseの新規フィールドとして同じレスポンスに含まれる)。 */}
        <div className="panel reading-summary" aria-live="polite">
          <div className="reading-summary-group current">
            <div className="reading-summary-label">現在値</div>
            <div className="status-item primary"><small>現在値（確定）</small><strong>{currentValueText(monitor)}</strong></div>
            <div className="status-item"><small>信頼度</small><strong>{monitor.confidence == null ? "--" : `${(monitor.confidence * 100).toFixed(1)}%`}</strong></div>
            {/* Issue #29: monitor.status(映像Runtime接続状態)とmonitor.inference_status(読取・
                推論状態)を合成した表示にする(Dashboardのバッジと同じルール)。詳細な内訳は
                下部「推論デバッグ」の映像Runtime診断行で個別に確認できる。 */}
            <div className="status-item"><small>状態</small><span className={`status-text ${combinedMonitorStatus(monitor)}`}>● {monitorStatusLabels[combinedMonitorStatus(monitor)]}</span></div>
            {rawDiffersFromConfirmed && <div className="status-item raw-pending"><small>最新推論値（未確定）</small><strong>{rawInferenceValue}</strong></div>}
          </div>
          <div className="reading-summary-divider" aria-hidden="true" />
          <div className="reading-summary-group previous">
            <div className="reading-summary-label">前回値</div>
            <div className="status-item"><small>前回値</small><strong>{monitor.previous_value ?? "--"}</strong></div>
            <div className="status-item"><small>信頼度</small><strong>{monitor.previous_confidence == null ? "--" : `${(monitor.previous_confidence * 100).toFixed(1)}%`}</strong></div>
            <div className="status-item"><small>確定日時</small><strong>{monitor.previous_confirmed_at ? formatDateTimeJst(monitor.previous_confirmed_at) : "--"}</strong></div>
            <div className="status-item"><small>差分</small><strong>{formatDiff(monitor.current_value, monitor.previous_value)}</strong></div>
          </div>
        </div>
        <p className="muted status-note">
          「現在値（確定）」は読取安定化により確定した値です（直近{monitor.inference.reading.window_size}回中{monitor.inference.reading.required_matches}回以上一致で更新）。
          一致が取れていない間は直前の確定値を保持するため、最新の推論結果と一時的に異なる場合があります。「前回値」は直前に確定していた値（Raw推論の途中経過ではありません）。
        </p>
        {modelMissing && <div className="alert error">モデルが設定されていません。右側の「推論設定」でモデルを選択してください。</div>}
        {/* Issue #32: current_inference_errorは直近のRaw Readingが既に成功していればnullになる
            「現在の状態」専用の値なので、これが立っている間だけ赤の警告として表示する。 */}
        {/* Issue #40: 合意候補がbaselineと矛盾して一定時間続いている(=固着の疑い)場合の警告。 */}
        {monitor.reading_baseline?.conflict && (
          <div className="alert warning">⚠ {conflictMessage(monitor.reading_baseline.conflict_status, monitor.reading_baseline.value, monitor.reading_baseline.conflict_candidate, monitor.reading_baseline.conflict_seconds)}。実メーターを確認し、必要なら「読取基準値」から再設定してください。</div>
        )}
        {monitor.current_inference_error && !modelMissing && <div className="alert error">{inferenceErrorText(monitor.current_inference_error, monitor.inference.engine)}</div>}
        {/* last_inference_errorは値が変わるまで残り続ける履歴値(粘着性)なので、現在は
            エラーではない(current_inference_errorがnull)場合は、誤って現在のエラーと
            混同されないよう、控えめな「過去のエラー」注記としてのみ表示する。 */}
        {!monitor.current_inference_error && monitor.last_inference_error && !modelMissing && (
          <p className="muted status-note">直近のエラー履歴（現在は解消済み）: {inferenceErrorText(monitor.last_inference_error, monitor.inference.engine)}</p>
        )}

        <div className="monitoring-summary" aria-label="読取の詳細">
          <div><small>Raw（最新・未確定）</small><strong>{rawInferenceValue ?? readingDiagnostics?.confirmed.raw_value ?? "--"}</strong></div>
          <div><small>engine</small><strong>{monitor.inference.engine}</strong></div>
          <div><small>model</small><strong title={monitor.inference.model_id ?? undefined}>{monitor.inference.model_id ?? "--"}</strong></div>
          <div><small>最終更新</small><strong>{monitor.last_updated ? formatDateTimeJst(monitor.last_updated) : "--"}</strong></div>
          <div><small>baseline</small><strong>{monitor.reading_baseline ? `${monitor.reading_baseline.value ?? "--"}（${monitor.reading_baseline.state === "pending_reset" ? "リセット済み" : "有効"}）` : "--"}</strong></div>
          <div><small>conflict</small><strong className={monitor.reading_baseline?.conflict ? "conflict-yes" : undefined}>{monitor.reading_baseline?.conflict ? `あり（${monitor.reading_baseline.conflict_candidate ?? "--"}）` : "なし"}</strong></div>
        </div>

        {/* Issue #28: 「モニター映像」「推論オーバーレイ」を縦2枚並べる構造を廃止し、
            同じ映像領域をタブで1枚だけ表示する。非アクティブ側はunmountされるため、
            表示していない方のpolling(VideoPreview内のsetInterval)も自動的に止まる。 */}
        <div className="panel video-panel primary-video">
          <div className="video-tabs" role="tablist">
            <button type="button" role="tab" aria-selected={videoTab === "video"} className={`video-tab${videoTab === "video" ? " active" : ""}`} onClick={() => setVideoTab("video")}>モニター映像</button>
            <button type="button" role="tab" aria-selected={videoTab === "overlay"} className={`video-tab${videoTab === "overlay" ? " active" : ""}`} onClick={() => setVideoTab("overlay")} disabled={!monitor.source}>推論オーバーレイ</button>
          </div>
          <div className="primary-video-body">
            {!monitor.source ? (
              <div className="no-video large">映像ソースを設定してください</div>
            ) : lightbox === videoTab ? (
              <div className="no-video large">拡大表示中（×で閉じると再表示されます）</div>
            ) : videoTab === "video" ? (
              <VideoPreview monitorId={monitor.id} large onImageClick={() => setLightbox("video")} />
            ) : (
              <VideoPreview monitorId={monitor.id} overlay onImageClick={() => setLightbox("overlay")} />
            )}
          </div>
          {videoTab === "overlay" && monitor.source && <>
            <div className="overlay-legend">
              {/* ROIの破線は、推論cropがROIより広い場合(roi_modeあり)だけ描画される */}
              {runtimeDiagnostics?.pipeline?.roi_mode && <span><i className="legend-swatch legend-roi" />ユーザー指定ROI</span>}
              <span><i className="legend-swatch legend-detection" />検出bbox（ラベル: 推論値/確信度）</span>
              <span>前処理後の推論入力画像に描画</span>
            </div>
            {runtimeDiagnostics?.pipeline && (
              (runtimeDiagnostics.pipeline.engine === "ultralytics" || runtimeDiagnostics.pipeline.engine === "cpp_onnx") ? (
                <p className="muted overlay-caption">
                  検出 {runtimeDiagnostics.pipeline.roi_filtered_detection_count}/{runtimeDiagnostics.pipeline.raw_detection_count} 件（ROI内/全体）
                  {runtimeDiagnostics.pipeline.raw_detection_count === 0 && "（全体でも検出0件のため、bboxは表示されません）"}
                </p>
              ) : (
                <p className="muted overlay-caption">
                  このエンジン（{runtimeDiagnostics.pipeline.engine}）は文字ごとの位置を検出しないため、bboxは表示されません（検出bbox=0は仕様どおりです）。
                </p>
              )
            )}
          </>}
        </div>

      </section>}

      {tab === "history" && <RecordsSection monitors={[{ id: monitor.id, display_name: monitor.display_name }]} fixedMonitorId={monitor.id} pageSize={50} title="この Monitor の計測履歴" description="1時間ごとの正式な記録（reading_records）。" size="tall" />}

      {tab === "settings" && <section className="settings-tab">
        <div className="settings-tab-grid">
        <CollapsibleSection title="基本情報" open={openSections.basic} onToggle={() => toggleSection("basic")}>
          <div className="readonly-field"><small>Monitor ID</small><strong>{monitor.id}</strong></div>
          <label>
            内部名（name）
            <input required pattern="[A-Za-z0-9_-]+" value={basicInfo.name} onChange={(e) => setBasicInfo({ ...basicInfo, name: e.target.value })} placeholder="gas_meter_01" />
          </label>
          <p className="muted" style={{ fontSize: "0.74rem", margin: "-4px 0 10px" }}>
            半角英数字・アンダースコア・ハイフンのみ（例: <code>gas_meter_01</code>）。他のMonitorと重複できません。
            実行時の識別には常にMonitor IDが使われるため、変更してもRuntime・映像・CSVの過去行には影響しません
            （CSVの新しい追記行から新しい内部名が反映されます）。
          </p>
          <label>表示名<input required value={basicInfo.display_name} onChange={(e) => setBasicInfo({ ...basicInfo, display_name: e.target.value })} /></label>
          <label>設置場所<input value={basicInfo.location} onChange={(e) => setBasicInfo({ ...basicInfo, location: e.target.value })} /></label>
          <div className="settings-actions"><button className="save-button" onClick={saveBasicInfo} disabled={savingBasicInfo || !basicInfo.display_name.trim() || !/^[A-Za-z0-9_-]+$/.test(basicInfo.name)}>{savingBasicInfo ? "保存中..." : "基本情報を保存"}</button></div>
        </CollapsibleSection>
        <SourceSettings source={source} onChange={setSource} onCheck={check} open={openSections.source} onToggleOpen={() => toggleSection("source")} />
        <InferenceSettings value={inference} onChange={setInference} open={openSections.inference} onToggleOpen={() => toggleSection("inference")} />
        <CollapsibleSection title="前処理" open={openSections.preprocess} onToggle={() => toggleSection("preprocess")}>
          <button className="secondary" onClick={() => setEditor("preprocess")}>前処理を編集</button>
        </CollapsibleSection>
        <CollapsibleSection title="ROI（関心領域）" open={openSections.roi} onToggle={() => toggleSection("roi")}>
          {inference.method === "object_detection" && inference.engine === "cpp_onnx" && <p className="muted" style={{ fontSize: "0.76rem", margin: "0 0 8px" }}>
            C++ ONNXではROIそのものを切り出して推論します（ROIモードは適用されません）。
          </p>}
          {inference.method === "object_detection" && inference.engine !== "cpp_onnx" && <p className="muted" style={{ fontSize: "0.76rem", margin: "0 0 8px" }}>
            モード: {inference.roi_mode === "crop_context" ? "ROI周辺を切り出して推論（詳細設定）" : "検出結果をROI内に限定（推奨）"}
          </p>}
          <button className="secondary" onClick={() => setEditor("roi")}>ROIを編集</button>
        </CollapsibleSection>
        <ReadingSettingsPanel value={inference.reading} onChange={(reading) => setInference({ ...inference, reading })} open={openSections.reading} onToggleOpen={() => toggleSection("reading")} />
        </div>
        <div className="settings-actions"><button className="save-button" onClick={save} disabled={cppModelMissing} title={cppModelMissing ? "C++ ONNXではモデルを選択してください" : undefined}>設定を保存</button></div>

        <CollapsibleSection title="Danger Zone" open={openSections.danger} onToggle={() => toggleSection("danger")} className="danger-zone">
          {!confirmingDelete ? (
            <button className="danger" onClick={() => setConfirmingDelete(true)}>このモニターを削除</button>
          ) : (
            <div className="danger-confirm">
              <p>「{monitor.display_name}」（{monitor.name}）を削除します。この操作は取り消せません。よろしいですか？</p>
              <div className="danger-confirm-actions">
                <button className="danger" onClick={deleteMonitor} disabled={deleting}>{deleting ? "削除中..." : "削除する"}</button>
                <button className="secondary" onClick={() => setConfirmingDelete(false)} disabled={deleting}>キャンセル</button>
              </div>
            </div>
          )}
        </CollapsibleSection>
      </section>}

      {tab === "diagnostics" && <section className="monitor-column diagnostics-tab">
        <div className="diagnostics-grid">
          <div className="panel" aria-label="engine / model">
            <h3>Engine / Model</h3>
            <table className="diagnostics-table"><tbody>
              <tr><td>method</td><td>{monitor.inference.method}</td></tr>
              <tr><td>engine</td><td>{monitor.inference.engine}</td></tr>
              <tr><td>model_id</td><td>{monitor.inference.model_id ?? "--"}</td></tr>
              <tr><td>映像Runtime</td><td>{runtimeDiagnostics ? runtimeDiagnostics.state : "--（停止中または取得不可）"}</td></tr>
              {runtimeDiagnostics && <tr><td>映像取得</td><td>{runtimeDiagnostics.source_fps != null ? `${runtimeDiagnostics.source_fps.toFixed(1)} fps` : "--"}{runtimeDiagnostics.frame_age != null && ` / 最新フレーム ${runtimeDiagnostics.frame_age.toFixed(1)}秒前`}{runtimeDiagnostics.stale && " / 停滞中"}</td></tr>}
              <tr><td>現在の推論エラー</td><td>{monitor.current_inference_error ? inferenceErrorText(monitor.current_inference_error, monitor.inference.engine) : "なし"}</td></tr>
              <tr><td>過去のエラー履歴</td><td>{monitor.last_inference_error ? inferenceErrorText(monitor.last_inference_error, monitor.inference.engine) : "なし"}</td></tr>
            </tbody></table>
          </div>
          {monitor.source && <div className="panel video-panel" aria-label="推論オーバーレイ">
            <h3>推論オーバーレイ</h3>
            {lightbox === "overlay" ? <div className="no-video large">拡大表示中</div> : <VideoPreview monitorId={monitor.id} overlay onImageClick={() => setLightbox("overlay")} />}
          </div>}
        </div>
        {monitor.source && <div className="panel debug-details">
          <h3>推論デバッグ（推論入力 / Pipeline診断）</h3>
          <div className="debug-body">
            <div className="video-panel nested">
              <div className="section-title"><span>推論入力（実際にモデルへ渡した画像）</span></div>
              <p className="muted" style={{ fontSize: "0.78rem", margin: "0 0 8px" }}>
                {runtimeDiagnostics?.pipeline?.roi_mode === "crop_context"
                  ? "Full Frame → ROI周辺をcontext margin分広げてcrop → 前処理 → この画像、の順で生成されます。"
                  : "Full Frame → 前処理 → この画像、の順で生成されます（filter_only: ROIでcropせずFull Frameのまま推論します）。"}
                表示用に別途生成した画像ではなく、実際にInferenceEngineへ渡した画像そのものです。
              </p>
              <VideoPreview monitorId={monitor.id} inferenceInput paused={lightbox === "inferenceInput"} onImageClick={() => setLightbox("inferenceInput")} />
            </div>
            {readingDiagnostics && <div className="debug-line">
              Raw値: {readingDiagnostics.confirmed.raw_value ?? "--"}
              {readingDiagnostics.confirmed.raw_confidence != null && ` (${(readingDiagnostics.confirmed.raw_confidence * 100).toFixed(0)}%)`}
              {" / 一致 "}{readingDiagnostics.confirmed.agreement_count}/{readingDiagnostics.confirmed.raw_count}
              {readingDiagnostics.consecutive_failures > 0 && ` / 連続失敗 ${readingDiagnostics.consecutive_failures}`}
            </div>}
            {readingDiagnostics && <div className="debug-line">
              検証: {readingDiagnostics.confirmed.validation_status ?? "--"}
              {" / 基準値 "}{readingDiagnostics.baseline?.value ?? "--"}
              {" / 合意候補 "}{readingDiagnostics.candidate?.value ?? "--"}
              {readingDiagnostics.conflict && ` / 矛盾 ${readingDiagnostics.conflict.status} ${readingDiagnostics.conflict.count}回`}
            </div>}
            {runtimeDiagnostics && <div className="debug-line">
              映像Runtime: {runtimeDiagnostics.state}
              {runtimeDiagnostics.frame_width != null && ` / ${runtimeDiagnostics.frame_width}x${runtimeDiagnostics.frame_height}`}
              {runtimeDiagnostics.reconnect_count > 0 && ` / 再接続 ${runtimeDiagnostics.reconnect_count}回`}
              {runtimeDiagnostics.last_error && ` / エラー: ${runtimeDiagnostics.last_error}`}
              {runtimeDiagnostics.stale && ` / 映像停滞中`}
            </div>}
            {runtimeDiagnostics?.pipeline && <div className="pipeline-diagnostics">
              <div className="section-title"><span>推論Pipeline診断</span></div>
              <table className="diagnostics-table">
                <tbody>
                  <tr><td>frame</td><td>{runtimeDiagnostics.pipeline.frame_width}×{runtimeDiagnostics.pipeline.frame_height}</td></tr>
                  <tr><td>roi_mode</td><td>{runtimeDiagnostics.pipeline.roi_mode ?? "--（OCR等はROIそのものをcrop）"}</td></tr>
                  {runtimeDiagnostics.pipeline.roi_mode === "crop_context" && <tr><td>context_margin</td><td>{runtimeDiagnostics.pipeline.context_margin}</td></tr>}
                  <tr><td>ROI(正規化)</td><td>x={runtimeDiagnostics.pipeline.roi_normalized.x.toFixed(3)} y={runtimeDiagnostics.pipeline.roi_normalized.y.toFixed(3)} w={runtimeDiagnostics.pipeline.roi_normalized.width.toFixed(3)} h={runtimeDiagnostics.pipeline.roi_normalized.height.toFixed(3)}</td></tr>
                  <tr><td>ROI(pixel)</td><td>{runtimeDiagnostics.pipeline.roi_pixel.join(", ")}</td></tr>
                  <tr><td>推論crop(pixel)</td><td>{runtimeDiagnostics.pipeline.inference_crop_pixel.join(", ")}</td></tr>
                  <tr><td>crop shape</td><td>{runtimeDiagnostics.pipeline.crop_shape.join(" × ")}</td></tr>
                  <tr><td>前処理後 shape</td><td>{runtimeDiagnostics.pipeline.preprocess_output_shape.join(" × ")}</td></tr>
                  <tr><td>モデル入力 shape</td><td>{runtimeDiagnostics.pipeline.model_input_shape.join(" × ")}</td></tr>
                  <tr><td>検出数(ROI filter前)</td><td>{runtimeDiagnostics.pipeline.raw_detection_count}</td></tr>
                  <tr><td>検出数(ROI filter後)</td><td>{runtimeDiagnostics.pipeline.roi_filtered_detection_count}</td></tr>
                  <tr><td>engine / model_id</td><td>{runtimeDiagnostics.pipeline.engine} / {runtimeDiagnostics.pipeline.model_id ?? "--"}</td></tr>
                </tbody>
              </table>
            </div>}
          </div>
        </div>}
        <section className="admin-operations" aria-label="管理操作">
          <h2>管理操作</h2>
          <p className="muted">通常の設定とは別の、監査履歴が残る操作です（読取基準値の再設定・リセット）。</p>
        <ReadingBaselinePanel monitorId={monitor.id} currentValue={monitor.current_value} open onToggleOpen={() => undefined} />
        </section>
      </section>}
    </div>
    {editor === "roi" && <RoiEditor
      monitorId={monitorId}
      initial={inference.roi}
      isObjectDetection={inference.method === "object_detection" && inference.engine !== "cpp_onnx"}
      initialRoiMode={inference.roi_mode}
      initialContextMargin={inference.context_margin}
      onClose={() => setEditor(null)}
      onSaved={(roi, roiMode, contextMargin) => setInference({ ...inference, roi, roi_mode: roiMode, context_margin: contextMargin })}
    />}
    {editor === "preprocess" && <PreprocessEditor monitorId={monitorId} roi={inference.roi} initial={inference.preprocessing} onClose={() => setEditor(null)} onSaved={(preprocessing) => setInference({ ...inference, preprocessing })} />}
    {lightbox && <div className="lightbox-backdrop" onClick={() => setLightbox(null)}>
      <div className="lightbox" onClick={(event) => event.stopPropagation()}>
        <button className="lightbox-close" onClick={() => setLightbox(null)} aria-label="閉じる">×</button>
        <VideoPreview
          monitorId={monitor.id}
          large={lightbox === "video"}
          overlay={lightbox === "overlay"}
          inferenceInput={lightbox === "inferenceInput"}
        />
      </div>
    </div>}
  </main>;
}
