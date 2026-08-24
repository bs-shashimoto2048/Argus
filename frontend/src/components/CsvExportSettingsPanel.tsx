import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CsvExportStatus } from "../types";
import { formatDateTimeJst } from "../utils/datetime";

function outcomeLabel(status: string): string {
  if (status === "written") return "出力済み";
  if (status === "skipped_already_exported") return "この時間帯は既に出力済み";
  return "エラー";
}

// Dashboard表示FPS(useDashboardSettings、Frontend-only/localStorage)とは独立させる。
// CSV出力の有効/無効・出力フォルダはBackend(SystemSettings)側で永続化し、実際に
// ファイルを書き出すのもBackendの1時間ごとBackground Worker(runtime/csv_export_worker.py)
// のため、状態はBackend APIから取得・保存する(localStorageは使わない、Issue #17)。
export function CsvExportSettingsPanel() {
  const [status, setStatus] = useState<CsvExportStatus | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [folder, setFolder] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);

  const load = () => api.csvExportStatus().then((result) => {
    setStatus(result);
    setEnabled(result.enabled);
    setFolder(result.output_folder ?? "");
  }).catch(() => undefined);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const save = async () => {
    setSaving(true); setError(""); setMessage("");
    try {
      await api.updateCsvExportSettings({ enabled, output_folder: folder.trim() || null });
      setMessage("保存しました");
      await load();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setSaving(false);
    }
  };

  const runNow = async () => {
    setRunning(true); setError(""); setMessage("");
    try {
      const result = await api.runCsvExportNow();
      const summary = result.outcomes.map((o) => `${o.display_name}: ${outcomeLabel(o.status)}`).join(" / ");
      setMessage(result.outcomes.length ? `実行しました（${summary}）` : "Monitorが登録されていません");
      await load();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="panel csv-export-panel">
      <h3>CSV出力</h3>
      <label>
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> CSV出力を有効にする（1時間ごと・Asia/Tokyo基準の毎時0分）
      </label>
      <label>
        出力フォルダ
        <input value={folder} placeholder={"例: C:\\Argus\\csv または \\\\server\\share\\argus-csv"} onChange={(e) => setFolder(e.target.value)} />
      </label>
      <p className="muted" style={{ fontSize: "0.74rem", margin: "-4px 0 8px" }}>
        本番: <code>argus_hourly_readings.csv</code>（1時間ごと・全Monitor分を追記） / テスト: <code>argus_hourly_readings_test.csv</code>（「今すぐエクスポート」で何度でも追記、本番の重複防止・最終出力日時には影響しません）
      </p>
      <div className="modal-actions csv-export-actions">
        <button className="secondary" onClick={runNow} disabled={running || !folder.trim()}>{running ? "実行中..." : "今すぐエクスポート（テスト用）"}</button>
        <button className="primary" onClick={save} disabled={saving}>{saving ? "保存中..." : "保存"}</button>
      </div>
      {message && <p className="muted csv-export-message">{message}</p>}
      {error && <div className="alert error">{error}</div>}
      {status && (
        <div className="csv-export-status">
          <p className="muted" style={{ fontSize: "0.76rem" }}>
            Worker: {status.worker_running ? "稼働中" : "停止中"}
            {status.last_tick_at && ` / 最終チェック: ${formatDateTimeJst(status.last_tick_at)}`}
            {status.last_test_run_at && ` / テスト出力 最終実行: ${formatDateTimeJst(status.last_test_run_at)}`}
          </p>
          {status.monitors.length > 0 && (
            <table className="diagnostics-table csv-export-table">
              <thead><tr><th>Monitor</th><th>本番 最終出力(時間帯)</th><th>本番 最終出力日時</th><th>直近エラー</th></tr></thead>
              <tbody>
                {status.monitors.map((m) => (
                  <tr key={m.monitor_id}>
                    <td>{m.display_name}（ID:{m.monitor_id}）</td>
                    <td>{formatDateTimeJst(m.last_exported_hour)}</td>
                    <td>{formatDateTimeJst(m.last_exported_at)}</td>
                    <td>{m.last_error ?? "--"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      <p className="muted" style={{ fontSize: "0.74rem", marginTop: 8 }}>
        出力対象は安定化済みのConfirmed値です（Raw値は出力しません）。credential/URL等はCSVに含まれません。
        ファイルは「Monitor名_ID.csv」として出力フォルダ内へ直接作成されます（サブフォルダ等、指定フォルダ外へは出力しません）。
      </p>
    </section>
  );
}
