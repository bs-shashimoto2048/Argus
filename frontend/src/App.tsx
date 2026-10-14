import { Routes, Route } from "react-router-dom";
import { AppBackground } from "./components/AppBackground";
import { AdminLoginDialog } from "./auth/AdminLoginDialog";
import { AdminOnly } from "./auth/AdminOnly";
import { AuthProvider } from "./auth/AuthContext";
import { AppLayout } from "./components/AppLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryPage } from "./pages/HistoryPage";
import { MonitorCreatePage } from "./pages/MonitorCreatePage";
import { MonitorDetailPage } from "./pages/MonitorDetailPage";
import { MonitorsPage } from "./pages/MonitorsPage";
import { SettingsPage } from "./pages/SettingsPage";

// 全画面を共通のAppLayout(上部ナビゲーション)配下に置く。/monitors/new と /monitors/:id は従来どおり。
export default function App() {
  return <AuthProvider><div className="app-shell"><AppBackground /><div className="app-content">
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<DashboardPage />} />
        {/* 管理画面は管理者のみ(VIEWERには案内を表示)。Backendも同じ操作を403で拒否する。 */}
        <Route path="/monitors" element={<AdminOnly><MonitorsPage /></AdminOnly>} />
        <Route path="/monitors/new" element={<AdminOnly><MonitorCreatePage /></AdminOnly>} />
        <Route path="/monitors/:id" element={<MonitorDetailPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<AdminOnly><SettingsPage /></AdminOnly>} />
      </Route>
    </Routes>
    <AdminLoginDialog />
  </div></div></AuthProvider>;
}
