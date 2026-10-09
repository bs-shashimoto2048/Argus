import type { RecordState } from "../utils/records";

export function StateBadge({ state }: { state: RecordState }) {
  return <span className={`state-badge tone-${state.tone}`} data-state={state.key}>{state.label}</span>;
}
