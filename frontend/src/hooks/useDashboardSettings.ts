import { useState } from "react";

// Dashboard専用の表示設定。video_fps/inference_fpsとは完全に独立しており、
// Backendへの推論・映像取得設定には一切影響しない(Dashboard側のpreview.jpg
// polling頻度のみを制御するFrontend-onlyの設定)。
export type DashboardDisplayFps = 1 | 2 | 5 | 10 | 15 | 20 | 30;

export const DASHBOARD_DISPLAY_FPS_OPTIONS: DashboardDisplayFps[] = [1, 2, 5, 10, 15, 20, 30];
export const DASHBOARD_DISPLAY_FPS_DEFAULT: DashboardDisplayFps = 5;
// この値以上では、ブラウザ・通信の負荷が増えるため設定欄に注意を表示する。
export const DASHBOARD_HIGH_FPS = 20;

// 画面の自動リロード間隔(分)。0=自動リロードなし。Dashboard表示FPSと同じくFrontend-only(localStorage)で、Backend設定ではない。
export type DashboardReloadMinutes = 0 | 5 | 10 | 15 | 30 | 60 | 120 | 240 | 480;
export const DASHBOARD_RELOAD_OPTIONS: { minutes: DashboardReloadMinutes; label: string }[] = [
  { minutes: 0, label: "なし" }, { minutes: 5, label: "5分" }, { minutes: 10, label: "10分" }, { minutes: 15, label: "15分" }, { minutes: 30, label: "30分" },
  { minutes: 60, label: "1時間" }, { minutes: 120, label: "2時間" }, { minutes: 240, label: "4時間" }, { minutes: 480, label: "8時間" },
];

export type DashboardSettings = {
  displayFps: DashboardDisplayFps;
  reloadIntervalMinutes: DashboardReloadMinutes;
};

const STORAGE_KEY = "argus.dashboardSettings";
const DEFAULT_SETTINGS: DashboardSettings = { displayFps: DASHBOARD_DISPLAY_FPS_DEFAULT, reloadIntervalMinutes: 0 };

function isValidFps(value: unknown): value is DashboardDisplayFps {
  return typeof value === "number" && (DASHBOARD_DISPLAY_FPS_OPTIONS as number[]).includes(value);
}

function isValidReload(value: unknown): value is DashboardReloadMinutes {
  return typeof value === "number" && DASHBOARD_RELOAD_OPTIONS.some((option) => option.minutes === value);
}

export function loadDashboardSettings(): DashboardSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_SETTINGS, displayFps: isValidFps(parsed?.displayFps) ? parsed.displayFps : DEFAULT_SETTINGS.displayFps, reloadIntervalMinutes: isValidReload(parsed?.reloadIntervalMinutes) ? parsed.reloadIntervalMinutes : 0 };
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
