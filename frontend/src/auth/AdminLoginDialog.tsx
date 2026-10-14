import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "./AuthContext";

// 小さな管理者ログインダイアログ(パスワードだけ)。ナビの「管理者ログイン」を押したときだけ表示する。
export function AdminLoginDialog() {
  const { loginOpen, closeLogin, login } = useAuth();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (loginOpen) { setPassword(""); setError(""); inputRef.current?.focus(); } }, [loginOpen]);
  useEffect(() => {
    if (!loginOpen) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") closeLogin(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [loginOpen, closeLogin]);

  if (!loginOpen) return null;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!password || busy) return;
    setBusy(true); setError("");
    try { await login(password); setPassword(""); }
    catch (reason) { setError((reason as Error).message); setPassword(""); inputRef.current?.focus(); }
    finally { setBusy(false); }
  };
  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="管理者ログイン">
    <form className="modal admin-login-dialog" onSubmit={submit}>
      <div className="modal-head"><h2>管理者ログイン</h2><button type="button" className="icon-button" onClick={closeLogin} aria-label="閉じる">×</button></div>
      <label>パスワード
        <input ref={inputRef} type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} aria-invalid={error ? true : undefined} />
      </label>
      {error && <p className="alert error small" role="alert">{error}</p>}
      <div className="modal-actions">
        <button type="button" className="secondary" onClick={closeLogin}>キャンセル</button>
        <button type="submit" className="primary" disabled={busy || !password}>{busy ? "確認中…" : "ログイン"}</button>
      </div>
    </form>
  </div>;
}
