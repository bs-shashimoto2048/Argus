import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Clock } from "./Clock";

const links = [
  { to: "/", label: "ダッシュボード", end: true },
  { to: "/monitors", label: "モニター管理", end: false, adminOnly: true },
  { to: "/history", label: "履歴・データ", end: false },
  { to: "/settings", label: "システム設定", end: false, adminOnly: true },
];

// 全画面共通のレイアウト(上部ナビゲーション + コンテンツ領域)。
// /monitors/new と /monitors/:id は「モニター管理」の配下として扱い、ナビの強調表示を維持する。
export function AppLayout() {
  const { isAdmin, adminLoginAvailable, openLogin, logout } = useAuth();
  return <div className="app-layout">
    <header className="app-nav" role="banner">
      <NavLink to="/" className="app-nav-brand" aria-label="ARGUS 遠方監視システム">
        <span className="app-nav-logo">ARGUS</span>
        <span className="app-nav-sub">遠方監視システム</span>
      </NavLink>
      {/* 時計はロゴ(左)の右隣。右側のメニューの位置は変えない。 */}
      <Clock />
      <nav className="app-nav-links" aria-label="メインナビゲーション">
        {links.filter((link) => isAdmin || !("adminOnly" in link)).map((link) => <NavLink key={link.to} to={link.to} end={link.end} className={({ isActive }) => `app-nav-link${isActive ? " active" : ""}`}>{link.label}</NavLink>)}
      </nav>
      {/* 権限表示: 未ログイン=「閲覧モード」(+管理者ログイン)、ADMIN=「管理者」(+ログアウト)。 */}
      <div className="auth-box">
        {isAdmin
          ? <><span className="auth-role admin" title="管理者としてログイン中">管理者</span><button type="button" className="auth-button" onClick={() => void logout()}>ログアウト</button></>
          : <><span className="auth-role viewer" title="閲覧専用です(設定の変更はできません)">閲覧モード</span>{adminLoginAvailable && <button type="button" className="auth-button" onClick={openLogin}>管理者ログイン</button>}</>}
      </div>
    </header>
    <div className="app-layout-content"><Outlet /></div>
  </div>;
}
