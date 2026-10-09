import type { Period, PeriodMode } from "../utils/records";
import { periodError } from "../utils/records";

export type RecordFilterValue = { monitorIds: number[]; period: Period };
type MonitorOption = { id: number; display_name: string };

const periodButtons: { mode: PeriodMode; label: string }[] = [
  { mode: "today", label: "今日" },
  { mode: "last7", label: "過去7日" },
  { mode: "custom", label: "任意期間" },
];

// 履歴のフィルタ。Monitorはプルダウン(「すべてのモニター」または1台)、期間は今日/過去7日/任意期間の3択。
// どの操作も「適用」ボタン無しで即時に反映される(親が変更のたびに履歴を再取得する)。
// monitorsを渡さない(fixedMonitor)場合はMonitor選択を表示しない(Monitor Detailの履歴タブ用)。
export function RecordFilters({ monitors, value, onChange, hideMonitor = false }: { monitors: MonitorOption[]; value: RecordFilterValue; onChange: (next: RecordFilterValue) => void; hideMonitor?: boolean }) {
  const setPeriod = (patch: Partial<Period>) => onChange({ ...value, period: { ...value.period, ...patch } });
  const error = periodError(value.period);
  const selected = value.monitorIds.length === 1 ? String(value.monitorIds[0]) : "";
  return <div className="record-filters">
    {!hideMonitor && <label className="filter-select">
      <select aria-label="モニター" value={selected} onChange={(e) => onChange({ ...value, monitorIds: e.target.value === "" ? [] : [Number(e.target.value)] })}>
        <option value="">すべてのモニター</option>
        {monitors.map((m) => <option key={m.id} value={m.id}>{m.display_name.trim()}</option>)}
      </select>
    </label>}
    <div className="filter-group" role="group" aria-label="表示期間">
      <span className="segmented">
        {periodButtons.map((p) => <button type="button" key={p.mode} className={`segment${value.period.mode === p.mode ? " active" : ""}`} aria-pressed={value.period.mode === p.mode} onClick={() => setPeriod({ mode: p.mode })}>{p.label}</button>)}
      </span>
      {value.period.mode === "custom" && <span className="date-range-box" role="group" aria-label="期間選択">
        <input type="date" aria-label="開始日" value={value.period.startDate} max={value.period.endDate || undefined} onChange={(e) => setPeriod({ startDate: e.target.value })} />
        <span aria-hidden="true">～</span>
        <input type="date" aria-label="終了日" value={value.period.endDate} min={value.period.startDate || undefined} onChange={(e) => setPeriod({ endDate: e.target.value })} />
      </span>}
    </div>
    {error && <div className="filter-error" role="alert">{error}</div>}
  </div>;
}
