/// <reference types="vite/client" />
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoCell } from "../components/MemoCell";
import { useAutoReload } from "../hooks/useAutoReload";
import { DASHBOARD_RELOAD_OPTIONS, loadDashboardSettings } from "../hooks/useDashboardSettings";
import { get, json, monitor, record, renderApp, route, standardMocks } from "./helpers";
import type { Call } from "./helpers";
import type { ReadingRecord } from "../types";

const reloadSpy = vi.hoisted(() => vi.fn());
vi.mock("../utils/reloadPage", () => ({ reloadPage: reloadSpy }));

const KEY = "argus.dashboardSettings";
beforeEach(() => { localStorage.clear(); reloadSpy.mockClear(); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); localStorage.clear(); });

const rows: ReadingRecord[] = [
  record({ id: 1, monitor_id: 2, monitor_name: "メーター2", hour_bucket: "2026-10-09T08:00:00+09:00", memo: "現場確認済み" }),
  record({ id: 2, monitor_id: 3, monitor_name: "メーター3", hour_bucket: "2026-10-09T08:00:00+09:00", memo: null }),
];
const recordsRoute = get("/api/records", (c: Call) => {
  const ids = new URL(c.url, "http://x").searchParams.getAll("monitor_id").map(Number);
  const items = ids.length ? rows.filter((r) => ids.includes(r.monitor_id)) : rows;
  return { items, total: items.length, limit: 500, offset: 0 };
});
const threeMonitors = [monitor({ id: 2, display_name: "メーター2" }), monitor({ id: 3, display_name: "メーター3" }), monitor({ id: 4, display_name: "メーター4" })];
const withMonitors = () => get("/api/monitors", { monitors: threeMonitors });
const headers = () => [...document.querySelectorAll(".records-table thead th")].map((th) => th.textContent);
const bodyRows = () => document.querySelectorAll(".records-table tbody tr");

describe("単独Monitor選択: モニター列・映像のフォーカス", () => {
  it("すべてのモニターではモニター列を表示し、1台を選ぶと非表示、戻すと再表示(他の列は保たれる)", async () => {
    const user = userEvent.setup();
    standardMocks([withMonitors(), recordsRoute]);
    renderApp("/");
    await waitFor(() => expect(bodyRows()).toHaveLength(2));
    expect(headers()).toEqual(["取得日時", "モニター", "正式値", "前回値", "使用量", "信頼度", "状態", "メモ", "画像", "詳細"]);
    await user.selectOptions(screen.getByRole("combobox", { name: "モニター" }), "2");
    await waitFor(() => expect(bodyRows()).toHaveLength(1));
    expect(headers()).toEqual(["取得日時", "正式値", "前回値", "使用量", "信頼度", "状態", "メモ", "画像", "詳細"]);
    expect(document.querySelectorAll(".records-table tbody tr:first-child td")).toHaveLength(9); // 見出しと列数が一致
    await user.selectOptions(screen.getByRole("combobox", { name: "モニター" }), "");
    await waitFor(() => expect(headers()).toContain("モニター"));
  });

  it("1台選択で非選択のカードだけを薄く(消さない)し、全モニターへ戻すと解除。選択カードは薄くしない", async () => {
    const user = userEvent.setup();
    standardMocks([withMonitors(), recordsRoute]);
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    const dimmed = () => [...document.querySelectorAll(".monitor-card")].map((c) => c.classList.contains("is-dimmed"));
    expect(dimmed()).toEqual([false, false, false]);
    await user.selectOptions(screen.getByRole("combobox", { name: "モニター" }), "3");
    await waitFor(() => expect(dimmed()).toEqual([true, false, true]));
    expect(document.querySelectorAll(".monitor-card")).toHaveLength(3); // カードは残る(配置も変えない)
    await user.selectOptions(screen.getByRole("combobox", { name: "モニター" }), "");
    await waitFor(() => expect(dimmed()).toEqual([false, false, false]));
  });

  it("フィルタ(映像上部)の変更で、グラフ・履歴の取得条件が一緒に切り替わる", async () => {
    const user = userEvent.setup();
    const mocks = standardMocks([withMonitors(), recordsRoute]);
    renderApp("/");
    await waitFor(() => expect(bodyRows()).toHaveLength(2));
    await user.selectOptions(screen.getByRole("combobox", { name: "モニター" }), "4");
    await waitFor(() => {
      const calls = mocks.calls.filter((c) => c.url.startsWith("/api/records?")).map((c) => new URL(c.url, "http://x").searchParams).filter((p) => p.getAll("monitor_id").join() === "4");
      expect(calls.some((p) => p.get("limit") === "1000")).toBe(true); // グラフ
      expect(calls.some((p) => p.get("limit") === "500")).toBe(true); // 履歴
    });
  });
});

