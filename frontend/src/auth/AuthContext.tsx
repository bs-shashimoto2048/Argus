import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ADMIN_REQUIRED_EVENT, api } from "../api/client";
import type { AuthRole } from "../api/client";

// 権限(VIEWER / ADMIN)。未ログイン=VIEWER。権限の根拠はBackendの /api/auth/session の応答だけ
// (このContextは「表示を出し分ける」ためのもので、書き込みの可否はBackendが決める)。
type AuthState = {
  role: AuthRole;
  isAdmin: boolean;
  /** ADMIN認証がBackendで設定されているか(未設定なら「管理者ログイン」を出さない)。 */
  adminLoginAvailable: boolean;
  /** 起動時の/api/auth/sessionの取得が済んだか(取得前・失敗時はVIEWER扱い)。 */
  loaded: boolean;
  /** ログイン。パスワードが違えば例外(メッセージは表示用)。 */
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** 管理者ログインのダイアログを開く要求(ナビ・ガード画面から共通で使う)。 */
  loginOpen: boolean;
  openLogin: () => void;
  closeLogin: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<AuthRole>("VIEWER");
  const [adminLoginAvailable, setAvailable] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);

  const refresh = useCallback(() => api.session()
    .then((session) => { setRole(session.role); setAvailable(session.admin_login_available); })
    .catch(() => setRole("VIEWER")) // 取得できないときは安全側(VIEWER)
    .finally(() => setLoaded(true)), []);

  useEffect(() => { void refresh(); }, [refresh]);
  // ADMIN sessionが切れた(書き込みが403になった)ら、画面全体は壊さずroleを取り直してVIEWER表示へ戻す。編集中の入力は各コンポーネントが保持する。
  useEffect(() => {
    const onLost = () => { setRole("VIEWER"); void refresh(); };
    window.addEventListener(ADMIN_REQUIRED_EVENT, onLost);
    return () => window.removeEventListener(ADMIN_REQUIRED_EVENT, onLost);
  }, [refresh]);

  const value = useMemo<AuthState>(() => ({
    role, isAdmin: role === "ADMIN", adminLoginAvailable, loaded, loginOpen,
    login: async (password) => {
      try {
        const session = await api.login(password);
        setRole(session.role); setAvailable(session.admin_login_available); setLoginOpen(false);
      } catch (reason) {
        const status = (reason as { status?: number }).status;
        if (status === 401) throw new Error("パスワードが違います");
        if (status === 429) throw new Error("失敗が続いたため、しばらく待ってからやり直してください");
        if (status === 503) throw new Error("管理者ログインは設定されていません");
        throw new Error("ログインできませんでした");
      }
    },
    logout: async () => {
      try { await api.logout(); } finally { setRole("VIEWER"); void refresh(); }
    },
    openLogin: () => setLoginOpen(true),
    closeLogin: () => setLoginOpen(false),
  }), [role, adminLoginAvailable, loaded, loginOpen, refresh]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  // Provider外(単体で描画する既存の部品テスト等)では、従来どおりの全機能(ADMIN相当)として動かす。画面アプリはApp内で必ずProviderの下にある。
  return value ?? { role: "ADMIN", isAdmin: true, adminLoginAvailable: false, loaded: true, loginOpen: false, login: async () => undefined, logout: async () => undefined, openLogin: () => undefined, closeLogin: () => undefined };
}
