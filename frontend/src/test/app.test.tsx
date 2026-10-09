import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { get, monitor, record, renderApp, standardMocks } from "./helpers";

beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-10-09T05:30:00Z")); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("ルーティングと共通レイアウト", () => {
  it("全画面に共通ナビゲーションがあり、各ルートへ遷移できる", async () => {
    standardMocks();
    const user = userEvent.setup();
    renderApp("/");
    const nav = screen.getByRole("navigation", { name: "メインナビゲーション" });
    expect(screen.getByRole("link", { name: "ARGUS 遠方監視システム" })).toBeInTheDocument();
    for (const label of ["ダッシュボード", "モニター管理", "履歴・データ", "システム設定"]) expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    // Phase 5: ページタイトル「ダッシュボード」は置かない(ナビゲーションに同名のリンクがあるため)。
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    expect(screen.queryByRole("heading", { name: "ダッシュボード" })).not.toBeInTheDocument();
    await user.click(within(nav).getByRole("link", { name: "履歴・データ" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/history");
    expect(await screen.findByRole("heading", { name: "履歴・データ" })).toBeInTheDocument();
    await user.click(within(nav).getByRole("link", { name: "システム設定" }));
    expect(await screen.findByRole("heading", { name: "システム設定" })).toBeInTheDocument();
    await user.click(within(nav).getByRole("link", { name: "モニター管理" }));
    expect(await screen.findByRole("heading", { name: "モニター管理" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "モニター管理" })).toHaveClass("active");
  });

  it("既存の /monitors/new は共通レイアウト内で表示される", async () => {
    standardMocks();
    renderApp("/monitors/new");
    expect(await screen.findByRole("heading", { name: "モニター追加" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "メインナビゲーション" })).toBeInTheDocument();
  });
});

describe("Dashboard", () => {
  it("状態サマリーとMonitorカード(正式値・信頼度・取得状態)を表示する", async () => {
    standardMocks([get("/api/monitors", { monitors: [
      monitor({ id: 2, display_name: "エネセン内ガスメータ用２", current_value: "265803" }),
      monitor({ id: 3, display_name: "エネセン内ガスメータ用１\t", current_value: "215836", inference_status: "low_confidence" }),
      monitor({ id: 4, display_name: "食堂前機械室内メータ用", current_value: "372414.3", inference_status: "read_error", confidence: 0.5 }),
    ] })]);
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    expect(screen.getByTestId("count-normal")).toHaveTextContent("1");
    expect(screen.getByTestId("count-warning")).toHaveTextContent("1");
    expect(screen.getByTestId("count-error")).toHaveTextContent("1");
    const cards = document.querySelectorAll(".monitor-card");
    expect(cards).toHaveLength(3);
    expect(within(cards[0] as HTMLElement).getByText("265803")).toBeInTheDocument(); // 先頭0を除いた正式値
    expect(within(cards[0] as HTMLElement).getByText("95.0%")).toBeInTheDocument();
    expect(within(cards[0] as HTMLElement).getByText("取得状態：取得中")).toBeInTheDocument();
    expect(within(cards[2] as HTMLElement).getByText("372414.3")).toBeInTheDocument();
    expect(within(cards[1] as HTMLElement).getByText("エネセン内ガスメータ用１")).toBeInTheDocument(); // 末尾のタブは表示に出さない
  });

  it("最新の記録が carried_forward のMonitorカードに「前回確定値を保持」と棄却Rawを補助表示する", async () => {
    const carried = record({ id: 9, monitor_id: 3, value: "215858", raw_value: "0215850", value_source: "carried_forward", validation_status: "decrease_detected", recorded_at: "2026-10-08T23:00:20" });
    standardMocks([get("/api/records", { items: [carried], total: 1, limit: 100, offset: 0 })]);
    renderApp("/");
    await screen.findAllByText("前回確定値を保持");
    const badge = document.querySelector(".monitor-card .carried-badge") as HTMLElement;
    expect(badge).toHaveTextContent("前回確定値を保持");
    expect(badge).toHaveTextContent("Raw 0215850");
    expect(badge).toHaveTextContent("decrease_detected");
    expect(document.querySelectorAll(".monitor-card .carried-badge")).toHaveLength(1);
  });

  it("下部に計測履歴(初期表示は本日)が表示される", async () => {
    const mocks = standardMocks([get("/api/records", { items: [record({ id: 1 })], total: 1, limit: 20, offset: 0 })]);
    renderApp("/");
    expect(await screen.findByText("1時間ごとに自動記録（毎時00分）。詳細な検索・Excel出力は「履歴・データ」から行えます。")).toBeInTheDocument();
    await waitFor(() => expect(mocks.calls.some((c) => c.url.startsWith("/api/records?") && c.url.includes("limit=500"))).toBe(true));
    const url = new URL(mocks.calls.filter((c) => c.url.startsWith("/api/records?") && c.url.includes("limit=500")).pop()!.url, "http://x");
    expect(url.searchParams.get("from")).toBe("2026-10-09T00:00:00+09:00");
    expect(url.searchParams.get("to")).toBe("2026-10-10T00:00:00+09:00");
    expect(screen.queryByRole("button", { name: "Excel出力" })).not.toBeInTheDocument(); // Excel出力は履歴・データ画面
  });
});

describe("モニター管理", () => {
  it("3台を一覧表示し、詳細へ遷移できる", async () => {
    standardMocks();
    const user = userEvent.setup();
    renderApp("/monitors");
    const rows = await waitFor(() => { const r = document.querySelectorAll(".monitors-table tbody tr"); expect(r).toHaveLength(3); return r; });
    expect(within(rows[0] as HTMLElement).getByText("エネセン内ガスメータ用２")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("drum_production_v1.onnx")).toBeInTheDocument();
    expect(within(rows[2] as HTMLElement).getByText("372414.3")).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText("正常")).toBeInTheDocument();
    await user.click(within(rows[1] as HTMLElement).getByRole("button", { name: /詳細/ }));
    expect(screen.getByTestId("location")).toHaveTextContent("/monitors/3");
  });

  it("新規モニターへの導線がある", async () => {
    standardMocks();
    const user = userEvent.setup();
    renderApp("/monitors");
    await user.click(await screen.findByRole("button", { name: "＋ 新規モニター" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/monitors/new");
  });
});
