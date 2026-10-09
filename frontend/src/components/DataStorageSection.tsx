import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { DataStorageSettings, DataStorageStatus, StorageTestResult } from "../types";
import { storageStateLabels } from "../utils/records";
import { formatDateTimeJst } from "../utils/datetime";

type Form = { imageRoot: string; excelFolder: string; saveOriginal: boolean; saveOverlay: boolean; warn: string; stop: string };

const toForm = (s: DataStorageSettings): Form => ({
  imageRoot: s.image_root_folder ?? "", excelFolder: s.excel_output_folder ?? "", saveOriginal: s.save_original_image, saveOverlay: s.save_overlay_image,
  warn: String(s.storage_warn_free_gb), stop: String(s.storage_stop_free_gb),
});

export const IMAGE_ROOT_CHANGE_WARNING = "画像保存先を変更すると、以前の保存先にある過去画像を履歴画面から参照できなくなる場合があります。";

// システム設定「データ保存」: 画像保存先 / Excel保存先 / 保存ON/OFF / 空き容量しきい値と、保存状態の表示。
export function DataStorageSection() {
  const [settings, setSettings] = useState<DataStorageSettings | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [status, setStatus] = useState<DataStorageStatus | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [tests, setTests] = useState<{ image?: StorageTestResult | "running"; excel?: StorageTestResult | "running" }>({});

  const loadStatus = useCallback(() => api.dataStorageStatus().then(setStatus).catch(() => setStatus(null)), []);
  useEffect(() => {
    api.dataStorage().then((s) => { setSettings(s); setForm(toForm(s)); }).catch((reason: Error) => setError(`データ保存設定を取得できません（${reason.message}）`));
    loadStatus();
    const timer = window.setInterval(() => { if (!document.hidden) loadStatus(); }, 10000);
    return () => window.clearInterval(timer);
  }, [loadStatus]);

  if (!settings || !form) return <section className="panel"><h2>データ保存</h2>{error ? <div className="alert error" role="alert">{error}</div> : <p className="muted">読み込み中…</p>}</section>;

  const set = (patch: Partial<Form>) => { setForm({ ...form, ...patch }); setMessage(""); };
  const imageRootChanged = form.imageRoot.trim() !== (settings.image_root_folder ?? "");
  const warn = Number(form.warn), stop = Number(form.stop);
  const thresholdError = form.warn.trim() === "" || form.stop.trim() === "" || !Number.isFinite(warn) || !Number.isFinite(stop) || warn < 0 || stop < 0
    ? "しきい値は0以上の数値で入力してください" : stop > warn ? "停止しきい値は警告しきい値以下にしてください" : "";

  const doSave = async () => {
    setConfirming(false); setSaving(true); setError(""); setMessage("");
    try {
      const saved = await api.updateDataStorage({
        image_root_folder: form.imageRoot.trim(), excel_output_folder: form.excelFolder.trim(),
        save_original_image: form.saveOriginal, save_overlay_image: form.saveOverlay, storage_warn_free_gb: warn, storage_stop_free_gb: stop,
      });
      setSettings(saved); setForm(toForm(saved)); setMessage("データ保存設定を保存しました");
      loadStatus();
    } catch (reason) {
      setError(`保存できませんでした（${reason instanceof Error ? reason.message : String(reason)}）`);
    } finally {
      setSaving(false);
    }
  };
  // 画像保存先を変更する場合だけ、保存前に確認する(Excel保存先の変更では確認しない)。
  const save = () => { if (imageRootChanged) setConfirming(true); else void doSave(); };

  const runTest = async (target: "image" | "excel") => {
    setTests((t) => ({ ...t, [target]: "running" }));
    const path = (target === "image" ? form.imageRoot : form.excelFolder).trim();
    try {
      const result = await api.testDataStorage(target, path || undefined);
      setTests((t) => ({ ...t, [target]: result }));
    } catch (reason) {
      setTests((t) => ({ ...t, [target]: { ok: false, path: path || null, message: `テストを実行できませんでした（${reason instanceof Error ? reason.message : String(reason)}）`, free_gb: null } }));
    }
  };

  const renderTest = (target: "image" | "excel") => {
    const result = tests[target];
    if (!result) return null;
    if (result === "running") return <div className="muted" role="status">書込みテスト中…</div>;
    return <div className={`alert ${result.ok ? "success" : "error"}`} role="status">{result.message}{result.ok && result.free_gb != null && `（空き容量 ${result.free_gb} GB）`}</div>;
  };

  const stateInfo = status ? storageStateLabels[status.state] : null;
  return <section className="panel data-storage" aria-label="データ保存">
    <h2>データ保存</h2>
    <p className="muted">1時間ごとの計測記録に付ける画像と、Excel出力の保存先を設定します。ローカルのパス（例 D:\ArgusData\images）とUNC（例 \\server\share\Argus\images）に対応します。空欄の場合は既定の保存先（data/images、data/exports）を使います。</p>

    <div className="storage-status" aria-label="保存状態">
      <h3>保存状態</h3>
      {status && stateInfo ? <>
        <div className="storage-state"><span className={`state-badge tone-${stateInfo.tone}`} data-state={status.state}>{stateInfo.label}</span><span className="muted">{stateInfo.hint}</span></div>
        <dl className="status-grid">
          <div><dt>空き容量</dt><dd>{status.free_gb == null ? "--" : `${status.free_gb} GB`}</dd></div>
          <div><dt>警告しきい値</dt><dd>{status.warn_free_gb} GB</dd></div>
          <div><dt>停止しきい値</dt><dd>{status.stop_free_gb} GB</dd></div>
          <div><dt>画像保存Worker</dt><dd>{status.worker_running ? "稼働中" : "停止"}</dd></div>
          <div><dt>待ちキュー</dt><dd>{status.queue_length} 件</dd></div>
          <div><dt>サーキット</dt><dd>{status.circuit_open ? "開(保存を一時停止中)" : "閉(通常)"}</dd></div>
          <div><dt>保存失敗</dt><dd>{status.counts.failed} 件</dd></div>
          <div><dt>保存見送り</dt><dd>{status.counts.dropped} 件</dd></div>
          <div><dt>保存成功(起動後)</dt><dd>{status.counts.ok} 件</dd></div>
          <div><dt>現在の画像保存先</dt><dd className="path">{status.image_root}{status.image_root_is_default && "（既定）"}</dd></div>
        </dl>
        {status.last_error && <div className="muted small">直近のエラー：{status.last_error}{status.last_error_at && `（${formatDateTimeJst(status.last_error_at)}）`}</div>}
      </> : <p className="muted">保存状態を取得できません。</p>}
    </div>

    <div className="storage-form">
      <label>画像保存先
        <input type="text" value={form.imageRoot} placeholder={settings.effective_image_root} onChange={(e) => set({ imageRoot: e.target.value })} />
      </label>
      <div className="storage-test"><button type="button" className="secondary" onClick={() => void runTest("image")} aria-label="画像保存先の書込みテスト">書込みテスト</button>{renderTest("image")}</div>

      <label>Excel保存先
        <input type="text" value={form.excelFolder} placeholder={settings.effective_excel_output_folder} onChange={(e) => set({ excelFolder: e.target.value })} />
      </label>
      <div className="storage-test"><button type="button" className="secondary" onClick={() => void runTest("excel")} aria-label="Excel保存先の書込みテスト">書込みテスト</button>{renderTest("excel")}</div>

      <label className="check"><input type="checkbox" checked={form.saveOriginal} onChange={(e) => set({ saveOriginal: e.target.checked })} /> 元画像を保存</label>
      <label className="check"><input type="checkbox" checked={form.saveOverlay} onChange={(e) => set({ saveOverlay: e.target.checked })} /> 推論画像を保存</label>
      <div className="threshold-row">
        <label>容量警告しきい値 (GB)<input type="number" min="0" step="1" value={form.warn} onChange={(e) => set({ warn: e.target.value })} /></label>
        <label>容量停止しきい値 (GB)<input type="number" min="0" step="1" value={form.stop} onChange={(e) => set({ stop: e.target.value })} /></label>
      </div>
      {thresholdError && <div className="filter-error" role="alert">{thresholdError}</div>}
      {error && <div className="alert error" role="alert">{error}</div>}
      {message && <div className="alert success" role="status">{message}</div>}
      <button type="button" onClick={save} disabled={saving || !!thresholdError}>{saving ? "保存中…" : "保存"}</button>
    </div>

    {confirming && <div className="modal-backdrop" role="alertdialog" aria-modal="true" aria-label="画像保存先の変更の確認">
      <div className="modal export-modal">
        <div className="modal-head"><h2>画像保存先を変更しますか？</h2></div>
        <div className="alert warning">{IMAGE_ROOT_CHANGE_WARNING}</div>
        <p className="muted">記録にはフォルダの「相対パス」だけを保存しているため、保存先を変えると、旧保存先の画像は履歴画面のDrawerで「読み込めません」になります。旧保存先のフォルダ内の画像ファイルそのものは削除されません（必要なら新しい保存先へコピーしてください）。</p>
        <dl className="export-result"><dt>変更前</dt><dd>{settings.effective_image_root}</dd><dt>変更後</dt><dd>{form.imageRoot.trim() || "既定（data/images）"}</dd></dl>
        <div className="modal-actions"><button type="button" className="secondary" onClick={() => setConfirming(false)}>キャンセル</button><button type="button" className="danger" onClick={() => void doSave()}>変更して保存</button></div>
      </div>
    </div>}
  </section>;
}
