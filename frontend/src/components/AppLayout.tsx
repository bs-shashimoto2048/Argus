import { NavLink, Outlet } from "react-router-dom";
import { Clock } from "./Clock";

const links = [
  { to: "/", label: "ダッシュボード", end: true },
  { to: "/monitors", label: "モニター管理", end: false },
  { to: "/history", label: "履歴・データ", end: false },
  { to: "/settings", label: "システム設定", end: false },
];

// 全画面共通のレイアウト(上部ナビゲーション + コンテンツ領域)。
// /monitors/new と /monitors/:id は「モニター管理」の配下として扱い、ナビの強調表示を維持する。
export function AppLayout() {
  return <div className="app-layout">
    <header className="app-nav" role="banner">
      <NavLink to="/" className="app-nav-brand" aria-label="ARGUS 遠方監視システム">
        <span className="app-nav-logo">ARGUS</span>
        <span className="app-nav-sub">遠方監視システム</span>
      </NavLink>
      {/* 時計はロゴ(左)の右隣。右側のメニューの位置は変えない。 */}
      <Clock />
      <nav className="app-nav-links" aria-label="メインナビゲーション">
        {links.map((link) => <NavLink key={link.to} to={link.to} end={link.end} className={({ isActive }) => `app-nav-link${isActive ? " active" : ""}`}>{link.label}</NavLink>)}
      </nav>
    </header>
    <div className="app-layout-content"><Outlet /></div>
  </div>;
}
