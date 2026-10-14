/// <reference types="vite/client" />
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { get, json, monitor, record, renderApp, route, standardMocks } from "./helpers";
import type { Call } from "./helpers";
import type { Inference } from "../types";

const inference: Inference = {
  method: "object_detection", engine: "cpp_onnx", model_id: "digital_production_v1.onnx", device: "cpu", video_fps: 5, inference_fps: 1, confidence: 0.25, iou: 0.45, image_size: 640,
  preprocessing: { gray: true, clahe: true, blur: 3 }, roi: { x: 0, y: 0, width: 0.5, height: 0.25 }, roi_mode: "filter_only", context_margin: 0.1, engine_options: {},
  reading: { enabled: true, mode: "majority", window_size: 5, required_matches: 3, min_confidence: null, expected_digits: 7, decimal_position: null, monotonic: true, max_rate_per_minute: null, max_consecutive_failures: 5, allow_rollover: false, rollover_max: null },
};

beforeEach(() => { localStorage.clear(); });
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

// 認証のモック: roleはテストごとに切り替える。login(password="pw"のみ成功)/logoutでroleが変わる。
function authMocks(initial: "VIEWER" | "ADMIN", opts: { available?: boolean; extra?: ReturnType<typeof route>[]; records?: unknown[] } = {}) {
  const state = { role: initial };
  const available = opts.available ?? true;
  const body = () => ({ role: state.role, admin_login_available: available });
  const rows = (opts.records ?? [record({ id: 1, monitor_id: 2, monitor_name: "メーター2", correctable: true, correctable_reason: "carried_forward", value_source: "carried_forward", memo: "既存メモ" })]) as ReturnType<typeof record>[];
  const mocks = standardMocks([
    get("/api/monitors", { monitors: [monitor({ id: 2, display_name: "メーター2" }), monitor({ id: 3, display_name: "メーター3" })] }),
    get("/api/records", () => ({ items: rows, total: rows.length, limit: 500, offset: 0 })),
    get("/api/auth/session", body),
    route("POST", "/api/auth/login", (c: Call) => {
      if ((c.body as { password: string }).password === "pw") { state.role = "ADMIN"; return json(body()); }
      return json({ detail: { code: "INVALID_PASSWORD", message: "パスワードが違います" } }, 401);
    }),
    route("POST", "/api/auth/logout", () => { state.role = "VIEWER"; return json(body()); }),
    ...(opts.extra ?? []),
  ]);
  return { ...mocks, state };
}
const navLinks = () => within(screen.getByRole("navigation", { name: "メインナビゲーション" })).getAllByRole("link").map((a) => a.textContent);

