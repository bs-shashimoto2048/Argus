import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

// 管理画面のルートガード(VIEWERは入れない)。Backendも同じ操作を403で拒否するため、これは案内の表示(権限境界ではない)。
// 権限の取得が済むまでは何も出さない(ADMINで開き直したときに、ガード画面が一瞬見えないようにする)。
export function AdminOnly({ children }: { children: ReactNode }) {
  const { isAdmin, loaded, adminLoginAvailable, openLogin } = useAuth();
  const navigate = useNavigate();
  if (!loaded) return null;
  if (isAdmin) return <>{children}</>;
  return <main className="page"><section className="panel admin-required" role="alert">
    <h2>管理者ログインが必要です</h2>
    <p className="muted">この画面は管理者のみ利用できます。閲覧モードでは、ダッシュボード・履歴・Monitor Detailの閲覧ができます。</p>
    <div className="settings-actions">
      {adminLoginAvailable && <button type="button" className="primary" onClick={openLogin}>管理者ログイン</button>}
      <button type="button" className="secondary" onClick={() => navigate("/")}>ダッシュボードへ</button>
    </div>
  </section></main>;
}
