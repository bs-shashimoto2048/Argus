import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Inference, Monitor, ReadingDiagnostics, RuntimeDiagnostics, Source } from "../types";
import { Brand } from "../components/Brand";
import { formatDateTimeJst } from "../utils/datetime";
import { InferenceSettings } from "../components/InferenceSettings";
import { ReadingSettingsPanel } from "../components/ReadingSettingsPanel";
import { SourceSettings } from "../components/SourceSettings";
import { VideoPreview } from "../components/VideoPreview";
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
  MODEL_NOT_FOUND: "指定されたモデルファイルが見つかりません",
  DEVICE_UNAVAILABLE: "指定されたDevice（GPU/CPU）が利用できません",
  OCR_ENGINE_UNAVAILABLE: "OCRエンジンがインストールされていません",
  TESSERACT_NOT_INSTALLED: "Tesseractがインストールされていません",
  NO_DETECTION: "検出結果がありません",
  INFERENCE_FAILED: "推論処理でエラーが発生しました",
};

function inferenceErrorText(code: string, engine: string): string {
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
type SectionKey = "basic" | "source" | "preprocess" | "roi" | "reading" | "inference" | "danger";

function CollapsibleSection({ title, open, onToggle, className, children }: { title: string; open: boolean; onToggle: () => void; className?: string; children: React.ReactNode }) {
  return <section className={`panel collapsible-panel${className ? ` ${className}` : ""}`}>
    <button type="button" className="collapsible-header" onClick={onToggle} aria-expanded={open}>
      <span className="chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
      <h3>{title}</h3>
    </button>
    <div className="collapsible-body" style={open ? undefined : { display: "none" }}>{children}</div>
  </section>;
}

export function MonitorDetailPage() {
  const { id } = useParams();
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
  const [settingsOpen, setSettingsOpen] = useState(true);
  const [lightbox, setLightbox] = useState<"video" | "overlay" | "inferenceInput" | null>(null);
  // Issue #28: 「モニター映像」「推論オーバーレイ」を縦に2枚並べず、タブで1枚だけ
  // 表示する(ページの縦スクロールを削減するため)。非表示側はunmountされるので、
  // 見えていない方のpolling(VideoPreviewのsetInterval)も自動的に止まる。
  const [videoTab, setVideoTab] = useState<"video" | "overlay">("video");
  // 右ペイン各セクションの開閉状態(Frontend表示のみ・永続化なし)。
  // 日常監視では設定編集の頻度が低いため、初期状態は全セクション折りたたみ(画面を短く保つ)。
  const [openSections, setOpenSections] = useState<Record<SectionKey, boolean>>({
    basic: false, source: false, preprocess: false, roi: false, reading: false, inference: false, danger: false,
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
      navigate("/");
    } catch (reason) {
      setError(String(reason));
      setConfirmingDelete(false);
      setDeleting(false);
    }
  };

  // Confirmed(確定値)とRaw(最新推論値、未確定)の区別をUI上で示すための派生値。
  // どちらも既存の5秒/3秒ポーリングで取得済みのデータのみを使用し、新規API呼び出しは発生しない。
  const rawInferenceValue = runtimeDiagnostics?.inference_result ?? null;
  const rawDiffersFromConfirmed = rawInferenceValue != null && rawInferenceValue !== monitor.current_value;
  // Issue #28調査: last_inference_error(DB由来、値が変わるまで残り続ける)だけを見ると、
  // 「model_idを設定し直した後もMODEL_NOT_CONFIGUREDの表示が残る」という誤解を招く。
  // 実際に現在のinference設定でmodel_idが空かどうかは、この派生値で直接判定する
  // (object_detection+ultralyticsのときだけ意味を持つ組み合わせ)。
  const modelMissing = monitor.inference.method === "object_detection" && monitor.inference.engine === "ultralytics" && !monitor.inference.model_id;

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
        {/* Issue #28: Dashboardと同様、Monitor Detailのヘッダーからもキャラクターアイコンを
            非表示にする(showIcon=false)。文字ロゴ(ARGUS)自体はBrand内で維持され、
            アセットファイルも削除しない(Brand.tsxのpropで画面ごとに表示を切り替えるだけ)。 */}
        <Brand showIcon={false} />
        <div className="breadcrumbs">Argus / メーター詳細</div>
        <h1>{monitor.display_name}</h1>
        {/* 設定変更・デバッグ時に対象Monitorを取り違えないよう、display_nameとIDを常時明示する(Issue #16)。 */}
        <div className="monitor-id-badge">Monitor ID: {monitor.id}</div>
      </div>
      <div className="topbar-actions">
        <button className="secondary settings-toggle" onClick={() => setSettingsOpen((v) => !v)}>
          {settingsOpen ? "設定を閉じる ▸" : "◂ 設定を表示"}
        </button>
        <button className="secondary" onClick={() => navigate("/")}>＜ 戻る</button>
      </div>
    </header>

    {(error || message) && <div className={`alert ${error ? "error" : "success"}`}>{error || message}</div>}

    <div className={`detail-layout${settingsOpen ? "" : " settings-collapsed"}`}>
      <section className="monitor-column">
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
        {monitor.current_inference_error && !modelMissing && <div className="alert error">{inferenceErrorText(monitor.current_inference_error, monitor.inference.engine)}</div>}
        {/* last_inference_errorは値が変わるまで残り続ける履歴値(粘着性)なので、現在は
            エラーではない(current_inference_errorがnull)場合は、誤って現在のエラーと
            混同されないよう、控えめな「過去のエラー」注記としてのみ表示する。 */}
        {!monitor.current_inference_error && monitor.last_inference_error && !modelMissing && (
          <p className="muted status-note">直近のエラー履歴（現在は解消済み）: {inferenceErrorText(monitor.last_inference_error, monitor.inference.engine)}</p>
        )}

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
              <span><i className="legend-swatch legend-roi" />ユーザー指定ROI</span>
              {runtimeDiagnostics?.pipeline?.roi_mode === "crop_context" && <span><i className="legend-swatch legend-margin" />内部推論crop範囲(context margin適用後)</span>}
              <span><i className="legend-swatch legend-detection" />検出bbox</span>
            </div>
            {runtimeDiagnostics?.pipeline && (
              runtimeDiagnostics.pipeline.engine === "ultralytics" ? (
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

        {monitor.source && <details className="panel debug-details">
          <summary>推論デバッグ（推論入力 / Pipeline診断）</summary>
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
        </details>}
      </section>

      <aside className="settings-column">
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
        <CollapsibleSection title="前処理" open={openSections.preprocess} onToggle={() => toggleSection("preprocess")}>
          <button className="secondary" onClick={() => setEditor("preprocess")}>前処理を編集</button>
        </CollapsibleSection>
        <CollapsibleSection title="ROI（関心領域）" open={openSections.roi} onToggle={() => toggleSection("roi")}>
          {inference.method === "object_detection" && <p className="muted" style={{ fontSize: "0.76rem", margin: "0 0 8px" }}>
            モード: {inference.roi_mode === "crop_context" ? "ROI周辺を切り出して推論（詳細設定）" : "検出結果をROI内に限定（推奨）"}
          </p>}
          <button className="secondary" onClick={() => setEditor("roi")}>ROIを編集</button>
        </CollapsibleSection>
        <ReadingSettingsPanel value={inference.reading} onChange={(reading) => setInference({ ...inference, reading })} open={openSections.reading} onToggleOpen={() => toggleSection("reading")} />
        <InferenceSettings value={inference} onChange={setInference} open={openSections.inference} onToggleOpen={() => toggleSection("inference")} />
        <div className="settings-actions"><button className="save-button" onClick={save}>設定を保存</button></div>

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
      </aside>
    </div>
    {editor === "roi" && <RoiEditor
      monitorId={monitorId}
      initial={inference.roi}
      isObjectDetection={inference.method === "object_detection"}
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
