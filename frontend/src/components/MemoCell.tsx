import { useEffect, useRef, useState } from "react";

export const MEMO_MAX_LENGTH = 500;

type Props = {
  recordLabel: string;
  memo: string | null;
  // 保存。成功すれば解決し、失敗は例外(入力は残してエラーを表示する)。未指定なら読み取り専用。
  onSave?: (memo: string) => Promise<void>;
  // 編集中かどうか(編集中は画面の自動リロードを抑止する)。
  onEditingChange?: (editing: boolean) => void;
};

// 計測履歴のメモ欄。通常は1行表示(長いものは省略。title=全文)。クリックで入力欄に切り替わり、Enter/フォーカスアウトで保存、Escで取り消す。
// 編集中の入力(draft)はこのセルの中だけで持つため、履歴の定期更新で行が差し替わっても失われない。
export function MemoCell({ recordLabel, memo, onSave, onEditingChange }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = useRef(false); // 保存中・取り消し直後のblurで二重に保存しない
  const current = memo ?? "";

  useEffect(() => { onEditingChange?.(editing); }, [editing]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => onEditingChange?.(false), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing, saving]);

  if (!onSave && !editing) return <span className="memo-text" title={current || undefined}>{current || "—"}</span>;

  const start = () => { setDraft(current); setError(""); setEditing(true); };
  const cancel = () => { busy.current = true; setEditing(false); setError(""); queueMicrotask(() => { busy.current = false; }); };
  const commit = async () => {
    if (busy.current || !onSave) return; // 管理者ログインが切れている間は保存しない(入力は残す)
    if (draft.trim() === current) { setEditing(false); setError(""); return; }
    busy.current = true; setSaving(true); setError("");
    try {
      await onSave(draft);
      setEditing(false);
    } catch (reason) {
      setError(`保存できません（${reason instanceof Error ? reason.message : "エラー"}）`); // 入力は残す
    } finally {
      busy.current = false; setSaving(false);
    }
  };

  if (!editing) {
    return <button type="button" className="memo-button" onClick={start} title={current ? `${current}（クリックで編集）` : "クリックしてメモを入力"} aria-label={`${recordLabel} のメモを編集`}>
      {current ? <span className="memo-text">{current}</span> : <span className="muted">—</span>}
    </button>;
  }
  return <span className="memo-editor">
    <input ref={inputRef} type="text" value={draft} maxLength={MEMO_MAX_LENGTH} disabled={saving} aria-label={`${recordLabel} のメモ`} aria-invalid={error ? true : undefined}
      onChange={(event) => setDraft(event.target.value)} onBlur={() => void commit()}
      onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void commit(); } else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); cancel(); } }} />
    {!onSave && <small className="memo-error" role="status">管理者ログインが切れました。再ログインすると保存できます（Escで破棄）</small>}
    {saving && <small className="muted memo-state" role="status">保存中…</small>}
    {error && <small className="memo-error" role="alert">{error}</small>}
  </span>;
}
