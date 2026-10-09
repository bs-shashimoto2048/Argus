/// <reference types="vite/client" />
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import stylesheet from "../styles.css?raw";
import { get, monitor, record, renderApp, standardMocks } from "./helpers";
import type { Call } from "./helpers";
import type { Monitor } from "../types";

beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-10-09T05:30:00Z")); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const css = stylesheet.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].split(",").map((x: string) => x.trim()).includes(selector)).map((m) => m[2]);
const propertyValue = (body: string, property: string) => new RegExp(String.raw`(?:^|[;\s])${property}\s*:\s*([^;]+)`).exec(body)?.[1]?.trim();
const value = (selector: string, property: string) => { const hits = rules(selector).map((b) => propertyValue(b, property)).filter(Boolean); return hits[hits.length - 1]; };
const declared = (selector: string, property: string) => rules(selector).some((b) => propertyValue(b, property) !== undefined);

// DashboardがMonitorカードの補助表示用に取得する「最新の記録」(limit=100)は、履歴表の取得ではないので除く
const calls = (all: Call[]) => all.filter((c) => c.url.startsWith("/api/records?")).map((c) => new URL(c.url, "http://x").searchParams).filter((p) => p.get("limit") !== "100");

/** 総件数totalの記録を、offset/limitに応じて返す(新しい順にidが小さくなる)。 */
function pagedRecords(total: number, delayMs = 0) {
  return get("/api/records", (c: Call) => {
    const p = new URL(c.url, "http://x").searchParams;
    const offset = Number(p.get("offset")), limit = Number(p.get("limit"));
    const items = Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, i) => record({ id: total - (offset + i), recorded_at: "2026-10-08T23:00:20" }));
    return { items, total, limit, offset };
  });
}
const scrollTo = (wrap: HTMLElement, top: number, height = 10000, client = 400) => {
  Object.defineProperty(wrap, "scrollHeight", { configurable: true, value: height });
  Object.defineProperty(wrap, "clientHeight", { configurable: true, value: client });
  Object.defineProperty(wrap, "scrollTop", { configurable: true, writable: true, value: top });
  fireEvent.scroll(wrap);
};
const rowCount = () => document.querySelectorAll(".records-table tbody tr[data-record-id]").length;

describe("Dashboard上部: 状態サマリーは横1行のcompact chip", () => {
  it("正常 / 要確認 / 通信異常が、項目名と値を横に並べた3つのchipとして1行に並ぶ(縦長のカードではない)", async () => {
    standardMocks([get("/api/monitors", { monitors: [monitor({ id: 2 }), monitor({ id: 3, inference_status: "low_confidence" }), monitor({ id: 4, inference_status: "read_error" }), monitor({ id: 5 })] as Monitor[] })]);
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(4));
    const chips = [...document.querySelectorAll(".summary-chips > .summary-chip")] as HTMLElement[];
    expect(chips.map((c) => c.querySelector(".chip-label")!.textContent)).toEqual(["正常", "要確認", "通信異常"]);
    expect(chips.map((c) => c.querySelector("strong")!.textContent)).toEqual(["2", "1", "1"]);
    expect(chips.map((c) => c.className.match(/tone-\w+/)![0])).toEqual(["tone-ok", "tone-caution", "tone-danger"]); // 緑 / 黄 / 赤
    expect(screen.getByTestId("count-normal")).toHaveTextContent("2");
    expect(document.querySelector(".summary-card")).toBeNull(); // 旧カード形式は使わない
    expect(document.querySelector(".summary-cards")).toBeNull();
    for (const chip of chips) expect(chip.children).toHaveLength(2); // [項目名][値]の横並び
  });

  it("CSS: chipは同じ高さ(34px)・横並び(inline-flex)で、縦長にならない", () => {
    expect(value(".summary-chip", "height")).toBe("34px");
    expect(value(".summary-chip", "display")).toBe("inline-flex");
    expect(value(".summary-chip", "white-space")).toBe("nowrap");
    expect(value(".summary-chips", "display")).toBe("flex");
    expect(value(".summary-chip strong", "font-variant-numeric")).toBe("tabular-nums");
    expect(declared(".summary-chip.tone-ok", "border-left-color") && declared(".summary-chip.tone-caution", "border-left-color") && declared(".summary-chip.tone-danger", "border-left-color")).toBe(true);
    expect(declared(".summary-chip", "padding")).toBe(true);
    expect(parseInt(value(".summary-chip", "height")!)).toBeLessThan(40); // 旧カード(約70px)より明確に低い
  });

  it("左=状態サマリー、右=[モニター追加]とMonitoringの1行構成(同じtoolbar内)", async () => {
    standardMocks();
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    const toolbar = document.querySelector(".dashboard-toolbar") as HTMLElement;
    expect([...toolbar.children].map((e) => e.className)).toEqual(["summary-chips", "action-group"]);
    const group = screen.getByRole("group", { name: "ダッシュボード操作" });
    expect(group.children[0]).toHaveTextContent("＋ モニター追加");
    expect(group.children[1]).toHaveClass("monitoring-control"); // 従来どおり[モニター追加]の右隣
    expect(value(".dashboard-toolbar", "justify-content")).toBe("space-between");
  });
});