describe("メモ(計測履歴)", () => {
  it("メモを表示する(空は「—」)", async () => {
    standardMocks([withMonitors(), recordsRoute]);
    renderApp("/");
    await waitFor(() => expect(bodyRows()).toHaveLength(2));
    expect(within(document.querySelector("tbody tr:nth-child(1) .cell-memo") as HTMLElement).getByText("現場確認済み")).toBeInTheDocument();
    expect(document.querySelector("tbody tr:nth-child(2) .cell-memo")).toHaveTextContent("—");
  });

  it("クリックで編集→Enterで保存(PATCH /api/records/{id}/memo)し、行のメモが更新される", async () => {
    const user = userEvent.setup();
    const patched: Call[] = [];
    standardMocks([withMonitors(), recordsRoute, route("PATCH", "/api/records/2/memo", (c) => { patched.push(c); return json({ ...rows[1], memo: (c.body as { memo: string }).memo }); })]);
    renderApp("/");
    await waitFor(() => expect(bodyRows()).toHaveLength(2));
    await user.click(document.querySelector("tbody tr:nth-child(2) .memo-button") as HTMLElement);
    await user.type(screen.getByRole("textbox", { name: /のメモ$/ }), "再確認{Enter}");
    await waitFor(() => expect(patched).toHaveLength(1));
    expect(patched[0].body).toEqual({ memo: "再確認" });
    await waitFor(() => expect(document.querySelector("tbody tr:nth-child(2) .cell-memo")).toHaveTextContent("再確認"));
    expect(document.querySelector(".memo-editor")).toBeNull();
  });
});

describe("MemoCell(単体)", () => {
  const setup = (onSave: (m: string) => Promise<void>, memo: string | null = "既存", onEditingChange = vi.fn()) => {
    const view = render(<MemoCell recordLabel="r" memo={memo} onSave={onSave} onEditingChange={onEditingChange} />);
    return { ...view, onEditingChange };
  };
  const open = async (user: ReturnType<typeof userEvent.setup>) => { await user.click(screen.getByRole("button", { name: "r のメモを編集" })); return screen.getByRole("textbox") as HTMLInputElement; };

  it("フォーカスアウトで保存する。変更が無ければ保存しない", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    setup(onSave);
    let input = await open(user);
    await user.tab();
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox")).toBeNull();
    input = await open(user);
    await user.type(input, "追記");
    await user.tab();
    await waitFor(() => expect(onSave).toHaveBeenCalledWith("既存追記"));
  });

  it("Escで編集を取り消す(保存しない・入力は破棄)", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    setup(onSave);
    const input = await open(user);
    await user.type(input, "xxx");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("既存")).toBeInTheDocument();
  });

  it("保存中は状態を表示し、失敗したら入力を消さずエラーを表示する(再度保存できる)", async () => {
    const user = userEvent.setup();
    let reject!: (e: Error) => void;
    const onSave = vi.fn()
      .mockImplementationOnce(() => new Promise<void>((_, r) => { reject = r; }))
      .mockResolvedValueOnce(undefined);
    setup(onSave);
    const input = await open(user);
    await user.clear(input);
    await user.type(input, "新しいメモ{Enter}");
    expect(await screen.findByText("保存中…")).toBeInTheDocument();
    await act(async () => { reject(new Error("503")); });
    expect(await screen.findByRole("alert")).toHaveTextContent("保存できません（503）");
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("新しいメモ"); // 入力は残る
    await user.type(screen.getByRole("textbox"), "{Enter}");
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
  });

  it("編集中に履歴が再取得されて(memoが差し替わって)も、入力中のテキストは失われない", async () => {
    const user = userEvent.setup();
    const { rerender } = setup(vi.fn().mockResolvedValue(undefined), "旧");
    const input = await open(user);
    await user.type(input, "入力中");
    rerender(<MemoCell recordLabel="r" memo="サーバー側の新しい値" onSave={vi.fn()} />);
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("旧入力中");
  });

  it("編集中は通知(自動リロード抑止用)がtrue、終われば解除される", async () => {
    const user = userEvent.setup();
    const { onEditingChange, unmount } = setup(vi.fn().mockResolvedValue(undefined));
    expect(onEditingChange).toHaveBeenLastCalledWith(false);
    await open(user);
    expect(onEditingChange).toHaveBeenLastCalledWith(true);
    await user.keyboard("{Escape}");
    expect(onEditingChange).toHaveBeenLastCalledWith(false);
    await open(user);
    unmount();
    expect(onEditingChange).toHaveBeenLastCalledWith(false);
  });

  it("maxLengthは500", async () => {
    const user = userEvent.setup();
    setup(vi.fn());
    expect((await open(user)).maxLength).toBe(500);
  });
});

