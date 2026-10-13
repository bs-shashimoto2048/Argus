import { useState } from "react";
import type { ReactNode } from "react";
import type { BaselineStatus, ReadingDiagnostics, ReadingSettings } from "../types";
import { formatDateTimeJst } from "../utils/datetime";
import { stripLeadingZeros } from "../utils/readingFormat";
import { BASELINE_HELP, MODE_HELPS, MODE_LABELS, baselineSourceLabel, candidateDifference, judgement } from "../utils/readingLabels";
import { BaselineChangeDialog, BaselineClearDialog } from "./BaselineDialogs";

// candidateDifference / judgement は readingLabels.ts へ移した(従来のimport先からも使えるよう再exportする)。
export { candidateDifference, judgement };

const numOrNull = (raw: string): number | null => (raw === "" ? null : Number(raw));

/** 読取基準値の取得状態: undefined=読み込み中 / null=取得できない / BaselineStatus。 */
export type BaselineState = BaselineStatus | null | undefined;

function Switch({ checked, onChange, label }: { checked: boolean; onChange: (next: boolean) => void; label: string }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} className={`rs-switch${checked ? " on" : ""}`} onClick={() => onChange(!checked)}>{checked ? "ON" : "OFF"}</button>;
}

function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return <label className={`reading-setting-field${wide ? " compact-wide" : ""}`}><span>{label}</span>{children}</label>;
}

function BaselineCard({ baseline, diagnostics, monotonic }: { baseline: BaselineState; diagnostics: ReadingDiagnostics | null | undefined; monotonic: boolean }) {
  if (baseline === undefined) return <div className="rs-status-card" aria-label="現在の判定状態"><span className="muted">読取基準値を読み込み中…</span></div>;
  if (baseline === null) return <div className="rs-status-card" aria-label="現在の判定状態"><div className="rs-status-row"><span>現在の読取基準値</span><strong>取得できません</strong></div></div>;
  const info = baseline.baseline;
  const baselineValue = info?.value ?? null;
  const candidate = baseline.candidate?.value ?? (baseline.latest_raw ? stripLeadingZeros(baseline.latest_raw) : null) ?? diagnostics?.candidate?.value ?? null;
  const difference = candidateDifference(candidate, baselineValue);
  const result = judgement(monotonic, difference, diagnostics?.confirmed?.validation_status);
  return <div className={`rs-status-card${result?.warn ? " warn" : ""}`} aria-label="現在の判定状態">
    <div className="rs-status-row"><span>現在の読取基準値</span><strong>{baselineValue ?? "未設定"}</strong></div>
    <div className="rs-status-row"><span>最新のAI読取値</span><strong>{candidate ?? "--"}</strong></div>
    <div className="rs-status-row"><span>差</span><strong className={difference?.negative ? "neg" : undefined}>{difference?.text ?? "--"}</strong></div>
    <div className="rs-status-row rs-status-judge"><span>判定</span><strong>{result?.text ?? "--"}</strong></div>
  </div>;
}

/** 読取基準値の詳細(確定日時・決まり方)。見出し行に置き、閉じている間は高さを増やさない。内部管理番号(epoch)は表示しない。 */
function BaselineDetail({ baseline }: { baseline: BaselineState }) {
  if (!baseline) return null;
  const info = baseline.baseline;
  return <details className="rs-status-detail">
    <summary>基準値の詳細</summary>
    <span>{info ? `確定日時 ${formatDateTimeJst(info.confirmed_at)} / 決まり方 ${baselineSourceLabel(info.source)}` : "読取基準値は未設定です（次に正常に確定したAI読取値が自動で設定されます）"}</span>
  </details>;
}

type Props = {
  value: ReadingSettings;
  onChange: (v: ReadingSettings) => void;
  open: boolean;
  onToggleOpen: () => void;
  baseline?: BaselineState; // 読取基準値(表示用。変更・解除は下のダイアログから)。未指定なら基準値の欄は出さない
  diagnostics?: ReadingDiagnostics | null;
  monitorId?: number; // 指定すると、読取基準値の「変更」「未設定に戻す」ボタンを出す
  onBaselineChanged?: (next: BaselineStatus) => void; // 変更・解除の成功後(最新の読取基準値で画面を即時更新する)
};

