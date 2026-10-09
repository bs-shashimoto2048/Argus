/// <reference types="vite/client" />
import { afterEach, describe, expect, it, vi } from "vitest";
import { createEvent, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { get, json, monitor, mockFetch, renderApp, route, storageSettings, storageStatus } from "./helpers";
import type { Call } from "./helpers";
import stylesheet from "../styles.css?raw";

afterEach(() => { vi.unstubAllGlobals(); });

const css = stylesheet.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].split(",").map((x: string) => x.trim()).includes(selector)).map((m) => m[2]);
const declared = (selector: string, property: string) => rules(selector).some((body) => new RegExp(`(^|[;\\s])${property}\\s*:`).test(body));
const value = (selector: string, property: string) => { const hits = rules(selector).map((b) => new RegExp(`(?:^|[;\\s])${property}\\s*:\\s*([^;]+)`).exec(b)?.[1]?.trim()).filter(Boolean); return hits[hits.length - 1]; };

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

const handleOf = (name: string) => screen.getByRole("img", { name: `${name} を並べ替え（ドラッグ）` });
const rowOf = (name: string) => [...document.querySelectorAll(".monitors-table tbody tr")].find((r) => r.querySelector("strong")!.textContent === name) as HTMLElement;
/** 三本線のハンドルをドラッグして、別の行へドロップする(HTML5 DnDのイベント列)。 */
function dragHandleTo(fromName: string, toName: string) {
  const handle = handleOf(fromName);
  fireEvent.dragStart(handle, { dataTransfer: { setData: vi.fn(), setDragImage: vi.fn(), effectAllowed: "" } });
  const target = rowOf(toName);
  const over = createEvent.dragOver(target, { dataTransfer: {} });
  fireEvent(target, over);
  fireEvent.drop(target, { dataTransfer: {} });
  fireEvent.dragEnd(handle);
  return { over, target };
}