describe("計測履歴のヘッダー: 説明とフィルタが同じ行", () => {
  it("左=タイトルと説明、右=Monitor・期間のフィルタ。フィルタ専用の2行目を作らない", async () => {
    standardMocks();
    renderApp("/");
    const head = (await screen.findByRole("heading", { name: "計測履歴" })).closest(".records-head") as HTMLElement;
    expect([...head.children].map((e) => e.className)).toEqual(["records-title", "records-controls"]);
    const title = head.querySelector(".records-title") as HTMLElement;
    const controls = head.querySelector(".records-controls") as HTMLElement;
    expect(title).toHaveTextContent("1時間ごとに自動記録（毎時00分）。詳細な検索・Excel出力は「履歴・データ」から行えます。");
    expect(within(controls).getByRole("combobox", { name: "モニター" })).toBeInTheDocument();
    expect(within(controls).getByRole("group", { name: "表示期間" })).toBeInTheDocument();
    expect(within(controls).getAllByRole("button").map((b) => b.textContent)).toEqual(["今日", "過去7日", "任意期間"]);
    expect(title.contains(controls)).toBe(false);
    // フィルタはヘッダー(records-head)の外にも無い
    expect(document.querySelectorAll(".record-filters")).toHaveLength(1);
    expect(head.contains(document.querySelector(".record-filters"))).toBe(true);
    // 「モニター」「表示期間」の見出しラベルは出さない(コンパクト化)
    expect(document.querySelector(".filter-label")).toBeNull();
  });

  it("CSS: ヘッダーは左右に分離(space-between)・右側は右寄せ。幅が足りない場合だけ折り返す", () => {
    expect(value(".records-head", "display")).toBe("flex");
    expect(value(".records-head", "justify-content")).toBe("space-between");
    expect(value(".records-head", "flex-wrap")).toBe("wrap");
    expect(value(".records-controls", "justify-content")).toBe("flex-end");
    expect(value(".records-controls .record-filters", "display")).toBe("contents"); // フィルタ自体は専用の行を持たない
  });

  it("任意期間のときだけdate rangeを右側の操作グループ内に表示し、今日/過去7日では出さない", async () => {
    standardMocks();
    const user = userEvent.setup();
    renderApp("/");
    const controls = (await screen.findByRole("heading", { name: "計測履歴" })).closest(".records-head")!.querySelector(".records-controls") as HTMLElement;
    expect(within(controls).queryByRole("group", { name: "期間選択" })).not.toBeInTheDocument();
    await user.click(within(controls).getByRole("button", { name: "過去7日" }));
    expect(within(controls).queryByRole("group", { name: "期間選択" })).not.toBeInTheDocument();
    await user.click(within(controls).getByRole("button", { name: "任意期間" }));
    expect(within(controls).getByRole("group", { name: "期間選択" })).toBeInTheDocument(); // 同じ右側グループ内
    await user.click(within(controls).getByRole("button", { name: "今日" }));
    expect(document.querySelector(".date-range-box")).toBeNull(); // 空白を残さない
  });

  it("履歴・データ画面ではExcel出力もフィルタと同じ右側グループに並ぶ", async () => {
    standardMocks([pagedRecords(3)]);
    renderApp("/history");
    const controls = (await screen.findByRole("heading", { name: "1時間ごとの計測履歴" })).closest(".records-head")!.querySelector(".records-controls") as HTMLElement;
    expect(within(controls).getByRole("button", { name: "Excel出力" })).toBeInTheDocument();
    expect(within(controls).getByRole("combobox", { name: "モニター" })).toBeInTheDocument();
  });
});

