import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Inference, Monitor, Source } from "../types";
import { Brand } from "../components/Brand";
import { InferenceSettings } from "../components/InferenceSettings";
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

  useEffect(() => {
    api.monitor(monitorId)
      .then((value) => {
        setMonitor(value);
        setSource(value.source);
        setInference(value.inference);
      })
      .catch((reason: Error) => setError(reason.message));
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
          <div className="result-values-live" aria-live="polite"><span>現在値 <strong>{monitor.current_value ?? "--"}</strong></span><span>信頼度 <strong>{monitor.confidence == null ? "--" : `${(monitor.confidence * 100).toFixed(1)}%`}</strong></span><span>前回値 <strong>{monitor.previous_value ?? "--"}</strong></span></div>
          <div className="section-title">
            <span>モニター映像</span>
            <span className={`status-text ${monitor.status}`}>● {labels[monitor.status] || monitor.status}</span>
          </div>
          {monitor.source ? <VideoPreview monitorId={monitor.id} large /> : <div className="no-video large">映像ソースを設定してください</div>}
        </div>
        <div className="result-panel reading-summary">
          <div><small>現在値</small><strong>--</strong></div>
          <div><small>信頼度</small><strong>--</strong></div>
          <div><small>前回値</small><strong>--</strong></div>
          <div><small>差分</small><strong>--</strong></div>
        </div>
      </section>

      <aside className="settings-column">
        <SourceSettings source={source} onChange={setSource} onCheck={check} />
        <section className="panel future">
          <h3>前処理</h3>
          <button className="secondary" onClick={() => setEditor("preprocess")}>前処理を編集</button>
          <h3>ROI（関心領域）</h3>
          <button className="secondary" onClick={() => setEditor("roi")}>ROIを編集</button>
        </section>
        <InferenceSettings value={inference} onChange={setInference} />
        <div className="settings-actions"><button className="save-button" onClick={save}>設定を保存</button></div>
      </aside>
    </div>
    {editor === "roi" && <RoiEditor monitorId={monitorId} initial={inference.roi} onClose={() => setEditor(null)} onSaved={(roi) => setInference({ ...inference, roi })} />}
    {editor === "preprocess" && <PreprocessEditor monitorId={monitorId} roi={inference.roi} initial={inference.preprocessing} onClose={() => setEditor(null)} onSaved={(preprocessing) => setInference({ ...inference, preprocessing })} />}
  </main>;
}
