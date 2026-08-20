import { useState } from "react";

// Dashboard専用の表示設定。video_fps/inference_fpsとは完全に独立しており、
// Backendへの推論・映像取得設定には一切影響しない(Dashboard側のpreview.jpg
// polling頻度のみを制御するFrontend-onlyの設定)。
export type DashboardDisplayFps = 0.2 | 0.5 | 1 | 2 | 5;

export const DASHBOARD_DISPLAY_FPS_OPTIONS: DashboardDisplayFps[] = [0.2, 0.5, 1, 2, 5];

export type DashboardSettings = {
  displayFps: DashboardDisplayFps;
};

const STORAGE_KEY = "argus.dashboardSettings";
const DEFAULT_SETTINGS: DashboardSettings = { displayFps: 1 };

function isValidFps(value: unknown): value is DashboardDisplayFps {
  return typeof value === "number" && (DASHBOARD_DISPLAY_FPS_OPTIONS as number[]).includes(value);
}

export function loadDashboardSettings(): DashboardSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_SETTINGS, displayFps: isValidFps(parsed?.displayFps) ? parsed.displayFps : DEFAULT_SETTINGS.displayFps };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function saveDashboardSettings(settings: DashboardSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // localStorageが使えない環境でも画面全体を落とさない(設定は保存されないだけ)。
  }
}

export function useDashboardSettings() {
  const [settings, setSettings] = useState<DashboardSettings>(() => loadDashboardSettings());
  const update = (patch: Partial<DashboardSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      saveDashboardSettings(next);
      return next;
    });
  };
  return { settings, update };
}
