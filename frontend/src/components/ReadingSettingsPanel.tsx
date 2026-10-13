import type { ReactNode } from "react";
import type { BaselineStatus, ReadingDiagnostics, ReadingSettings } from "../types";
import { formatDateTimeJst } from "../utils/datetime";
import { stripLeadingZeros } from "../utils/readingFormat";

const numOrNull = (raw: string): number | null => (raw === "" ? null : Number(raw));

// 利用者向けの表示名(内部名は括弧内に残す)。
const modeLabels: Record<ReadingSettings["mode"], string> = { majority: "多数決（majority）", consecutive: "連続一致（consecutive）" };
const baselineSourceLabels: Record<string, string> = { confirmed: "通常確定", operator_rebase: "運用者の再設定（rebase）", db: "保存済みの基準値" };

/** 読取基準値の取得状態: undefined=読み込み中 / null=取得できない / BaselineStatus。 */
export type BaselineState = BaselineStatus | null | undefined;

const decimals = (text: string) => (text.includes(".") ? text.split(".")[1].length : 0);

/** 候補値 - 基準値(小数桁は両者の大きい方に揃える)。数値でなければnull。 */
export function candidateDifference(candidate: string | null | undefined, baseline: string | null | undefined): { text: string; negative: boolean } | null {
  if (!candidate || !baseline) return null;
  const c = Number(candidate), b = Number(baseline);
  if (!Number.isFinite(c) || !Number.isFinite(b)) return null;
  const places = Math.max(decimals(candidate), decimals(baseline));
  const diff = Number((c - b).toFixed(places));
  return { text: `${diff > 0 ? "+" : ""}${diff.toFixed(places)}`, negative: diff < 0 };
}

const statusReasons: Record<string, { text: string; warn: boolean }> = {
  decrease_detected: { text: "基準値未満のため不採用", warn: true },
  invalid_format: { text: "桁数が期待桁数と一致しないため不採用", warn: true },
  rate_exceeded: { text: "変化率が最大変化率を超えたため不採用", warn: true },
  no_reading: { text: "読取失敗が続いているため前回値を保持", warn: true },
  low_confidence: { text: "信頼度が低いため要確認", warn: true },
  pending: { text: "判定中（一致数が不足）", warn: false },
  confirmed: { text: "採用", warn: false },
};

/** 現在の判定(利用者向けの説明)。候補が基準値未満で減少チェックONなら、statusに関わらず「基準値未満のため不採用」。 */
export function judgement(monotonic: boolean, difference: { negative: boolean } | null, validationStatus: string | null | undefined): { text: string; warn: boolean } | null {
  if (monotonic && difference?.negative) return statusReasons.decrease_detected;
  if (validationStatus && statusReasons[validationStatus]) return statusReasons[validationStatus];
  if (difference) return monotonic ? { text: "基準値以上（減少なし）", warn: false } : { text: "減少チェックOFFのため基準値との比較なし", warn: false };
  return null;
}

function Switch({ checked, onChange, label }: { checked: boolean; onChange: (next: boolean) => void; label: string }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} className={`rs-switch${checked ? " on" : ""}`} onClick={() => onChange(!checked)}>{checked ? "ON" : "OFF"}</button>;
}

function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return <label className={`reading-setting-field${wide ? " compact-wide" : ""}`}><span>{label}</span>{children}</label>;
}

/** 基準値の詳細(確定日時・由来・epoch)。見出し行に置き、閉じている間は高さを増やさない。 */
function BaselineDetail({ baseline }: { baseline: BaselineState }) {
  if (!baseline) return null;
  const info = baseline.baseline;
  return <details className="rs-status-detail">
    <summary>基準値の詳細</summary>
    <span>{info ? `確定日時 ${formatDateTimeJst(info.confirmed_at)} / 由来 ${baselineSourceLabels[info.source] ?? info.source} / epoch ${info.epoch}` : "基準値は未設定です（次に正常に確定した値が基準値になります）"}</span>
  </details>;
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
    <div className="rs-status-row"><span>最新候補値</span><strong>{candidate ?? "--"}</strong></div>
    <div className="rs-status-row"><span>差</span><strong className={difference?.negative ? "neg" : undefined}>{difference?.text ?? "--"}</strong></div>
    <div className="rs-status-row rs-status-judge"><span>判定</span><strong>{result?.text ?? "--"}</strong></div>
  </div>;
}

type Props = {
  value: ReadingSettings;
  onChange: (v: ReadingSettings) => void;
  open: boolean;
  onToggleOpen: () => void;
  baseline?: BaselineState; // 読取基準値(read-only表示用)。未指定なら基準値の欄は出さない
  diagnostics?: ReadingDiagnostics | null;
};

