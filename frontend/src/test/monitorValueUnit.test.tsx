/// <reference types="vite/client" />
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import stylesheet from "../styles.css?raw";
import { get, json, monitor, renderApp, route, standardMocks } from "./helpers";
import type { Inference } from "../types";

afterEach(() => { vi.unstubAllGlobals(); });

const css = stylesheet.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].split(",").map((x: string) => x.trim()).includes(selector)).map((m) => m[2]);
const value = (selector: string, property: string) => { const hits = rules(selector).map((b) => new RegExp(String.raw`(?:^|[;\s])${property}\s*:\s*([^;]+)`).exec(b)?.[1]?.trim()).filter(Boolean); return hits[hits.length - 1]; };

const inference: Inference = {
  method: "object_detection", engine: "cpp_onnx", model_id: "digital_production_v1.onnx", device: "cpu", video_fps: 5, inference_fps: 1, confidence: 0.25, iou: 0.45, image_size: 640,
  preprocessing: { gray: true, clahe: true, blur: 3 }, roi: { x: 0, y: 0, width: 0.5, height: 0.25 }, roi_mode: "filter_only", context_margin: 0.1, engine_options: {},
  reading: { enabled: true, mode: "majority", window_size: 5, required_matches: 3, min_confidence: null, expected_digits: 7, decimal_position: null, monotonic: true, max_rate_per_minute: null, max_consecutive_failures: 5, allow_rollover: false, rollover_max: null },
};
const detail = monitor({ id: 3, display_name: "エネセン内ガスメータ用１", name: "gas_1", value_unit: "m³", inference, source: { source_type: "url", device_id: null, url: "http://192.168.25.212/view.shtml", username: "user", has_password: true } });
const detailMocks = (extra = [] as ReturnType<typeof route>[]) => standardMocks([
  get("/api/monitors/3", detail),
  get("/api/monitors/3/reading/diagnostics", { enabled: true, mode: "majority", consecutive_failures: 0, recent_raw: [], confirmed: { value: "1", confidence: 0.9, confirmed_at: null, raw_count: 5, agreement_count: 5, engine: "cpp_onnx", validation_status: "confirmed", raw_value: "1", raw_confidence: 0.9 } }),
  get("/api/monitors/3/runtime", { source_type: "url", state: "running", frame_width: 1920, frame_height: 1080, source_fps: 25, last_frame_timestamp: null, reconnect_count: 0, last_error: null, frame_age: 0.1, stale: false, inference_enabled: true, inference_result: "1", pipeline: null }),
  get("/api/url-history", { items: [] }),
  get("/api/system/inference", { torch: { available: false, version: null, cuda_available: false, cuda_version: null, device_count: 0, devices: [] }, ultralytics: { available: false }, easyocr: { available: false }, tesseract: { python_package: false, executable: false }, devices: [{ value: "cpu", label: "CPU" }] }),
  get("/api/system/models", { models: [] }),
  ...extra,
]);

