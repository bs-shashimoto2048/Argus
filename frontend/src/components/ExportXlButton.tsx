import { useState } from "react";
import { api } from "../api/client";
import { addDays, exportErrorMessage, periodToRange } from "../utils/records";
import type { RecordFilterValue } from "./RecordFilters";

const XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

type SaveHandle = { createWritable: () => Promise<{ write: (data: Blob) => Promise<void>; close: () => Promise<void> }> };
type SavePicker = (options: { suggestedName: string; types: { description: string; accept: Record<string, string[]> }[] }) => Promise<SaveHandle>;

/** 提案ファイル名 argus_records_YYYYMMDD_YYYYMMDD.xlsx(期間のJST日付。toは排他的なので前日まで)。 */
export function suggestedExportName(range: { from: string; to: string }): string {
  const first = range.from.slice(0, 10).replace(/-/g, "");
  const last = addDays(range.to.slice(0, 10), -1).replace(/-/g, "");
  return `argus_records_${first}_${last}.xlsx`;
}

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

// 履歴ヘッダーの [ Export (XL) ]。現在のMonitor・期間に該当する全件(未読込の行を含む)を、常に.xlsxで出力する。
// 保存先: showSaveFilePicker(File System Access API)があれば保存ダイアログ、無ければ通常のダウンロード。
// ダイアログは、ユーザー操作(クリック)の直後でしか開けないため、サーバーへの出力依頼より先に開く。
export function ExportXlButton({ filter }: { filter: RecordFilterValue }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const range = periodToRange(filter.period);

  const run = async () => {
    if (!range) { setError("期間が正しくありません。開始日と終了日を確認してください"); return; }
    setError(""); setDone("");
    const suggestedName = suggestedExportName(range);
    const picker = (window as unknown as { showSaveFilePicker?: SavePicker }).showSaveFilePicker;
    let handle: SaveHandle | null = null;
    if (typeof picker === "function") {
      try {
        handle = await picker.call(window, { suggestedName, types: [{ description: "Excelブック (.xlsx)", accept: { [XLSX_TYPE]: [".xlsx"] } }] });
      } catch (reason) {
        if (reason instanceof DOMException && reason.name === "AbortError") return; // ユーザーのキャンセルは何も表示しない
        setError(`保存先を選択できませんでした（${reason instanceof Error ? reason.message : String(reason)}）`);
        return;
      }
    }
    setBusy(true);
    try {
      const result = await api.exportExcelDownload({ monitor_ids: filter.monitorIds, from: range.from, to: range.to, save_to_server: false });
      if (handle) {
        const writable = await handle.createWritable();
        await writable.write(result.blob);
        await writable.close();
      } else {
        triggerDownload(result.blob, suggestedName);
      }
      setDone(`${suggestedName}${result.totalRows != null ? `（${result.totalRows.toLocaleString("ja-JP")}行）` : ""}を出力しました`);
    } catch (reason) {
      setError(exportErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return <>
    <button type="button" className="export-xl-button" onClick={run} disabled={busy || !range} aria-busy={busy} title="現在のモニター・期間の全件をExcel(.xlsx)で出力します">{busy ? "出力中…" : "Export (XL)"}</button>
    {error && <span className="export-xl-message error-text" role="alert">{error}</span>}
    {done && <span className="export-xl-message muted" role="status">{done}</span>}
  </>;
}
