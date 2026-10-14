import { useEffect, useRef } from "react";
import { reloadPage } from "../utils/reloadPage";

/**
 * 画面の自動リロード。Dashboardが表示された時点(または設定を変更した時点)から minutes 分後に画面全体を再読み込みする。
 * - minutes=0 は自動リロードなし(timerを作らない)。設定が変わるたびに古いtimerを解除して作り直す。
 * - タブが非表示(document.hidden)の間はリロードせず、表示へ戻った時点で期限を過ぎていればリロードする。
 * - suspended=true(メモ編集中・修正ダイアログ・設定ダイアログ表示中など)の間もリロードせず、解除された時点で期限超過ならリロードする。
 * Monitor Runtimeの再起動やBackend設定の変更は行わない(ブラウザ上の画面の再読み込みだけ)。
 */
export function useAutoReload(minutes: number, suspended: boolean): void {
  const startedAt = useRef(Date.now());
  const lastMinutes = useRef(minutes);
  useEffect(() => {
    if (lastMinutes.current !== minutes) { lastMinutes.current = minutes; startedAt.current = Date.now(); }
    if (!minutes) return;
    const deadline = startedAt.current + minutes * 60_000;
    const tryReload = () => {
      if (Date.now() < deadline || suspended || document.hidden) return false;
      reloadPage();
      return true;
    };
    if (tryReload()) return;
    const timer = Date.now() < deadline ? window.setTimeout(tryReload, deadline - Date.now()) : undefined;
    const onVisible = () => { if (!document.hidden) tryReload(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { if (timer !== undefined) window.clearTimeout(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [minutes, suspended]);
}