describe("Monitor設定: 測定単位", () => {
  it("基本情報に「測定単位」入力(最大16文字・補足文つき)があり、内部名・表示名・設置場所・測定単位の順に並ぶ", async () => {
    detailMocks();
    renderApp("/monitors/3?tab=settings");
    await screen.findByRole("heading", { name: "基本情報" });
    const grid = document.querySelector(".basic-grid") as HTMLElement;
    expect([...grid.children].map((e) => e.textContent?.replace(/\s+/g, "").slice(0, 5))).toEqual(expect.arrayContaining([expect.stringContaining("内部名"), expect.stringContaining("表示名"), expect.stringContaining("設置場所"), expect.stringContaining("測定単位")]));
    expect(grid.children).toHaveLength(4);
    const input = within(grid).getByLabelText(/測定単位/) as HTMLInputElement;
    expect(input.value).toBe("m³");
    expect(input.maxLength).toBe(16);
    expect(within(grid).getByText("現在値・履歴などで表示する単位です。")).toBeInTheDocument();
    // 単位欄は短い幅(基本情報の横幅いっぱいに伸ばさない)
    expect(value(".settings-tab .basic-unit input", "width")).toBe("9rem");
  });

  it("保存のPATCHは name / display_name / location / value_unit だけを送る(source・inference・enabledは送らない)。前後の空白はtrimする", async () => {
    const mocks = detailMocks([route("PATCH", "/api/monitors/3", () => json({ ...detail, value_unit: "kWh" }))]);
    renderApp("/monitors/3?tab=settings");
    await screen.findByRole("heading", { name: "基本情報" });
    const input = screen.getByLabelText(/測定単位/) as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, "  kWh ");
    await userEvent.click(screen.getByRole("button", { name: "基本情報を保存" }));
    await waitFor(() => expect(mocks.calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = mocks.calls.find((c) => c.method === "PATCH")!;
    expect(patch.url).toBe("/api/monitors/3");
    expect(Object.keys(patch.body as object).sort()).toEqual(["display_name", "location", "name", "value_unit"]);
    expect((patch.body as { value_unit: string }).value_unit).toBe("kWh");
    expect(await screen.findByText("基本情報を保存しました")).toBeInTheDocument();
  });

  it("空欄にして保存すると value_unit は空文字(単位なし)で送られる", async () => {
    const mocks = detailMocks([route("PATCH", "/api/monitors/3", () => json({ ...detail, value_unit: "" }))]);
    renderApp("/monitors/3?tab=settings");
    await screen.findByRole("heading", { name: "基本情報" });
    await userEvent.clear(screen.getByLabelText(/測定単位/));
    await userEvent.click(screen.getByRole("button", { name: "基本情報を保存" }));
    await waitFor(() => expect(mocks.calls.some((c) => c.method === "PATCH")).toBe(true));
    expect((mocks.calls.find((c) => c.method === "PATCH")!.body as { value_unit: string }).value_unit).toBe("");
  });
});

describe("Dashboard: 現在値の単位", () => {
  const cards = async () => { await waitFor(() => expect(document.querySelectorAll(".monitor-card")).toHaveLength(3)); return [...document.querySelectorAll<HTMLElement>(".monitor-card")]; };

  it("単位ありの現在値は『数値 単位』(別要素)で表示し、未設定なら数値だけ", async () => {
    standardMocks([get("/api/monitors", { monitors: [
      monitor({ id: 2, display_name: "A", current_value: "123456", value_unit: "m³" }),
      monitor({ id: 3, display_name: "B", current_value: "9876", value_unit: "kWh" }),
      monitor({ id: 4, display_name: "C", current_value: "1234", value_unit: "" }),
    ] })]);
    renderApp("/");
    const [a, b, c] = await cards();
    for (const [card, number, unit] of [[a, "123456", "m³"], [b, "9876", "kWh"]] as const) {
      expect(card.querySelector(".current-value-number")!.textContent).toBe(number);
      expect(card.querySelector(".current-value-unit")!.textContent).toBe(unit);
      expect(card.querySelector(".current-value-unit")!.getAttribute("title")).toBe(unit);
      expect(card.querySelector(".card-value-primary strong")!.textContent).toBe(number); // 数値のstrongに単位を混ぜない
    }
    expect(c.querySelector(".current-value-number")!.textContent).toBe("1234");
    expect(c.querySelector(".current-value-unit")).toBeNull();
    expect(c.querySelector(".card-value-primary")!.textContent).toBe("現在値1234");
  });

  it("℃ / MPa / L / 個 なども省略せずそのまま表示する。空白だけの単位は表示しない", async () => {
    standardMocks([get("/api/monitors", { monitors: [
      monitor({ id: 2, display_name: "A", value_unit: "℃" }), monitor({ id: 3, display_name: "B", value_unit: "MPa" }), monitor({ id: 4, display_name: "C", value_unit: "   " }),
    ] })]);
    renderApp("/");
    const [a, b, c] = await cards();
    expect(a.querySelector(".current-value-unit")!.textContent).toBe("℃");
    expect(b.querySelector(".current-value-unit")!.textContent).toBe("MPa");
    expect(c.querySelector(".current-value-unit")).toBeNull();
  });

  it("値が無い(--)場合も単位は数値の横に出る。value_unit未提供の古い応答でも落ちない", async () => {
    standardMocks([get("/api/monitors", { monitors: [
      monitor({ id: 2, display_name: "A", current_value: null, value_unit: "m³" }),
      { ...monitor({ id: 3, display_name: "B" }), value_unit: undefined } as never,
      monitor({ id: 4, display_name: "C" }),
    ] })]);
    renderApp("/");
    const [a, b] = await cards();
    expect(a.querySelector(".current-value-number")!.textContent).toBe("--");
    expect(b.querySelector(".current-value-unit")).toBeNull();
  });

  it("長い単位(16文字)でも数値を押し出さない: 単位だけが省略表示(ellipsis)され、title属性で全文が分かる", async () => {
    const long = "あいうえおかきくけこさしすせそた";
    expect(long.length).toBeLessThanOrEqual(16);
    standardMocks([get("/api/monitors", { monitors: [monitor({ id: 2, display_name: "A", value_unit: long }), monitor({ id: 3, display_name: "B" }), monitor({ id: 4, display_name: "C" })] })]);
    renderApp("/");
    const [a] = await cards();
    expect(a.querySelector(".current-value-unit")!.getAttribute("title")).toBe(long);
    expect(value(".dashboard-page .current-value-unit", "flex")).toBe("0 1 auto"); // 単位だけが縮む
    expect(value(".dashboard-page .current-value-unit", "text-overflow")).toBe("ellipsis");
    expect(value(".dashboard-page .current-value-unit", "overflow")).toBe("hidden");
    expect(value(".dashboard-page .current-value-unit", "white-space")).toBe("nowrap");
    expect(value(".dashboard-page .current-value-head", "min-width")).toBe("0"); // 単位は「現在値」ラベルの行(数値の幅を奪わない)
  });

  it("見た目: 単位は数値(32〜38px)より小さい15〜16px・太さ600・補助色で、「現在値」ラベルの行に置く", () => {
    expect(parseFloat(value(".dashboard-page .current-value-unit", "font-size")!)).toBeGreaterThanOrEqual(15);
    expect(parseFloat(value(".dashboard-page .current-value-unit", "font-size")!)).toBeLessThanOrEqual(16);
    expect(value(".dashboard-page .current-value-unit", "font-weight")).toBe("600");
    expect(value(".dashboard-page .current-value-unit", "color")).toBe("var(--color-text-secondary)");
    expect(value(".dashboard-page .current-value-head", "align-items")).toBe("baseline");
    expect(value(".dashboard-page .monitor-card .card-body .card-value-primary strong", "font-size")).toBe("clamp(32px, 2.1vw, 38px)");
  });

  it("Dashboardに単位を出しても、履歴の表の列・セルには単位を追加しない(今回の範囲外)", async () => {
    standardMocks([get("/api/monitors", { monitors: [monitor({ id: 2, display_name: "A", value_unit: "m³" }), monitor({ id: 3, display_name: "B" }), monitor({ id: 4, display_name: "C" })] })]);
    renderApp("/");
    await cards();
    expect(document.querySelector(".records-section")!.textContent).not.toContain("m³");
    fireEvent.scroll(window);
  });
});
