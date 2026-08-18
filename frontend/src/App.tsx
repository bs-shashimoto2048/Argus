import {Routes,Route} from "react-router-dom";
import { AppBackground } from "./components/AppBackground";
import {DashboardPage} from "./pages/DashboardPage";
import {MonitorCreatePage} from "./pages/MonitorCreatePage";
import {MonitorDetailPage} from "./pages/MonitorDetailPage";
export default function App(){return <div className="app-shell"><AppBackground/><div className="app-content"><Routes><Route path="/" element={<DashboardPage/>}/><Route path="/monitors/new" element={<MonitorCreatePage/>}/><Route path="/monitors/:id" element={<MonitorDetailPage/>}/></Routes></div></div>}
