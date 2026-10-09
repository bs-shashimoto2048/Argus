import { Routes, Route } from "react-router-dom";
import { AppBackground } from "./components/AppBackground";
import { AppLayout } from "./components/AppLayout";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryPage } from "./pages/HistoryPage";
import { MonitorCreatePage } from "./pages/MonitorCreatePage";
import { MonitorDetailPage } from "./pages/MonitorDetailPage";
import { MonitorsPage } from "./pages/MonitorsPage";
import { SettingsPage } from "./pages/SettingsPage";

// 全画面を共通のAppLayout(上部ナビゲーション)配下に置く。/monitors/new と /monitors/:id は従来どおり。
export default function App() {
  return <div className="app-shell"><AppBackground /><div className="app-content">
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/monitors" element={<MonitorsPage />} />
        <Route path="/monitors/new" element={<MonitorCreatePage />} />
        <Route path="/monitors/:id" element={<MonitorDetailPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  </div></div>;
}
