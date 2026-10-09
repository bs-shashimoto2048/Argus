import type { Period, PeriodMode } from "../utils/records";
import { periodError } from "../utils/records";

export type RecordFilterValue = { monitorIds: number[]; period: Period };
type MonitorOption = { id: number; display_name: string };

const periodButtons: { mode: PeriodMode; label: string }[] = [
  { mode: "today", label: "今日" },
  { mode: "last7", label: "過去7日" },
  { mode: "custom", label: "任意期間" },
];

// 履歴のフィルタ(Monitor複数選択 + 期間)。Monitorを1つも選ばない場合は「すべて」。
export function RecordFilters({ monitors, value, onChange }: { monitors: MonitorOption[]; value: RecordFilterValue; onChange: (next: RecordFilterValue) => void }) {
  const toggle = (id: number) => {
    const next = value.monitorIds.includes(id) ? value.monitorIds.filter((x) => x !== id) : [...value.monitorIds, id];
    onChange({ ...value, monitorIds: next });
  };
  const setPeriod = (patch: Partial<Period>) => onChange({ ...value, period: { ...value.period, ...patch } });
  const error = periodError(value.period);
  return <div className="record-filters">
    <div className="filter-group" role="group" aria-label="モニター">
      <span className="filter-label">モニター</span>
      <button type="button" className={`chip${value.monitorIds.length === 0 ? " active" : ""}`} aria-pressed={value.monitorIds.length === 0} onClick={() => onChange({ ...value, monitorIds: [] })}>すべて</button>
      {monitors.map((m) => <button type="button" key={m.id} className={`chip${value.monitorIds.includes(m.id) ? " active" : ""}`} aria-pressed={value.monitorIds.includes(m.id)} onClick={() => toggle(m.id)}>{m.display_name.trim()}</button>)}
    </div>
    <div className="filter-group" role="group" aria-label="期間">
      <span className="filter-label">期間</span>
      {periodButtons.map((p) => <button type="button" key={p.mode} className={`chip${value.period.mode === p.mode ? " active" : ""}`} aria-pressed={value.period.mode === p.mode} onClick={() => setPeriod({ mode: p.mode })}>{p.label}</button>)}
      {value.period.mode === "custom" && <span className="date-range">
        <input type="date" aria-label="開始日" value={value.period.startDate} onChange={(e) => setPeriod({ startDate: e.target.value })} />
        <span>〜</span>
        <input type="date" aria-label="終了日" value={value.period.endDate} onChange={(e) => setPeriod({ endDate: e.target.value })} />
      </span>}
    </div>
    {error && <div className="filter-error" role="alert">{error}</div>}
  </div>;
}