export function ReadingSettingsPanel({ value, onChange, open, onToggleOpen, baseline, diagnostics, monitorId, onBaselineChanged }: Props) {
  const set = (p: Partial<ReadingSettings>) => onChange({ ...value, ...p });
  const [dialog, setDialog] = useState<"change" | "clear" | null>(null);
  const baselineValue = baseline === undefined ? undefined : baseline === null ? null : (baseline.baseline?.value ?? "");
  const baselineSummary = baselineValue === undefined ? "" : baselineValue === null ? " / 基準値 取得不可" : ` / 基準値 ${baselineValue === "" ? "未設定" : baselineValue}`;
  const canOperateBaseline = monitorId != null && !!baseline && baseline.reading.enabled;
  const percent = value.min_confidence == null ? "" : `= ${Math.round(value.min_confidence * 100)}%`;

  return (
    <section className="panel collapsible-panel reading-settings-panel">
      <button type="button" className="collapsible-header" onClick={onToggleOpen} aria-expanded={open}>
        <span className="chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
        <h3>読取安定化設定</h3>
        <span className="section-summary">{value.enabled ? "有効" : "無効"} / {value.required_matches}回一致 / 減少チェック{value.monotonic ? "ON" : "OFF"}{baselineSummary}</span>
      </button>
      <div className="collapsible-body reading-settings-body" style={open ? undefined : { display: "none" }}>
        <div className="rs-groups">
          <section className="rs-group rs-span-2" aria-label="判定の安定化">
            <h4>判定の安定化</h4>
            <div className="reading-settings-grid cols-4">
              <div className="reading-setting-field"><span>安定化</span><Switch checked={value.enabled} onChange={(enabled) => set({ enabled })} label="安定化" /></div>
              <Field label="判定に使う直近読取回数" wide><input type="number" min="1" value={value.window_size} onChange={(e) => set({ window_size: Number(e.target.value) })} /></Field>
              <Field label="採用に必要な一致回数" wide><input type="number" min="1" value={value.required_matches} onChange={(e) => set({ required_matches: Number(e.target.value) })} /></Field>
              <Field label="採用に必要な最低信頼度" wide><input type="number" min="0" max="1" step=".05" value={value.min_confidence ?? ""} placeholder="未設定" onChange={(e) => set({ min_confidence: numOrNull(e.target.value) })} /></Field>
            </div>
            <p className="rs-hint">直近{value.window_size}回のAI読取結果を使って値を判定します。同じ値が{value.required_matches}回以上確認された場合に採用します。最低信頼度は0〜1で指定します（0.6 = 60%{percent ? `。現在 ${percent}` : ""}）。</p>
          </section>
          <section className="rs-group" aria-label="桁・数値形式">
            <h4>桁・数値形式</h4>
            <div className="reading-settings-grid cols-2">
              <Field label="メーターの表示桁数"><input type="number" min="1" value={value.expected_digits ?? ""} placeholder="未設定" onChange={(e) => set({ expected_digits: numOrNull(e.target.value) === null ? null : Math.trunc(Number(e.target.value)) })} /></Field>
              <Field label="小数部の桁数"><input type="number" min="0" value={value.decimal_position ?? ""} placeholder="未設定" onChange={(e) => set({ decimal_position: numOrNull(e.target.value) })} /></Field>
            </div>
            <p className="rs-hint">表示桁数: AIが読み取る数字の桁数です。異なる桁数の読取値は採用しません。小数部の桁数: 右端から何桁を小数として扱うかを指定します（例: 1 → 3724644 を 372464.4 として扱う）。</p>
          </section>
          <section className="rs-group" aria-label="読取失敗">
            <h4>読取失敗</h4>
            <div className="reading-settings-grid cols-2">
              <Field label="読取不能と判定するまでの連続失敗回数" wide><input type="number" min="1" value={value.max_consecutive_failures} onChange={(e) => set({ max_consecutive_failures: Number(e.target.value) })} /></Field>
            </div>
            <p className="rs-hint">AIが連続してこの回数読み取れなかった場合、読取不能として扱います。</p>
          </section>
          <section className="rs-group rs-span-2" aria-label="積算値チェック">
            <div className="rs-group-head">
              <h4>積算値チェック</h4>
              <span className="rs-admin-note">{BASELINE_HELP}</span>
              <BaselineDetail baseline={baseline} />
            </div>
            <div className="rs-inline">
              <div className="reading-settings-grid cols-2">
                <div className="reading-setting-field"><span>積算値の減少チェック</span><Switch checked={value.monotonic} onChange={(monotonic) => set({ monotonic })} label="積算値の減少チェック" /></div>
                <Field label="1分あたりの最大増加量" wide><input type="number" min="0" value={value.max_rate_per_minute ?? ""} placeholder="制限なし" onChange={(e) => set({ max_rate_per_minute: numOrNull(e.target.value) })} /></Field>
              </div>
              <p className="rs-hint rs-inline-hint" role="note">
                {value.monotonic ? "AI読取値が現在の読取基準値より小さい場合、正式値として採用しません。" : "OFFの場合、読取基準値より小さい値でも、他の判定条件を満たせば採用されます。"}
                {" "}最大増加量: これを超える急な増加は、誤読の可能性があるため採用しません。制限なしの場合はこのチェックを行いません。
              </p>
            </div>
            {baseline !== undefined || diagnostics !== undefined ? <BaselineCard baseline={baseline} diagnostics={diagnostics} monotonic={value.monotonic} /> : null}
            {monitorId != null && <div className="rs-baseline-actions">
              <button type="button" className="secondary small-button" disabled={!canOperateBaseline} onClick={() => setDialog("change")}>基準値を変更</button>
              <button type="button" className="secondary small-button" disabled={!canOperateBaseline} onClick={() => setDialog("clear")}>基準値を未設定に戻す</button>
            </div>}
          </section>
        </div>
        <details className="rs-advanced">
          <summary>詳細設定</summary>
          <p className="rs-hint">小数部の桁数の詳細: 小数点の位置は桁数の検証後に決まり、整数部の先頭の0は正式値（表示・記録）から除去されます（例: "002560" → "25.60"。AI読取値は元の桁列のまま）。未設定（空欄）の場合は小数点を挿入しません。</p>
          <div className="reading-settings-grid cols-3">
            <Field label="判定方式" wide>
              <select value={value.mode} onChange={(e) => set({ mode: e.target.value as ReadingSettings["mode"] })}>
                <option value="majority">{MODE_LABELS.majority}</option>
                <option value="consecutive">{MODE_LABELS.consecutive}</option>
              </select>
            </Field>
            <div className="reading-setting-field"><span>最大値から0へ戻るメーターを許可（Rollover）</span><Switch checked={value.allow_rollover} onChange={(allow_rollover) => set({ allow_rollover })} label="最大値から0へ戻るメーターを許可" /></div>
            {value.allow_rollover && <Field label="戻る前の最大値"><input type="number" min="0" value={value.rollover_max ?? ""} placeholder="未設定" onChange={(e) => set({ rollover_max: numOrNull(e.target.value) })} /></Field>}
          </div>
          <p className="rs-hint">{MODE_HELPS[value.mode]} 最大値から0へ戻る設定: 桁が最大値まで進んだあと、0へ戻るタイプのメーターで使用します。</p>
        </details>
      </div>
      {dialog === "change" && monitorId != null && baseline && <BaselineChangeDialog monitorId={monitorId} status={baseline} onClose={() => setDialog(null)} onDone={(next) => { setDialog(null); onBaselineChanged?.(next); }} />}
      {dialog === "clear" && monitorId != null && baseline && <BaselineClearDialog monitorId={monitorId} status={baseline} onClose={() => setDialog(null)} onDone={(next) => { setDialog(null); onBaselineChanged?.(next); }} />}
    </section>
  );
}