describe("モニター管理: 並べ替え(三本線ハンドルのドラッグ&ドロップ)", () => {
  it("↑↓ボタンは存在しない", async () => {
    orderedServer();
    renderApp("/monitors");
    await waitRows();
    expect(screen.queryByRole("button", { name: /上へ|下へ/ })).not.toBeInTheDocument();
    expect(screen.queryByText("↑")).not.toBeInTheDocument();
    expect(screen.queryByText("↓")).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "順序" })).not.toBeInTheDocument();
  });

  it("三本線(☰)のハンドルが各Monitor行の右端にあり、ハンドルだけがdrag可能(行全体はdragしない)", async () => {
    orderedServer();
    renderApp("/monitors");
    await waitRows();
    const rows = [...document.querySelectorAll(".monitors-table tbody tr")] as HTMLElement[];
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      const cells = [...row.children];
      const last = cells[cells.length - 1] as HTMLElement;
      expect(last).toHaveClass("order-col"); // 右端の列
      const handle = last.querySelector(".drag-handle") as HTMLElement;
      expect(handle).not.toBeNull();
      expect(handle).toHaveTextContent("☰");
      expect(handle).toHaveAttribute("draggable", "true");
      expect(row).not.toHaveAttribute("draggable"); // 行全体はdragさせない
      expect(row.querySelectorAll(".drag-handle")).toHaveLength(1); // ハンドルは行に1つだけ
      expect(within(row).getByRole("button", { name: /の詳細/ })).toBeInTheDocument(); // 「詳細へ」はハンドルの左
    }
    // ヘッダーも右端が並べ替え列
    const headers = [...document.querySelectorAll(".monitors-table thead th")];
    expect(headers[headers.length - 1]).toHaveClass("order-col");
  });

  it("ハンドルのcursor(grab / grabbing)・hover・drag中の見た目がCSSで定義されている", async () => {
    expect(value(".drag-handle", "cursor")).toBe("grab");
    expect(declared(".drag-handle:active", "cursor")).toBe(true);
    expect(value(".drag-handle:active", "cursor")).toBe("grabbing");
    expect(declared(".drag-handle:hover", "color")).toBe(true);
    expect(declared(".drag-handle.dragging", "background")).toBe(true);
    expect(declared(".monitors-table .order-col", "width")).toBe(true); // 右端位置が行ごとに揃う固定幅の列
  });

  it("ハンドルからdragを開始でき、drag中はhandleと行に視覚フィードバックが出る", async () => {
    orderedServer();
    renderApp("/monitors");
    await waitRows();
    const handle = handleOf("Digital A");
    fireEvent.dragStart(handle, { dataTransfer: { setData: vi.fn(), setDragImage: vi.fn(), effectAllowed: "" } });
    expect(handle).toHaveClass("dragging");
    const over = createEvent.dragOver(rowOf("Drum"), { dataTransfer: {} });
    fireEvent(rowOf("Drum"), over);
    expect(over.defaultPrevented).toBe(true); // ドロップ可能
    expect(rowOf("Drum")).toHaveClass("row-drop-target");
    fireEvent.dragEnd(handle);
    expect(handle).not.toHaveClass("dragging");
    expect(rowOf("Drum")).not.toHaveClass("row-drop-target");
  });

  it("行(ハンドル以外)からはdragを開始できず、並べ替えにならない", async () => {
    const server = orderedServer();
    renderApp("/monitors");
    await waitRows();
    fireEvent.dragStart(rowOf("Digital A"), { dataTransfer: { setData: vi.fn(), effectAllowed: "" } });
    fireEvent.dragOver(rowOf("Drum"), { dataTransfer: {} });
    fireEvent.drop(rowOf("Drum"), { dataTransfer: {} });
    await new Promise((r) => setTimeout(r, 50));
    expect(putCalls(server.calls)).toHaveLength(0);
    expect(rowNames()).toEqual(["Digital A", "Digital B", "Drum"]);
  });

  it("drag&dropで順番が変わり、drop完了時に自動保存される(保存ボタンなし・保存中... → 保存済み)", async () => {
    const server = orderedServer();
    renderApp("/monitors");
    await waitRows();
    dragHandleTo("Digital A", "Drum"); // 先頭を末尾へ
    expect(rowNames()).toEqual(["Digital B", "Drum", "Digital A"]); // 即時(楽観的)に反映
    await waitFor(() => expect(putCalls(server.calls)).toHaveLength(1));
    expect(putCalls(server.calls)[0].body).toEqual({ monitor_ids: [3, 4, 2] });
    expect(await screen.findByText("保存済み")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "保存" })).not.toBeInTheDocument();
    dragHandleTo("Drum", "Digital B"); // 2番目を先頭へ
    await waitFor(() => expect(putCalls(server.calls)).toHaveLength(2));
    expect(putCalls(server.calls)[1].body).toEqual({ monitor_ids: [4, 3, 2] });
    expect(rowNames()).toEqual(["Drum", "Digital B", "Digital A"]);
  });

  it("保存中は「保存中...」を表示し、その間はdragできない", async () => {
    let release: (r: Response) => void = () => undefined;
    const server = orderedServer();
    server.on(route("PUT", "/api/monitors/order", () => new Promise<Response>((resolve) => { release = resolve; }) as unknown as Response));
    renderApp("/monitors");
    await waitRows();
    dragHandleTo("Digital A", "Digital B");
    expect(await screen.findByText("保存中...")).toBeInTheDocument();
    expect(rowNames()).toEqual(["Digital B", "Digital A", "Drum"]);
    expect(handleOf("Drum")).toHaveAttribute("draggable", "false"); // 保存中は操作不可
    release(json({ monitor_ids: [3, 2, 4] }));
    expect(await screen.findByText("保存済み")).toBeInTheDocument();
    expect(handleOf("Drum")).toHaveAttribute("draggable", "true");
  });

  it("同じ位置へのドロップでは保存しない", async () => {
    const server = orderedServer();
    renderApp("/monitors");
    await waitRows();
    dragHandleTo("Digital A", "Digital A");
    await new Promise((r) => setTimeout(r, 50));
    expect(putCalls(server.calls)).toHaveLength(0);
  });

  it("保存に失敗したら元の順へrollbackし、エラーを表示する", async () => {
    const server = orderedServer([2, 3, 4], () => json({ detail: { code: "UNKNOWN_MONITOR", message: "存在しないモニターIDが含まれています" } }, 422));
    renderApp("/monitors");
    await waitRows();
    dragHandleTo("Drum", "Digital A");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("表示順を保存できませんでした");
    expect(alert).toHaveTextContent("元の順に戻しました");
    expect(rowNames()).toEqual(["Digital A", "Digital B", "Drum"]); // 元の順
    expect(screen.queryByText("保存済み")).not.toBeInTheDocument();
    expect(putCalls(server.calls)).toHaveLength(1);
  });

  it("一覧が更新されていた場合(409)は再読み込みして最新の順に同期する", async () => {
    const server = orderedServer([2, 3, 4], () => json({ detail: { code: "ORDER_STALE", message: "全モニターを指定してください" } }, 409));
    renderApp("/monitors");
    await waitRows();
    server.state.order = [3, 2, 4]; // 別の画面で順序が変わった
    dragHandleTo("Drum", "Digital A");
    expect(await screen.findByRole("alert")).toHaveTextContent("再読み込みしました");
    await waitFor(() => expect(rowNames()).toEqual(["Digital B", "Digital A", "Drum"]));
  });

  it("保存後、Dashboardへ移動・再読込しても新しい順番で表示される", async () => {
    orderedServer();
    const user = userEvent.setup();
    renderApp("/monitors");
    await waitRows();
    dragHandleTo("Drum", "Digital A");
    await screen.findByText("保存済み");
    expect(rowNames()).toEqual(["Drum", "Digital A", "Digital B"]);
    await user.click(screen.getByRole("link", { name: "ダッシュボード" }));
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    expect(cardNames()).toEqual(["Drum", "Digital A", "Digital B"]);
    await user.click(screen.getByRole("link", { name: "モニター管理" })); // 画面を開き直しても維持
    await waitRows();
    expect(rowNames()).toEqual(["Drum", "Digital A", "Digital B"]);
  });

  it("ハンドルのdragと「詳細へ」のクリックは競合しない", async () => {
    const server = orderedServer();
    const user = userEvent.setup();
    renderApp("/monitors");
    await waitRows();
    await user.click(screen.getByRole("button", { name: "Drum の詳細" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/monitors/4");
    expect(putCalls(server.calls)).toHaveLength(0); // クリックでは並べ替え・保存しない
  });
});