describe("画面自動リロード: 設定", () => {
  it("既定は『なし』(0)。旧設定(reloadIntervalMinutesなし)でも壊れず、displayFpsは保たれる", () => {
    expect(loadDashboardSettings()).toEqual({ displayFps: 5, reloadIntervalMinutes: 0 });
    localStorage.setItem(KEY, JSON.stringify({ displayFps: 15 }));
    expect(loadDashboardSettings()).toEqual({ displayFps: 15, reloadIntervalMinutes: 0 });
    localStorage.setItem(KEY, JSON.stringify({ displayFps: 15, reloadIntervalMinutes: 7 })); // 不正値は0
    expect(loadDashboardSettings().reloadIntervalMinutes).toBe(0);
  });

  it("選択肢は なし/5分/10分/15分/30分/1時間/2時間/4時間/8時間", () => {
    expect(DASHBOARD_RELOAD_OPTIONS.map((o) => `${o.minutes}:${o.label}`)).toEqual(["0:なし", "5:5分", "10:10分", "15:15分", "30:30分", "60:1時間", "120:2時間", "240:4時間", "480:8時間"]);
  });

  it("設定画面に『画面自動リロード』(Dashboard表示FPSの下)があり、30分/1h/2h/4h/8hを選べてlocalStorageへ保存される。FPSは変わらない", async () => {
    const user = userEvent.setup();
    standardMocks([withMonitors(), recordsRoute]);
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Dashboard設定" }));
    const dialog = screen.getByRole("dialog", { name: "Dashboard設定" });
    const reload = within(dialog).getByRole("combobox", { name: /画面自動リロード/ });
    const fps = within(dialog).getByRole("combobox", { name: /Dashboard表示FPS/ });
    expect(fps.compareDocumentPosition(reload) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(reload).toHaveValue("0");
    expect(within(dialog).getByText(/映像取得・推論設定には影響しません/)).toBeInTheDocument();
    for (const minutes of [30, 60, 120, 240, 480]) {
      await user.selectOptions(reload, String(minutes));
      expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual({ displayFps: 5, reloadIntervalMinutes: minutes });
    }
    await user.selectOptions(fps, "10");
    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual({ displayFps: 10, reloadIntervalMinutes: 480 });
  });

  it("保存した設定は再表示(ブラウザを開き直し)後も保持される", async () => {
    localStorage.setItem(KEY, JSON.stringify({ displayFps: 5, reloadIntervalMinutes: 120 }));
    const user = userEvent.setup();
    standardMocks([withMonitors(), recordsRoute]);
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Dashboard設定" }));
    expect(screen.getByRole("combobox", { name: /画面自動リロード/ })).toHaveValue("120");
  });
});

describe("画面自動リロード: useAutoReload(fake timers)", () => {
  const MIN = 60_000;
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-09T00:00:00Z")); });
  const setHidden = (hidden: boolean) => { Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden }); document.dispatchEvent(new Event("visibilitychange")); };
  afterEach(() => { setHidden(false); });

  it("『なし』(0)ではtimerを作らず、リロードしない", () => {
    renderHook(() => useAutoReload(0, false));
    expect(vi.getTimerCount()).toBe(0);
    act(() => { vi.advanceTimersByTime(100 * 60 * MIN); });
    expect(reloadSpy).not.toHaveBeenCalled();
  });

  it("設定時間が経過したらリロードが1回だけ呼ばれる(その前は呼ばれない)", () => {
    renderHook(() => useAutoReload(30, false));
    act(() => { vi.advanceTimersByTime(30 * MIN - 1); });
    expect(reloadSpy).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(1); });
    expect(reloadSpy).toHaveBeenCalledTimes(1);
    act(() => { vi.advanceTimersByTime(300 * MIN); });
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it("設定変更で古いtimerを解除し、新しい時間で作り直す(多重登録しない)。『なし』へ戻すとtimerも解除", () => {
    const { rerender } = renderHook(({ m }) => useAutoReload(m, false), { initialProps: { m: 30 } });
    act(() => { vi.advanceTimersByTime(10 * MIN); });
    rerender({ m: 60 });
    expect(vi.getTimerCount()).toBe(1);
    act(() => { vi.advanceTimersByTime(30 * MIN); }); // 旧30分のtimerは動かない
    expect(reloadSpy).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(30 * MIN); }); // 変更から60分
    expect(reloadSpy).toHaveBeenCalledTimes(1);
    reloadSpy.mockClear();
    const second = renderHook(({ m }) => useAutoReload(m, false), { initialProps: { m: 5 } });
    second.rerender({ m: 0 });
    expect(vi.getTimerCount()).toBe(0);
    act(() => { vi.advanceTimersByTime(600 * MIN); });
    expect(reloadSpy).not.toHaveBeenCalled();
  });

  it("タブ非表示の間はリロードせず、表示へ戻った時点で期限超過ならリロードする", () => {
    renderHook(() => useAutoReload(30, false));
    setHidden(true);
    act(() => { vi.advanceTimersByTime(45 * MIN); });
    expect(reloadSpy).not.toHaveBeenCalled();
    act(() => { setHidden(false); });
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it("非表示のまま期限前に表示へ戻っても、期限までリロードしない", () => {
    renderHook(() => useAutoReload(30, false));
    setHidden(true);
    act(() => { vi.advanceTimersByTime(10 * MIN); });
    act(() => { setHidden(false); });
    expect(reloadSpy).not.toHaveBeenCalled();
  });

  it("抑止中(編集中・ダイアログ表示中)は期限が来てもリロードせず、解除後に期限超過ならリロードする", () => {
    const { rerender } = renderHook(({ s }) => useAutoReload(30, s), { initialProps: { s: true } });
    act(() => { vi.advanceTimersByTime(40 * MIN); });
    expect(reloadSpy).not.toHaveBeenCalled();
    rerender({ s: false });
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });
});

