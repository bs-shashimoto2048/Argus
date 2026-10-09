import { afterEach, describe, expect, it, vi } from "vitest";
import { createEvent, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { get, json, monitor, mockFetch, renderApp, route, storageSettings, storageStatus } from "./helpers";
import type { Call } from "./helpers";

afterEach(() => { vi.unstubAllGlobals(); });

const names: Record<number, string> = { 2: "Digital A", 3: "Digital B", 4: "Drum" };
const base = (id: number) => monitor({ id, display_name: names[id], current_value: String(id * 1000) });

/** サーバー側の表示順を持つ状態付きのモック(PUT /api/monitors/order で更新される)。 */
function orderedServer(initial = [2, 3, 4], putResponse?: () => Response) {
  const state = { order: [...initial] };
  const mocks = mockFetch([
    get("/api/monitors", () => ({ monitors: state.order.map(base) })),
    get("/api/records", { items: [], total: 0, limit: 20, offset: 0 }),
    get("/api/system/data-storage/status", storageStatus),
    get("/api/system/data-storage", storageSettings),
    route("PUT", "/api/monitors/order", (c: Call) => {
      if (putResponse) return putResponse();
      state.order = (c.body as { monitor_ids: number[] }).monitor_ids;
      return json({ monitor_ids: state.order });
    }),
  ]);
  return { state, ...mocks };
}
const rowNames = () => [...document.querySelectorAll(".monitors-table tbody tr")].map((r) => r.querySelector("strong")!.textContent);
const cardNames = () => [...document.querySelectorAll(".monitor-card .card-title")].map((e) => e.textContent);
const putCalls = (calls: Call[]) => calls.filter((c) => c.method === "PUT" && c.url === "/api/monitors/order");
const waitRows = async (n = 3) => { await waitFor(() => expect(document.querySelectorAll(".monitors-table tbody tr")).toHaveLength(n)); };

describe("Dashboard: 保存された表示順で表示する", () => {
  it("APIの順序のまま表示し、フロントで独自にソートしない", async () => {
    orderedServer([4, 2, 3]);
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    expect(cardNames()).toEqual(["Drum", "Digital A", "Digital B"]); // id昇順ではなく、display_order順
  });

  it("履歴のMonitorプルダウンも同じ順序", async () => {
    orderedServer([4, 2, 3]);
    renderApp("/");
    const select = await screen.findByRole("combobox", { name: "モニター" });
    await waitFor(() => expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["すべてのモニター", "Drum", "Digital A", "Digital B"]));
  });
});