describe("閲覧モード(VIEWER)の表示", () => {
  it("「閲覧モード」を表示し、管理系のナビ・モニター追加・メモ編集・読取値修正を出さない", async () => {
    const user = userEvent.setup();
    authMocks("VIEWER");
    renderApp("/");
    expect(await screen.findByText("閲覧モード")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "管理者ログイン" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ログアウト" })).toBeNull();
    expect(navLinks()).toEqual(["ダッシュボード", "履歴・データ"]); // モニター管理・システム設定は出さない
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(2));
    expect(screen.queryByRole("button", { name: /モニター追加/ })).toBeNull();
    // 計測履歴: メモは閲覧のみ(編集ボタンなし)・修正ボタンなし。閲覧(詳細・Export (XL))はできる
    await waitFor(() => expect(document.querySelectorAll(".records-table tbody tr")).toHaveLength(1));
    expect(document.querySelector(".memo-button")).toBeNull();
    expect(document.querySelector(".cell-memo")).toHaveTextContent("既存メモ");
    expect(screen.getByRole("button", { name: "Export (XL)" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /の詳細$/ }));
    expect(await screen.findByText("読取値を修正", { selector: "h2, h3, strong" }).catch(() => null)).toBeNull();
    expect(screen.queryByRole("button", { name: "読取値を修正" })).toBeNull();
  });

  it("Dashboard設定: 表示FPS・画面自動リロードは使え、管理系(CSV出力)は出ない", async () => {
    const user = userEvent.setup();
    const mocks = authMocks("VIEWER");
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Dashboard設定" }));
    const dialog = screen.getByRole("dialog", { name: "Dashboard設定" });
    expect(within(dialog).getByRole("combobox", { name: /Dashboard表示FPS/ })).toBeInTheDocument();
    expect(within(dialog).getByRole("combobox", { name: /画面自動リロード/ })).toBeInTheDocument();
    expect(within(dialog).queryByText(/CSV/)).toBeNull();
    expect(mocks.calls.some((c) => c.url.startsWith("/api/system/csv-export"))).toBe(false); // 管理系のAPIを呼ばない
  });

  it("管理画面(/monitors /monitors/new /settings)へは入れず、ログインの案内を出す", async () => {
    for (const path of ["/monitors", "/monitors/new", "/settings"]) {
      authMocks("VIEWER");
      const { unmount } = renderApp(path);
      expect(await screen.findByText("管理者ログインが必要です")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "ダッシュボードへ" })).toBeInTheDocument();
      unmount();
    }
  });

  it("Monitor Detail: 「設定」「診断」タブを出さず、診断APIも呼ばない(監視・履歴は閲覧できる)", async () => {
    const mocks = authMocks("VIEWER", { extra: [get("/api/monitors/2", monitor({ id: 2, display_name: "メーター2", inference, source: { source_type: "url", device_id: null, url: null, username: null, has_password: false } })), get("/api/monitors/2/runtime", { state: "running" }), get("/api/monitors/2/reading/baseline", { enabled: false })] });
    renderApp("/monitors/2");
    await screen.findByRole("tab", { name: "監視" });
    expect([...document.querySelectorAll(".detail-tabs [role=tab]")].map((t) => t.textContent)).toEqual(["監視", "履歴"]);
    expect(screen.queryByRole("button", { name: "ROIを編集" })).toBeNull();
    expect(screen.getByRole("button", { name: /ダッシュボードへ/ })).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(mocks.calls.some((c) => c.url.includes("/reading/diagnostics"))).toBe(false);
  });

  it("管理者ログインが設定されていないBackendでは「管理者ログイン」を出さない(閲覧モードのみ)", async () => {
    authMocks("VIEWER", { available: false });
    renderApp("/");
    expect(await screen.findByText("閲覧モード")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "管理者ログイン" })).toBeNull();
  });

  it("session取得に失敗したときは安全側(VIEWER)で表示し、Dashboardは壊れない", async () => {
    standardMocks([get("/api/auth/session", { detail: "x" }, 500)]);
    renderApp("/");
    expect(await screen.findByText("閲覧モード")).toBeInTheDocument();
    await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3));
    expect(screen.queryByRole("button", { name: /モニター追加/ })).toBeNull();
  });
});

