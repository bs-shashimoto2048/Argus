import { useState } from "react";
import { api } from "../api/client";
import type { ExcelExportSaved } from "../types";
import { exportErrorMessage, periodToRange } from "../utils/records";
import type { RecordFilterValue } from "./RecordFilters";

type Mode = "download" | "server";

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// 履歴・データ画面のExcel出力。現在のMonitor/期間フィルタをそのままPOST /api/records/export/excelへ渡す。
export function ExcelExportPanel({ filter }: { filter: RecordFilterValue }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("download");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{ kind: "download"; filename: string; rows: number | null } | { kind: "server"; result: ExcelExportSaved } | null>(null);
  const range = periodToRange(filter.period);

  const run = async () => {
    if (!range) { setError("期間が正しくありません。開始日と終了日を確認してください"); return; }
    setBusy(true); setError(""); setDone(null);
    const body = { monitor_ids: filter.monitorIds, from: range.from, to: range.to, save_to_server: mode === "server" };
    try {
      if (mode === "download") {
        const result = await api.exportExcelDownload(body);
        triggerDownload(result.blob, result.filename);
        setDone({ kind: "download", filename: result.filename, rows: result.totalRows });
      } else {
        setDone({ kind: "server", result: await api.exportExcelSave(body) });
      }
    } catch (reason) {
      setError(exportErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return <>
    <button type="button" onClick={() => { setOpen(true); setError(""); setDone(null); }}>Excel出力</button>
    {open && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Excel出力">
      <div className="modal export-modal">
        <div className="modal-head"><h2>Excel出力</h2><button type="button" className="icon-button" onClick={() => setOpen(false)} aria-label="閉じる">×</button></div>
        <p className="muted">現在のフィルタ（{filter.monitorIds.length === 0 ? "すべてのモニター" : `${filter.monitorIds.length}台を選択`}・{range ? `${range.from.slice(0, 10)} 〜 ${range.to.slice(0, 10)}（終了日は含まない）` : "期間未設定"}）の1時間計測記録を、モニターごとのシートにしたExcelへ出力します。</p>
        <fieldset className="export-mode">
          <label><input type="radio" name="export-mode" checked={mode === "download"} onChange={() => setMode("download")} /> ダウンロード（このブラウザへ保存）</label>
          <label><input type="radio" name="export-mode" checked={mode === "server"} onChange={() => setMode("server")} /> サーバー保存（システム設定の「Excel保存先」へ保存）</label>
        </fieldset>
        {error && <div className="alert error" role="alert">{error}</div>}
        {done?.kind === "download" && <div className="alert success" role="status">ダウンロードしました：{done.filename}{done.rows != null && `（${done.rows}行）`}</div>}
        {done?.kind === "server" && <div className="alert success" role="status">
          <div>サーバーへ保存しました</div>
          <dl className="export-result">
            <dt>ファイル名</dt><dd>{done.result.filename}</dd>
            <dt>保存先</dt><dd>{done.result.path}</dd>
            <dt>行数</dt><dd>{done.result.total_rows}行</dd>
            <dt>シート数</dt><dd>{done.result.sheets.length}（{done.result.sheets.map((s) => `${s.sheet_name}: ${s.rows}行`).join(" / ")}）</dd>
          </dl>
          {done.result.image_links_skipped && <div className="muted">画像保存先に接続できなかったため、画像のリンクは付けていません（パスのみ出力）。</div>}
        </div>}
        <div className="modal-actions"><button type="button" className="secondary" onClick={() => setOpen(false)}>閉じる</button><button type="button" onClick={run} disabled={busy || !range}>{busy ? "出力中…" : mode === "download" ? "ダウンロード" : "サーバーへ保存"}</button></div>
      </div>
    </div>}
  </>;
}