describe("モニター管理: 並べ替え", () => {
  it("各行に↑↓ボタンとドラッグハンドルがあり、先頭の↑・末尾の↓は無効", async () => {
    orderedServer();
    renderApp("/monitors");
    await waitRows();
    expect(rowNames()).toEqual(["Digital A", "Digital B", "Drum"]);
    expect(screen.getByRole("button", { name: "Digital A を上へ" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Drum を下へ" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Digital B を上へ" })).toBeEnabled();
    expect(document.querySelectorAll(".drag-handle")).toHaveLength(3);
    expect(document.querySelectorAll(".monitors-table tbody tr[draggable='true']")).toHaveLength(3);
  });

  it("↑↓で並べ替えると、保存ボタン無しで自動保存し(保存中... → 保存済み)、順序を送る", async () => {
    const server = orderedServer();
    const user = userEvent.setup();
    renderApp("/monitors");
    await waitRows();
    await user.click(screen.getByRole("button", { name: "Drum を上へ" }));
    expect(rowNames()).toEqual(["Digital A", "Drum", "Digital B"]); // 即時(楽観的)に反映
    await waitFor(() => expect(putCalls(server.calls)).toHaveLength(1));
    expect(putCalls(server.calls)[0].body).toEqual({ monitor_ids: [2, 4, 3] });
    expect(await screen.findByText("保存済み")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "保存" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Drum を上へ" }));
    await waitFor(() => expect(putCalls(server.calls)).toHaveLength(2));
    expect(putCalls(server.calls)[1].body).toEqual({ monitor_ids: [4, 2, 3] });
    expect(rowNames()).toEqual(["Drum", "Digital A", "Digital B"]);
  });

  it("保存中は「保存中...」を表示し、その間は再操作できない", async () => {
    let release: (r: Response) => void = () => undefined;
    const server = orderedServer();
    server.on(route("PUT", "/api/monitors/order", () => new Promise<Response>((resolve) => { release = resolve; }) as unknown as Response));
    const user = userEvent.setup();
    renderApp("/monitors");
    await waitRows();
    await user.click(screen.getByRole("button", { name: "Digital A を下へ" }));
    expect(await screen.findByText("保存中...")).toBeInTheDocument();
    expect(rowNames()).toEqual(["Digital B", "Digital A", "Drum"]);
    expect(screen.getByRole("button", { name: "Drum を上へ" })).toBeDisabled(); // 保存中は操作不可
    release(json({ monitor_ids: [3, 2, 4] }));
    expect(await screen.findByText("保存済み")).toBeInTheDocument();
  });

  it("ドラッグ&ドロップで並べ替えられ、自動保存される", async () => {
    const server = orderedServer();
    renderApp("/monitors");
    await waitRows();
    const rows = () => [...document.querySelectorAll(".monitors-table tbody tr")] as HTMLElement[];
    const [a, , drum] = rows();
    fireEvent.dragStart(a, { dataTransfer: { setData: vi.fn(), effectAllowed: "" } });
    const over = createEvent.dragOver(drum, { dataTransfer: {} });
    fireEvent(drum, over);
    expect(over.defaultPrevented).toBe(true); // ドロップ可能
    expect(drum).toHaveClass("row-drop-target");
    fireEvent.drop(drum, { dataTransfer: {} });
    await waitFor(() => expect(putCalls(server.calls)).toHaveLength(1));
    expect(putCalls(server.calls)[0].body).toEqual({ monitor_ids: [3, 4, 2] }); // Digital A を末尾へ
    expect(rowNames()).toEqual(["Digital B", "Drum", "Digital A"]);
  });

  it("同じ位置へのドロップでは保存しない", async () => {
    const server = orderedServer();
    renderApp("/monitors");
    await waitRows();
    const [a] = [...document.querySelectorAll(".monitors-table tbody tr")] as HTMLElement[];
    fireEvent.dragStart(a, { dataTransfer: { setData: vi.fn(), effectAllowed: "" } });
    fireEvent.dragOver(a, { dataTransfer: {} });
    fireEvent.drop(a, { dataTransfer: {} });
    await new Promise((r) => setTimeout(r, 50));
    expect(putCalls(server.calls)).toHaveLength(0);
  });

  it("保存に失敗したら元の順へrollbackし、エラーを表示する", async () => {
    const server = orderedServer([2, 3, 4], () => json({ detail: { code: "UNKNOWN_MONITOR", message: "存在しないモニターIDが含まれています" } }, 422));
    const user = userEvent.setup();
    renderApp("/monitors");
    await waitRows();
    await user.click(screen.getByRole("button", { name: "Drum を上へ" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("表示順を保存できませんでした");
    expect(alert).toHaveTextContent("元の順に戻しました");
    expect(rowNames()).toEqual(["Digital A", "Digital B", "Drum"]); // 元の順
    expect(screen.queryByText("保存済み")).not.toBeInTheDocument();
    expect(putCalls(server.calls)).toHaveLength(1);
  });

  it("一覧が更新されていた場合(409)は再読み込みして最新の順に同期する", async () => {
    const server = orderedServer([2, 3, 4], () => json({ detail: { code: "ORDER_STALE", message: "全モニターを指定してください" } }, 409));
    const user = userEvent.setup();
    renderApp("/monitors");
    await waitRows();
    server.state.order = [3, 2, 4]; // 別の画面で順序が変わった
    await user.click(screen.getByRole("button", { name: "Drum を上へ" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("再読み込みしました");
    await waitFor(() => expect(rowNames()).toEqual(["Digital B", "Digital A", "Drum"]));
  });

  it("保存後、Dashboardへ移動(再読込)しても新しい順番で表示される", async () => {
    orderedServer();
    const user = userEvent.setup();
    renderApp("/monitors");
    await waitRows();
    await user.click(screen.getByRole("button", { name: "Drum を上へ" }));
    await user.click(screen.getByRole("button", { name: "Drum を上へ" }));
    await screen.findByText("保存済み");
    await user.click(screen.getByRole("link", { name: "ダッシュボード" }));
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    expect(cardNames()).toEqual(["Drum", "Digital A", "Digital B"]);
  });

  it("保存の定期更新(5秒ごと)の結果で、保存中の順序が一瞬戻らない", async () => {
    let release: (r: Response) => void = () => undefined;
    const server = orderedServer();
    server.on(route("PUT", "/api/monitors/order", () => new Promise<Response>((resolve) => { release = resolve; }) as unknown as Response));
    const user = userEvent.setup();
    renderApp("/monitors");
    await waitRows();
    await user.click(screen.getByRole("button", { name: "Drum を上へ" }));
    await screen.findByText("保存中...");
    // 保存中にサーバーから(まだ古い順で)再取得されても、画面は新しい順のまま
    await new Promise((r) => setTimeout(r, 30));
    expect(rowNames()).toEqual(["Digital A", "Drum", "Digital B"]);
    release(json({ monitor_ids: [2, 4, 3] }));
    await screen.findByText("保存済み");
  });
});

describe("既存の動線", () => {
  it("並べ替えても「詳細へ」でMonitor Detailへ遷移できる", async () => {
    orderedServer();
    const user = userEvent.setup();
    renderApp("/monitors");
    await waitRows();
    await user.click(screen.getByRole("button", { name: "Drum の詳細" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/monitors/4");
  });
});
