import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Inference, Monitor, ReadingDiagnostics, Source } from "../types";
import { Brand } from "../components/Brand";
import { InferenceSettings } from "../components/InferenceSettings";
import { ReadingSettingsPanel } from "../components/ReadingSettingsPanel";
import { SourceSettings } from "../components/SourceSettings";
import { VideoPreview } from "../components/VideoPreview";
import { RoiEditor } from "../components/RoiEditor";
import { PreprocessEditor } from "../components/PreprocessEditor";

const labels: Record<string, string> = {
  running: "正常",
  reconnecting: "再接続中",
  error: "映像取得エラー",
  stopped: "停止中",
  connecting: "接続中",
  normal: "正常",
  warning: "要確認",
  connection_error: "通信異常",
  read_error: "読取不能",
};

// 推論エラーコード -> ユーザー向け日本語メッセージ。Pythonの例外や内部詳細は表示しない。
const inferenceErrorMessages: Record<string, string> = {
  MODEL_NOT_CONFIGURED: "モデルが設定されていません",
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
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    api.monitor(monitorId)
      .then((value) => {
        setMonitor(value);
        setSource(value.source);
        setInference(value.inference);
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

  if (!monitor || !inference) {
    return <main className="page"><div className="loading">読み込み中...</div></main>;
  }

  const check = async (value: Source & { password?: string }) => {
    setMessage("接続確認中...");
    try {
      const result = await api.testSource(monitorId, value);
      setMessage(`${result.connected ? "●" : "×"} ${result.message}`);
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

  return <main className="page monitor-detail-page">
    <header className="topbar">
      <div>
        <Brand />
        <div className="breadcrumbs">Argus / メーター詳細</div>
        <h1>{monitor.display_name}</h1>
      </div>
      <button className="secondary" onClick={() => navigate("/")}>＜ 戻る</button>
    </header>

    {(error || message) && <div className={`alert ${error ? "error" : "success"}`}>{error || message}</div>}

    <div className="detail-layout">
      <section className="monitor-column">
        <div className="panel video-panel">
          <div className="result-values-live" aria-live="polite"><span>現在値 <strong>{currentValueText(monitor)}</strong></span><span>信頼度 <strong>{monitor.confidence == null ? "--" : `${(monitor.confidence * 100).toFixed(1)}%`}</strong></span><span>前回値 <strong>{monitor.previous_value ?? "--"}</strong></span></div>
          <div className="section-title">
            <span>モニター映像</span>
            <span className={`status-text ${monitor.status}`}>● {labels[monitor.status] || monitor.status}</span>
          </div>
          {monitor.source ? <VideoPreview monitorId={monitor.id} large /> : <div className="no-video large">映像ソースを設定してください</div>}
        </div>
        {monitor.source && <div className="panel video-panel">
          <div className="section-title"><span>推論オーバーレイ</span></div>
          <VideoPreview monitorId={monitor.id} overlay />
        </div>}
        {monitor.last_inference_error && <div className="alert error">{inferenceErrorText(monitor.last_inference_error, monitor.inference.engine)}</div>}
        <div className="result-panel reading-summary">
          <div><small>現在値（Confirmed）</small><strong>{currentValueText(monitor)}</strong></div>
          <div><small>信頼度</small><strong>{monitor.confidence == null ? "--" : `${(monitor.confidence * 100).toFixed(1)}%`}</strong></div>
          <div><small>前回値</small><strong>{monitor.previous_value ?? "--"}</strong></div>
          <div><small>差分</small><strong>{formatDiff(monitor.current_value, monitor.previous_value)}</strong></div>
        </div>
        {readingDiagnostics && <div>
          <small>
            Raw値: {readingDiagnostics.confirmed.raw_value ?? "--"}
            {readingDiagnostics.confirmed.raw_confidence != null && ` (${(readingDiagnostics.confirmed.raw_confidence * 100).toFixed(0)}%)`}
            {" / 一致 "}{readingDiagnostics.confirmed.agreement_count}/{readingDiagnostics.confirmed.raw_count}
            {readingDiagnostics.consecutive_failures > 0 && ` / 連続失敗 ${readingDiagnostics.consecutive_failures}`}
          </small>
        </div>}
      </section>

      <aside className="settings-column">
        <SourceSettings source={source} onChange={setSource} onCheck={check} />
        <section className="panel future">
          <h3>前処理</h3>
          <button className="secondary" onClick={() => setEditor("preprocess")}>前処理を編集</button>
          <h3>ROI（関心領域）</h3>
          <button className="secondary" onClick={() => setEditor("roi")}>ROIを編集</button>
        </section>
        <ReadingSettingsPanel value={inference.reading} onChange={(reading) => setInference({ ...inference, reading })} />
        <InferenceSettings value={inference} onChange={setInference} />
        <div className="settings-actions"><button className="save-button" onClick={save}>設定を保存</button></div>

        <section className="panel danger-zone">
          <h3>Danger Zone</h3>
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
        </section>
      </aside>
    </div>
    {editor === "roi" && <RoiEditor monitorId={monitorId} initial={inference.roi} onClose={() => setEditor(null)} onSaved={(roi) => setInference({ ...inference, roi })} />}
    {editor === "preprocess" && <PreprocessEditor monitorId={monitorId} roi={inference.roi} initial={inference.preprocessing} onClose={() => setEditor(null)} onSaved={(preprocessing) => setInference({ ...inference, preprocessing })} />}
  </main>;
}