describe("計測履歴: ページ送りなし・スクロールで全件", () => {
  it("ページ送りのUI(前へ/次へ/ページ番号/ページ選択)が存在しない", async () => {
    standardMocks([pagedRecords(1200)]);
    renderApp("/");
    await waitFor(() => expect(rowCount()).toBe(500));
    expect(screen.queryByRole("button", { name: /前へ|次へ/ })).not.toBeInTheDocument();
    expect(document.querySelector(".pager")).toBeNull();
    expect(screen.queryByText(/\d+〜\d+件/)).not.toBeInTheDocument(); // 「1〜50件」のようなページ範囲の表示もない
    expect(screen.queryByLabelText("ページ送り")).not.toBeInTheDocument();
  });

  it("単一のスクロール領域(固定ヘッダーのtable)に、現在の条件の全件が入る", async () => {
    standardMocks([pagedRecords(40)]);
    renderApp("/");
    await waitFor(() => expect(rowCount()).toBe(40));
    expect(screen.getByText("40件（全件表示）")).toBeInTheDocument();
    const wraps = document.querySelectorAll(".records-area .records-table-wrap");
    expect(wraps).toHaveLength(1);
    expect(wraps[0].querySelectorAll("table")).toHaveLength(1);
    expect(wraps[0].querySelectorAll("thead th")).toHaveLength(9);
    expect(value(".records-table th", "position")).toBe("sticky");
    expect(value(".records-table-wrap", "overflow")).toBe("auto");
  });

  it("初回は先頭chunk(500件)だけ取得し、巨大な一括取得をしない", async () => {
    const mocks = standardMocks([pagedRecords(20000)]);
    renderApp("/history");
    await waitFor(() => expect(rowCount()).toBe(500));
    const first = calls(mocks.calls);
    expect(first).toHaveLength(1);
    expect(first[0].get("limit")).toBe("500");
    expect(first[0].get("offset")).toBe("0");
    expect(screen.getByText("20,000件中 500件を表示（下へスクロールで続きを読み込みます）")).toBeInTheDocument();
  });

  it("スクロール末尾に近づいたら続きを追加取得し(offset=500, 1000...)、最後まで読むと全件表示になる", async () => {
    const mocks = standardMocks([pagedRecords(1200)]);
    renderApp("/");
    await waitFor(() => expect(rowCount()).toBe(500));
    const wrap = screen.getByTestId("records-scroll");
    scrollTo(wrap, 0); // 先頭付近: 追加取得しない
    await new Promise((r) => setTimeout(r, 30));
    expect(calls(mocks.calls)).toHaveLength(1);
    scrollTo(wrap, 9500); // 末尾付近
    await waitFor(() => expect(rowCount()).toBe(1000));
    expect(calls(mocks.calls).map((p) => p.get("offset"))).toEqual(["0", "500"]);
    expect(screen.getByText("1,200件中 1,000件を表示（下へスクロールで続きを読み込みます）")).toBeInTheDocument();
    scrollTo(screen.getByTestId("records-scroll"), 9500);
    await waitFor(() => expect(rowCount()).toBe(1200));
    expect(calls(mocks.calls).map((p) => p.get("offset"))).toEqual(["0", "500", "1000"]);
    expect(screen.getByText("1,200件（全件表示）")).toBeInTheDocument();
    // 全件読み込み済み: これ以上は取得しない
    scrollTo(screen.getByTestId("records-scroll"), 99999);
    await new Promise((r) => setTimeout(r, 30));
    expect(calls(mocks.calls)).toHaveLength(3);
    // 行の重複がない(古い順に連続したid)
    const ids = [...document.querySelectorAll(".records-table tbody tr[data-record-id]")].map((r) => Number((r as HTMLElement).dataset.recordId));
    expect(new Set(ids).size).toBe(1200);
  });

  it("追加取得中に何度スクロールしても、同じ続きを二重に取得しない", async () => {
    let release: () => void = () => undefined;
    const mocks = standardMocks([pagedRecords(1200)]);
    renderApp("/");
    await waitFor(() => expect(rowCount()).toBe(500));
    const real = (globalThis.fetch as unknown as (...a: unknown[]) => Promise<Response>);
    const gate = new Promise<void>((resolve) => { release = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (...args: unknown[]) => { await gate; return real(...args); }));
    const wrap = screen.getByTestId("records-scroll");
    scrollTo(wrap, 9500); scrollTo(wrap, 9600); scrollTo(wrap, 9700);
    expect(await screen.findByText("続きを読み込み中…")).toBeInTheDocument();
    release();
    await waitFor(() => expect(rowCount()).toBe(1000));
    expect(mocks.calls.length).toBeGreaterThan(0);
  });

  it("Monitorを変えると即時に先頭から取り直し、続きの読み込み状態もリセットされる", async () => {
    const mocks = standardMocks([pagedRecords(1200)]);
    const user = userEvent.setup();
    renderApp("/");
    await waitFor(() => expect(rowCount()).toBe(500));
    scrollTo(screen.getByTestId("records-scroll"), 9500);
    await waitFor(() => expect(rowCount()).toBe(1000));
    const select = screen.getByRole("combobox", { name: "モニター" });
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(4));
    await user.selectOptions(select, "3");
    await waitFor(() => expect(calls(mocks.calls).pop()!.getAll("monitor_id")).toEqual(["3"]));
    expect(calls(mocks.calls).pop()!.get("offset")).toBe("0");
    await waitFor(() => expect(rowCount()).toBe(500)); // 先頭chunkに戻る
  });

  it("今日 / 過去7日 / 任意期間の切替は即時に反映される(適用ボタンなし)", async () => {
    const mocks = standardMocks([pagedRecords(10)]);
    const user = userEvent.setup();
    renderApp("/");
    await waitFor(() => expect(rowCount()).toBe(10));
    await user.click(screen.getByRole("button", { name: "過去7日" }));
    await waitFor(() => expect(calls(mocks.calls).pop()!.get("from")).toBe("2026-10-03T00:00:00+09:00"));
    await user.click(screen.getByRole("button", { name: "任意期間" }));
    fireEvent.change(screen.getByLabelText("開始日"), { target: { value: "2026-08-20" } });
    fireEvent.change(screen.getByLabelText("終了日"), { target: { value: "2026-08-26" } });
    await waitFor(() => expect(calls(mocks.calls).pop()!.get("to")).toBe("2026-08-27T00:00:00+09:00"));
    expect(screen.queryByRole("button", { name: "適用" })).not.toBeInTheDocument();
  });

  it("追加取得に失敗した場合はエラーを表示し、読み込み済みの行は保持する", async () => {
    const mocks = standardMocks([pagedRecords(1200)]);
    renderApp("/");
    await waitFor(() => expect(rowCount()).toBe(500));
    mocks.on({ test: (url, m) => m === "GET" && url.startsWith("/api/records?") && url.includes("offset=500"), respond: () => new Response(JSON.stringify({ detail: "boom" }), { status: 500, headers: { "Content-Type": "application/json" } }) });
    scrollTo(screen.getByTestId("records-scroll"), 9500);
    expect(await screen.findByText(/続きを取得できません（boom）/)).toBeInTheDocument();
    expect(rowCount()).toBe(500);
  });
});