export function ReadingSettingsPanel({ value, onChange, open, onToggleOpen, baseline, diagnostics }: Props) {
  const set = (p: Partial<ReadingSettings>) => onChange({ ...value, ...p });
  const baselineValue = baseline === undefined ? undefined : baseline === null ? null : (baseline.baseline?.value ?? "");
  const baselineSummary = baselineValue === undefined ? "" : baselineValue === null ? " / 基準値 取得不可" : ` / 基準値 ${baselineValue === "" ? "未設定" : baselineValue}`;

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
              <Field label="判定ウィンドウ"><input type="number" min="1" value={value.window_size} onChange={(e) => set({ window_size: Number(e.target.value) })} /></Field>
              <Field label="必要一致数"><input type="number" min="1" value={value.required_matches} onChange={(e) => set({ required_matches: Number(e.target.value) })} /></Field>
              <Field label="最低信頼度"><input type="number" min="0" max="1" step=".05" value={value.min_confidence ?? ""} placeholder="未設定" onChange={(e) => set({ min_confidence: numOrNull(e.target.value) })} /></Field>
            </div>
          </section>
          <section className="rs-group" aria-label="桁・数値形式">
            <h4>桁・数値形式</h4>
            <div className="reading-settings-grid cols-2">
              <Field label="期待桁数"><input type="number" min="1" value={value.expected_digits ?? ""} placeholder="未設定" onChange={(e) => set({ expected_digits: numOrNull(e.target.value) === null ? null : Math.trunc(Number(e.target.value)) })} /></Field>
              {/* Issue #17: Backend既存仕様(reading/canonicalizer.py)のUI露出のみ。意味は変えていない: 右からn桁を小数部として切り出す。 */}
              <Field label="小数点位置"><input type="number" min="0" value={value.decimal_position ?? ""} placeholder="未設定" onChange={(e) => set({ decimal_position: numOrNull(e.target.value) })} /></Field>
            </div>
            <p className="rs-hint">期待桁数: 推論結果として期待する数字の桁数。異なる桁数は invalid_format として採用しません。小数点位置: 右から何桁を小数部として扱うか（例: 2 → 12345 は 123.45）。</p>
          </section>
          <section className="rs-group" aria-label="読取失敗">
            <h4>読取失敗</h4>
            <div className="reading-settings-grid cols-2">
              <Field label="連続読取失敗許容回数" wide><input type="number" min="1" value={value.max_consecutive_failures} onChange={(e) => set({ max_consecutive_failures: Number(e.target.value) })} /></Field>
            </div>
            <p className="rs-hint">連続でこの回数読み取れない場合、読取不能として扱います。</p>
          </section>
          <section className="rs-group rs-span-2" aria-label="積算値チェック">
            <div className="rs-group-head">
              <h4>積算値チェック</h4>
              <span className="rs-admin-note">読取基準値のreset / rebase は、診断タブから操作します（この画面では編集できません）。</span>
              <BaselineDetail baseline={baseline} />
            </div>
            <div className="rs-inline">
              <div className="reading-settings-grid cols-2">
                <div className="reading-setting-field"><span>積算値の減少を検出する</span><Switch checked={value.monotonic} onChange={(monotonic) => set({ monotonic })} label="積算値の減少を検出する" /></div>
                <Field label="最大変化率（/分）" wide><input type="number" min="0" value={value.max_rate_per_minute ?? ""} placeholder="制限なし" onChange={(e) => set({ max_rate_per_minute: numOrNull(e.target.value) })} /></Field>
              </div>
              <p className="rs-hint rs-inline-hint" role="note">
                {value.monotonic ? "現在の読取基準値より小さい候補値は、減少と判断して採用しません。" : "OFFの場合、基準値より小さい値でも、他の判定条件を満たせば採用されます。"}
                {" "}最大変化率: 1分あたりに許容する最大増加量。制限なしの場合は急増チェックを行いません。
              </p>
            </div>
            {baseline !== undefined || diagnostics !== undefined ? <BaselineCard baseline={baseline} diagnostics={diagnostics} monotonic={value.monotonic} /> : null}
          </section>
        </div>
        <details className="rs-advanced">
          <summary>詳細設定</summary>
          <p className="rs-hint">小数点位置の詳細: 小数点の位置は桁数の検証後に決まり、整数部の先頭の0は確定値（表示・記録）から除去されます（例: "002560" → "25.60"。Raw値は元の桁列のまま）。未設定（空欄）の場合は小数点を挿入しません。</p>
          <div className="reading-settings-grid cols-3">
            <Field label="判定方式" wide>
              <select value={value.mode} onChange={(e) => set({ mode: e.target.value as ReadingSettings["mode"] })}>
                <option value="majority">{modeLabels.majority}</option>
                <option value="consecutive">{modeLabels.consecutive}</option>
              </select>
            </Field>
            <div className="reading-setting-field"><span>Rollover（最大値から0への巻き戻り）</span><Switch checked={value.allow_rollover} onChange={(allow_rollover) => set({ allow_rollover })} label="Rollover" /></div>
            {value.allow_rollover && <Field label="Rollover最大値"><input type="number" min="0" value={value.rollover_max ?? ""} placeholder="未設定" onChange={(e) => set({ rollover_max: numOrNull(e.target.value) })} /></Field>}
          </div>
        </details>
      </div>
    </section>
  );
}
