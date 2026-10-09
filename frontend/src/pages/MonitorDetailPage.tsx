import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Inference, Monitor, ReadingDiagnostics, RuntimeDiagnostics, Source } from "../types";
import { formatDateTimeJst } from "../utils/datetime";
import { InferenceSettings } from "../components/InferenceSettings";
import { ReadingSettingsPanel } from "../components/ReadingSettingsPanel";
import { conflictMessage, stripLeadingZeros } from "../utils/readingFormat";
import { SourceSettings } from "../components/SourceSettings";
import { VideoPreview } from "../components/VideoPreview";
import { RecordsSection } from "../components/RecordsSection";
import { MonitoringTab } from "../components/MonitoringTab";
import type { Lightbox } from "../components/MonitoringTab";
import { DiagnosticsTab } from "../components/DiagnosticsTab";
import { RoiEditor } from "../components/RoiEditor";
import { PreprocessEditor } from "../components/PreprocessEditor";
import { combinedMonitorStatus, monitorStatusLabels } from "../utils/monitorStatus";
import { currentValueText, formatDiff, inferenceErrorText } from "../utils/monitorDetail";

// 右ペインの各設定セクションを独立して開閉するための共通ラッパー。
// 閉じてもDOMからは外さず(display:noneのみ)、フォーム値・API呼び出しに一切影響しない。
type SectionKey = "basic" | "source" | "preprocess" | "roi" | "reading" | "baseline" | "inference" | "danger";

function CollapsibleSection({ title, summary, open, onToggle, className, children }: { title: string; summary?: string; open: boolean; onToggle: () => void; className?: string; children: React.ReactNode }) {
  return <section className={`panel collapsible-panel${className ? ` ${className}` : ""}`}>
    <button type="button" className="collapsible-header" onClick={onToggle} aria-expanded={open}>
      <span className="chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
      <h3>{title}</h3>
      {summary && <span className="section-summary">{summary}</span>}
    </button>
    <div className="collapsible-body" style={open ? undefined : { display: "none" }}>{children}</div>
  </section>;
}

