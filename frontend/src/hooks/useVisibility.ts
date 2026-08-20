import { useEffect, useState } from "react";
import type { RefObject } from "react";

// タブが非表示(他タブ・最小化中等)かどうか。Dashboard pollingを止める判定に使う。
export function usePageVisible(): boolean {
  const [visible, setVisible] = useState(() => document.visibilityState === "visible");
  useEffect(() => {
    const handler = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, []);
  return visible;
}

// 要素が画面内(viewport内)に見えているかどうか。画面外のMonitorCardのpollingを
// 止める判定に使う。少し手前から検知できるようrootMarginを持たせる。
export function useInView<T extends Element>(ref: RefObject<T | null>): boolean {
  const [inView, setInView] = useState(true);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === "undefined") return undefined;
    const observer = new IntersectionObserver(
      ([entry]) => setInView(entry.isIntersecting),
      { rootMargin: "100px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return inView;
}
