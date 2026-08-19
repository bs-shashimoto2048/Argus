import type { ReadingSettings } from "../types";

const numOrNull = (raw: string): number | null => (raw === "" ? null : Number(raw));

export function ReadingSettingsPanel({ value, onChange }: { value: ReadingSettings; onChange: (v: ReadingSettings) => void }) {
  const set = (p: Partial<ReadingSettings>) => onChange({ ...value, ...p });

  return (
    <section className="panel">
      <h3>読取安定化</h3>
      <label>
        <input type="checkbox" checked={value.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> 安定化を有効にする
      </label>
      <div className="two-col">
        <label>判定ウィンドウ<input type="number" min="1" value={value.window_size} onChange={(e) => set({ window_size: Number(e.target.value) })} /></label>
        <label>必要一致数<input type="number" min="1" value={value.required_matches} onChange={(e) => set({ required_matches: Number(e.target.value) })} /></label>
      </div>
      <div className="two-col">
        <label>最低信頼度<input type="number" min="0" max="1" step=".05" value={value.min_confidence ?? ""} placeholder="未設定" onChange={(e) => set({ min_confidence: numOrNull(e.target.value) })} /></label>
        <label>期待桁数<input type="number" min="1" value={value.expected_digits ?? ""} placeholder="未設定" onChange={(e) => set({ expected_digits: numOrNull(e.target.value) === null ? null : Math.trunc(Number(e.target.value)) })} /></label>
      </div>
      <label>
        <input type="checkbox" checked={value.monotonic} onChange={(e) => set({ monotonic: e.target.checked })} /> 値の減少を許可しない
      </label>
      <div className="two-col">
        <label>最大変化率（/分）<input type="number" min="0" value={value.max_rate_per_minute ?? ""} placeholder="制限なし" onChange={(e) => set({ max_rate_per_minute: numOrNull(e.target.value) })} /></label>
        <label>連続読取失敗許容回数<input type="number" min="1" value={value.max_consecutive_failures} onChange={(e) => set({ max_consecutive_failures: Number(e.target.value) })} /></label>
      </div>
      <details>
        <summary>詳細設定</summary>
        <label>判定方式
          <select value={value.mode} onChange={(e) => set({ mode: e.target.value as ReadingSettings["mode"] })}>
            <option value="majority">多数決（Majority）</option>
            <option value="consecutive">連続一致（Consecutive）</option>
          </select>
        </label>
        <label>小数点位置（右から桁数）<input type="number" min="0" value={value.decimal_position ?? ""} placeholder="未設定" onChange={(e) => set({ decimal_position: numOrNull(e.target.value) })} /></label>
        <label>
          <input type="checkbox" checked={value.allow_rollover} onChange={(e) => set({ allow_rollover: e.target.checked })} /> Rollover（最大値から0への巻き戻り）を許可する
        </label>
        {value.allow_rollover && <label>Rollover最大値<input type="number" min="0" value={value.rollover_max ?? ""} placeholder="未設定" onChange={(e) => set({ rollover_max: numOrNull(e.target.value) })} /></label>}
      </details>
    </section>
  );
}