describe("画面自動リロード: Dashboardでの抑止(fake timers)", () => {
  const MIN = 60_000;
  const seedReload = (minutes: number) => localStorage.setItem(KEY, JSON.stringify({ displayFps: 5, reloadIntervalMinutes: minutes }));
  // 画面全体にfake timersを掛けるとwaitForが進まないため、長い待ち(1分以上のsetTimeout)と時刻だけを手動で進める。
  let now = 0;
  let pending: { id: number; fn: () => void; at: number }[] = [];
  const ready = async () => {
    now = Date.now(); pending = [];
    const realSet = window.setTimeout.bind(window); const realClear = window.clearTimeout.bind(window);
    vi.spyOn(Date, "now").mockImplementation(() => now);
    vi.spyOn(window, "setTimeout").mockImplementation(((fn: () => void, ms?: number, ...args: unknown[]) => {
      if ((ms ?? 0) < MIN) return realSet(fn, ms, ...args);
      const id = 900000 + pending.length + Math.floor(Math.random() * 1000); pending.push({ id, fn, at: now + (ms ?? 0) }); return id;
    }) as unknown as typeof window.setTimeout);
    vi.spyOn(window, "clearTimeout").mockImplementation(((id?: number) => { pending = pending.filter((t) => t.id !== id); realClear(id); }) as typeof window.clearTimeout);
    standardMocks([withMonitors(), recordsRoute]);
    renderApp("/");
    await waitFor(() => expect(bodyRows()).toHaveLength(2));
  };
  const tick = async (minutes: number) => {
    now += minutes * MIN;
    const due = pending.filter((t) => t.at <= now);
    pending = pending.filter((t) => t.at > now);
    await act(async () => { due.forEach((t) => t.fn()); });
  };
  afterEach(() => { vi.restoreAllMocks(); });

  it("設定時間が経過するとDashboardが再読み込みされる", async () => {
    seedReload(5);
    await ready();
    await tick(4);
    expect(reloadSpy).not.toHaveBeenCalled();
    await tick(2);
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it("既定(なし)では何時間経っても再読み込みしない", async () => {
    await ready();
    await tick(600);
    expect(reloadSpy).not.toHaveBeenCalled();
  });

  it("Dashboard設定ダイアログの表示中は再読み込みせず、閉じると期限超過ですぐ再読み込みする", async () => {
    seedReload(5);
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Dashboard設定" }));
    await tick(10);
    expect(reloadSpy).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog", { name: "Dashboard設定" })).getByRole("button", { name: "閉じる" }));
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it("メモ編集中は再読み込みせず、編集が終わると期限超過なら再読み込みする(入力は編集中に失われない)", async () => {
    seedReload(5);
    await ready();
    fireEvent.click(document.querySelector("tbody tr:nth-child(2) .memo-button") as HTMLElement);
    fireEvent.change(screen.getByRole("textbox", { name: /のメモ$/ }), { target: { value: "編集中" } });
    await tick(10);
    expect(reloadSpy).not.toHaveBeenCalled();
    expect((screen.getByRole("textbox", { name: /のメモ$/ }) as HTMLInputElement).value).toBe("編集中");
    fireEvent.keyDown(screen.getByRole("textbox", { name: /のメモ$/ }), { key: "Escape" }); // 取り消し=編集終了
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it("詳細(読取値修正ダイアログを含む)の表示中は再読み込みしない", async () => {
    seedReload(5);
    await ready();
    fireEvent.click(screen.getAllByRole("button", { name: /の詳細$/ })[0]);
    await tick(10);
    expect(reloadSpy).not.toHaveBeenCalled();
  });
});