describe("管理者ログイン / ログアウト", () => {
  it("VIEWERとして閲覧でき、ログインダイアログは「管理者ログイン」を押したときだけ出る", async () => {
    const user = userEvent.setup();
    authMocks("VIEWER");
    renderApp("/");
    await screen.findByText("閲覧モード");
    expect(screen.queryByRole("dialog", { name: "管理者ログイン" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "管理者ログイン" }));
    expect(screen.getByRole("dialog", { name: "管理者ログイン" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "管理者ログイン" })).toBeNull();
  });

  it("パスワードが違うと簡潔なエラーを表示してVIEWERのまま。正しければADMINの管理UIが即時に出る", async () => {
    const user = userEvent.setup();
    const mocks = authMocks("VIEWER");
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "管理者ログイン" }));
    const dialog = screen.getByRole("dialog", { name: "管理者ログイン" });
    await user.type(within(dialog).getByLabelText("パスワード"), "wrong{Enter}");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("パスワードが違います");
    expect(screen.getByText("閲覧モード")).toBeInTheDocument();
    expect(navLinks()).not.toContain("システム設定");
    await user.type(within(dialog).getByLabelText("パスワード"), "pw{Enter}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "管理者ログイン" })).toBeNull());
    expect(screen.getByText("管理者")).toBeInTheDocument();
    expect(screen.queryByText("閲覧モード")).toBeNull();
    expect(navLinks()).toEqual(["ダッシュボード", "モニター管理", "履歴・データ", "システム設定"]);
    expect(screen.getByRole("button", { name: /モニター追加/ })).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector(".memo-button")).not.toBeNull()); // メモ編集が使える
    expect(mocks.calls.filter((c) => c.url === "/api/auth/login").map((c) => c.body)).toEqual([{ password: "wrong" }, { password: "pw" }]);
  });

  it("ADMINでは現在のUIのまま(全ナビ・モニター追加・メモ編集)。ログアウトで即VIEWERへ戻る", async () => {
    const user = userEvent.setup();
    authMocks("ADMIN");
    renderApp("/");
    expect(await screen.findByText("管理者")).toBeInTheDocument();
    expect(navLinks()).toContain("システム設定");
    await waitFor(() => expect(document.querySelector(".memo-button")).not.toBeNull());
    await user.click(screen.getByRole("button", { name: "ログアウト" }));
    expect(await screen.findByText("閲覧モード")).toBeInTheDocument();
    expect(navLinks()).not.toContain("システム設定");
    expect(screen.queryByRole("button", { name: /モニター追加/ })).toBeNull();
    expect(document.querySelector(".memo-button")).toBeNull();
  });

  it("ログアウト後に管理画面を開くと、ログインの案内になる", async () => {
    const user = userEvent.setup();
    authMocks("ADMIN");
    renderApp("/settings");
    await user.click(await screen.findByRole("button", { name: "ログアウト" }));
    expect(await screen.findByText("管理者ログインが必要です")).toBeInTheDocument();
  });
});

describe("ADMIN sessionが切れたとき", () => {
  it("書き込みが403(ADMIN_REQUIRED)になると、画面は壊さずVIEWERへ戻り、編集中のメモは消えない", async () => {
    const user = userEvent.setup();
    const mocks = authMocks("ADMIN", { extra: [route("PATCH", "/api/records/1/memo", () => { mocks.state.role = "VIEWER"; return json({ detail: { code: "ADMIN_REQUIRED", message: "この操作には管理者ログインが必要です" } }, 403); })] });
    renderApp("/");
    await waitFor(() => expect(document.querySelector(".memo-button")).not.toBeNull());
    await user.click(document.querySelector(".memo-button") as HTMLElement);
    const input = screen.getByRole("textbox", { name: /のメモ$/ });
    await user.clear(input);
    await user.type(input, "未保存の入力{Enter}");
    // VIEWERへ戻り、管理操作が消える
    expect(await screen.findByText("閲覧モード")).toBeInTheDocument();
    expect(navLinks()).not.toContain("システム設定");
    expect(screen.queryByRole("button", { name: /モニター追加/ })).toBeNull();
    // 未保存の入力は残り、再ログインが必要なことが分かる。Dashboardは動いたまま
    expect((screen.getByRole("textbox", { name: /のメモ$/ }) as HTMLInputElement).value).toBe("未保存の入力");
    expect(screen.getByText(/管理者ログインが切れました/)).toBeInTheDocument();
    expect(document.querySelectorAll(".monitor-card")).toHaveLength(2);
    // 再ログインすると、同じ入力のまま保存できる状態に戻る
    await user.click(screen.getByRole("button", { name: "管理者ログイン" }));
    await user.type(screen.getByLabelText("パスワード"), "pw{Enter}");
    await waitFor(() => expect(screen.queryByText(/管理者ログインが切れました/)).toBeNull());
    expect((screen.getByRole("textbox", { name: /のメモ$/ }) as HTMLInputElement).value).toBe("未保存の入力");
  });
});