export type DetailTab = "monitoring" | "history" | "settings" | "diagnostics";
const detailTabs: { key: DetailTab; label: string }[] = [
  { key: "monitoring", label: "監視" },
  { key: "history", label: "履歴" },
  { key: "settings", label: "設定" },
  { key: "diagnostics", label: "診断" },
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
  const [lightbox, setLightbox] = useState<Lightbox>(null);
  // Issue #28: 「モニター映像」「推論オーバーレイ」を縦に2枚並べず、タブで1枚だけ
  // 表示する(ページの縦スクロールを削減するため)。非表示側はunmountされるので、
  // 見えていない方のpolling(VideoPreviewのsetInterval)も自動的に止まる。
  const [videoTab, setVideoTab] = useState<"video" | "overlay">("video");
  // 右ペイン各セクションの開閉状態(Frontend表示のみ・永続化なし)。
  // 日常監視では設定編集の頻度が低いため、初期状態は全セクション折りたたみ(画面を短く保つ)。
  const [openSections, setOpenSections] = useState<Record<SectionKey, boolean>>({
    basic: true, source: true, preprocess: false, roi: false, reading: false, baseline: true, inference: true, danger: false,
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
    <header className="topbar detail-header">
      <div>
        <div className="breadcrumbs">モニター管理 / メーター詳細<span className="monitor-id-badge"> ・ Monitor ID: {monitor.id}</span></div>
        <h1>{monitor.display_name}</h1>
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
      {tab === "monitoring" && <MonitoringTab monitor={monitor} rawInferenceValue={rawInferenceValue} rawDiffersFromConfirmed={rawDiffersFromConfirmed} modelMissing={modelMissing}
        readingDiagnostics={readingDiagnostics} runtimeDiagnostics={runtimeDiagnostics} videoTab={videoTab} onVideoTab={setVideoTab} lightbox={lightbox} onLightbox={setLightbox} />}

      {tab === "history" && <RecordsSection monitors={[{ id: monitor.id, display_name: monitor.display_name }]} fixedMonitorId={monitor.id} title="この Monitor の計測履歴" description="1時間ごとの正式な記録（reading_records）。" size="tall" />}

      {tab === "settings" && <section className="settings-tab">
        <div className="settings-columns">
          <div className="settings-col settings-col-left">
        <CollapsibleSection title="基本情報" summary={`${basicInfo.display_name.trim()} / Monitor ID ${monitor.id}`} open={openSections.basic} onToggle={() => toggleSection("basic")}>
          <div className="basic-grid">
            <label>
              内部名（name）
              <input required pattern="[A-Za-z0-9_-]+" value={basicInfo.name} onChange={(e) => setBasicInfo({ ...basicInfo, name: e.target.value })} placeholder="gas_meter_01" />
            </label>
            <label>表示名<input required value={basicInfo.display_name} onChange={(e) => setBasicInfo({ ...basicInfo, display_name: e.target.value })} /></label>
            <label>設置場所<input value={basicInfo.location} onChange={(e) => setBasicInfo({ ...basicInfo, location: e.target.value })} /></label>
          </div>
          <details className="settings-hint">
            <summary>内部名について</summary>
            <p className="muted">
              半角英数字・アンダースコア・ハイフンのみ（例: <code>gas_meter_01</code>）。他のMonitorと重複できません。
              実行時の識別には常にMonitor IDが使われるため、変更してもRuntime・映像・CSVの過去行には影響しません
              （CSVの新しい追記行から新しい内部名が反映されます）。
            </p>
          </details>
          <div className="settings-actions"><button className="save-button" onClick={saveBasicInfo} disabled={savingBasicInfo || !basicInfo.display_name.trim() || !/^[A-Za-z0-9_-]+$/.test(basicInfo.name)}>{savingBasicInfo ? "保存中..." : "基本情報を保存"}</button></div>
        </CollapsibleSection>
        <SourceSettings source={source} onChange={setSource} onCheck={check} open={openSections.source} onToggleOpen={() => toggleSection("source")} />
        <CollapsibleSection title="ROI（関心領域）" summary={`幅${(inference.roi.width * 100).toFixed(0)}% × 高さ${(inference.roi.height * 100).toFixed(0)}%`} open={openSections.roi} onToggle={() => toggleSection("roi")}>
          {inference.method === "object_detection" && inference.engine === "cpp_onnx" && <p className="muted" style={{ fontSize: "0.76rem", margin: "0 0 8px" }}>
            C++ ONNXではROIそのものを切り出して推論します（ROIモードは適用されません）。
          </p>}
          {inference.method === "object_detection" && inference.engine !== "cpp_onnx" && <p className="muted" style={{ fontSize: "0.76rem", margin: "0 0 8px" }}>
            モード: {inference.roi_mode === "crop_context" ? "ROI周辺を切り出して推論（詳細設定）" : "検出結果をROI内に限定（推奨）"}
          </p>}
          <button className="secondary" onClick={() => setEditor("roi")}>ROIを編集</button>
        </CollapsibleSection>
        <CollapsibleSection title="前処理" summary={`${Object.keys(inference.preprocessing ?? {}).length}項目を設定`} open={openSections.preprocess} onToggle={() => toggleSection("preprocess")}>
          <button className="secondary" onClick={() => setEditor("preprocess")}>前処理を編集</button>
        </CollapsibleSection>
          </div>
          <div className="settings-col settings-col-right">
        <InferenceSettings value={inference} onChange={setInference} open={openSections.inference} onToggleOpen={() => toggleSection("inference")} />
        <ReadingSettingsPanel value={inference.reading} onChange={(reading) => setInference({ ...inference, reading })} open={openSections.reading} onToggleOpen={() => toggleSection("reading")} />
        <section className="panel settings-save" aria-label="保存関連">
          <h3>保存</h3>
          <div className="settings-actions"><button className="save-button" onClick={save} disabled={cppModelMissing} title={cppModelMissing ? "C++ ONNXではモデルを選択してください" : undefined}>設定を保存</button></div>
          <p className="muted tiny">映像ソース・推論エンジン / モデル・前処理・ROI・読取安定化設定をまとめて保存します（基本情報は上の「基本情報を保存」）。</p>
        </section>
          <div className="settings-admin">
          <CollapsibleSection title="危険な操作" summary="モニターの削除など（通常の設定とは別）" open={openSections.danger} onToggle={() => toggleSection("danger")} className="danger-zone">
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
          </div>
          </div>
        </div>
      </section>}

      {tab === "diagnostics" && <DiagnosticsTab monitor={monitor} readingDiagnostics={readingDiagnostics} runtimeDiagnostics={runtimeDiagnostics} lightbox={lightbox} onLightbox={setLightbox} />}
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