describe("画面揺れ防止(compact化後も維持)", () => {
  it("履歴領域は固定の高さ(viewport基準)で、件数表示の行も高さを確保している", () => {
    expect(value(".records-area.compact", "height")).toBe("clamp(340px, 54vh, 660px)"); // Dashboard以外(単体)の既定。Dashboardでは残り高さに置き換わる(下記)
    expect(value(".records-area.tall", "height")).toMatch(/^clamp\(.*100vh/);
    expect(value(".records-count", "min-height")).toBe("20px"); // 件数テキストの有無で高さが変わらない
    expect(value(".records-table-wrap", "scrollbar-gutter")).toBe("stable");
    expect(value("html", "scrollbar-gutter")).toBe("stable");
    expect(value(".records-table td", "font-variant-numeric")).toBe("tabular-nums");
    expect(value(".summary-chip strong", "font-variant-numeric")).toBe("tabular-nums");
  });

  it("読込中・0件・多数件でも履歴の描画領域(records-area)は1つで、件数行は常にある", async () => {
    standardMocks([pagedRecords(0)]);
    renderApp("/");
    const area = document.querySelector(".records-area") as HTMLElement;
    expect(area).toHaveTextContent("読み込み中…");
    expect(await within(area).findByText("この条件に該当する計測記録はありません。")).toBeInTheDocument();
    expect(document.querySelectorAll(".records-area")).toHaveLength(1);
    expect(document.querySelector(".records-count")).not.toBeNull();
  });
});

describe("Dashboard全体をviewport内に収め、計測履歴の表が残り高さで内部スクロールする", () => {
  it("Dashboardのルートは viewport(100dvh) - 上部ナビ の高さの縦flex。overflow:hiddenで切らない", () => {
    expect(value(".dashboard-page", "display")).toBe("flex");
    expect(value(".dashboard-page", "flex-direction")).toBe("column");
    expect(rules(".dashboard-page").some((b) => /height:\s*calc\(100dvh - var\(--nav-h\)\)/.test(b))).toBe(true); // dvh基準(100vhはフォールバックとして先に宣言)
    expect(rules(".dashboard-page").some((b) => /height:\s*calc\(100vh - var\(--nav-h\)\)/.test(b))).toBe(true);
    expect(value(":root", "--nav-h")).toBe("52px");
    expect(value(".app-nav", "min-height")).toBe("var(--nav-h)");
    for (const selector of [".dashboard-page", ".dashboard-page .monitor-grid", ".dashboard-page .records-section"]) {
      expect(["hidden", "clip"]).not.toContain(value(selector, "overflow")); // 単純なoverflow:hiddenで内容を切らない
    }
    expect(value(".dashboard-page", "min-height")).toBe("0");
  });

  it("上部(toolbar)とMonitorカードは固定サイズ(flex: 0 0 auto)、計測履歴のsectionが残り領域(flex: 1 1 auto; min-height: 0)を使う", () => {
    expect(value(".dashboard-page > *", "flex")).toBe("0 0 auto");
    expect(value(".dashboard-page .records-section", "flex")).toBe("1 1 auto");
    expect(value(".dashboard-page .records-section", "min-height")).toBe("0");
    expect(value(".dashboard-page .records-section", "display")).toBe("flex");
    expect(value(".dashboard-page .records-section", "flex-direction")).toBe("column");
    expect(value(".dashboard-page .records-head", "flex")).toBe("0 0 auto"); // ヘッダー(1行)は高さを増やさない
  });

  it("履歴の表の領域は残り高さで伸縮し(flex: 1 1 0 / height:auto / min-height)、表の容器だけがoverflow-y:autoでスクロールする", () => {
    expect(value(".dashboard-page .records-area.compact", "flex")).toBe("1 1 0");
    expect(value(".dashboard-page .records-area.compact", "height")).toBe("auto"); // 固定のviewport比(54vh)ではなく残り高さ
    expect(declared(".dashboard-page .records-area.compact", "min-height")).toBe(true);
    expect(value(".dashboard-page .records-area .records-table-wrap", "overflow-y")).toBe("auto");
    expect(value(".dashboard-page .records-area .records-table-wrap", "min-height")).toBe("0");
    expect(value(".dashboard-page .records-area .records-table-wrap", "height")).toBe("100%");
    expect(value(".records-area", "min-height")).toBe("0");
    expect(value(".records-table th", "position")).toBe("sticky"); // ヘッダー固定は維持
  });

  it("Monitorカードは情報(画像・現在値・信頼度・更新・状態・通知)を残したまま高さを詰め、通知欄の高さは常に確保する", async () => {
    standardMocks();
    renderApp("/");
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    for (const card of document.querySelectorAll(".monitor-card")) {
      expect(card.querySelector(".preview-wrap, .no-video")).not.toBeNull(); // 画像(または未設定表示)
      expect(card.querySelector(".card-value-primary")).not.toBeNull(); // 現在値
      expect(card.querySelector(".card-value-confidence")).not.toBeNull(); // 信頼度
      expect(card.querySelector(".card-value-updated")).not.toBeNull(); // 更新時刻
      expect(card.querySelector(".card-meta")).toHaveTextContent("取得状態"); // 取得状態
      expect(card.querySelector(".status-badge")).not.toBeNull(); // 状態
      expect(card.querySelector(".card-notices")).not.toBeNull(); // 通知欄
    }
    expect(value(".monitor-card .card-notices", "min-height")).toBe("56px");
    expect(value(".monitor-grid", "align-items")).toBe("stretch"); // 3枚の高さを揃える
    expect(value(".monitor-card", "align-self")).toBe("stretch");
    expect(value(".preview-wrap", "height")).toMatch(/^clamp\(104px, 17vh, 220px\)$/);
    expect(value(".video-image", "object-fit")).toBe("contain"); // 画像はaspect-ratioを維持
  });

  it("Dashboardのページ全体で縦overflowを起こすルール(固定高さのmin-heightや履歴領域の固定px高さ)が残っていない", () => {
    expect(value(".dashboard-page .monitor-grid", "min-height")).toBe("0"); // 以前の470px確保を解除
    expect(value(".dashboard-page .records-area", "height") ?? "auto").toBe("auto");
  });

  it("ページ送りなし・段階読み込みは維持(Dashboardの履歴がスクロール領域内に描画され、続きの取得が動く)", async () => {
    const mocks = standardMocks([pagedRecords(1200)]);
    renderApp("/");
    await waitFor(() => expect(rowCount()).toBe(500));
    expect(document.querySelector(".dashboard-page .records-area .records-table-wrap")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /前へ|次へ/ })).not.toBeInTheDocument();
    scrollTo(screen.getByTestId("records-scroll"), 9500);
    await waitFor(() => expect(rowCount()).toBe(1000));
    expect(calls(mocks.calls).map((p) => p.get("offset"))).toEqual(["0", "500"]);
  });
});
