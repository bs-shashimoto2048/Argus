/// <reference types="vite/client" />
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import stylesheet from "../styles.css?raw";
import { CorrectionDialog } from "../components/CorrectionDialog";
import { RecordDrawer } from "../components/RecordDrawer";
import { limitImageUpscale } from "../utils/records";
import { get, mockFetch, record } from "./helpers";

const css = stylesheet.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].split(",").map((x: string) => x.trim()).includes(selector)).map((m) => m[2]);
const value = (selector: string, property: string) => { const hits = rules(selector).map((b) => new RegExp(`(?:^|[;\\s])${property}\\s*:\\s*([^;]+)`).exec(b)?.[1]?.trim()).filter(Boolean); return hits[hits.length - 1]; };

// 記録画像(元画像・推論結果画像、digital/drum共通)は、画像全体が必ず枠内に収まる(cropしない)。画像自身の縦横比を優先し、固定比にしない。
describe.each([[".correction-image"], [".drawer-image"]])("%s(画像を切らない共通CSS)", (box) => {
  it("img: contain(coverは使わない)・幅は枠内・高さはauto(natural aspect)・最大高さはmin(40vh, 420px)", () => {
    expect(value(`${box} img`, "object-fit")).toBe("contain");
    expect(value(`${box} img`, "object-position")).toBe("center");
    expect(value(`${box} img`, "max-width")).toBe("100%");
    expect(value(`${box} img`, "width")).toBe("100%");
    expect(value(`${box} img`, "height")).toBe("auto");
    expect(value(`${box} img`, "max-height")).toBe("min(40vh, 420px)");
    expect(rules(`${box} img`).join(";")).not.toMatch(/object-fit:\s*cover/);
  });
  it("枠: 固定の縦横比にしない・背景は映像と同じ #0f172a・横にはみ出さない(min-width: 0 / overflow: hidden)", () => {
    expect(value(box, "aspect-ratio")).toBeUndefined();
    expect(value(box, "background")).toBe("#0f172a");
    expect(value(box, "min-width")).toBe("0");
    expect(value(box, "max-width")).toBe("100%");
    expect(value(box, "overflow")).toBe("hidden");
  });
});

describe("レイアウトがはみ出さない", () => {
  it("読取値修正ダイアログ: 右の情報欄を押し出さない(minmax(0,1.5fr) / minmax(300px,1fr)、各列 min-width: 0)", () => {
    expect(rules(".correction-grid").some((body) => /grid-template-columns:\s*minmax\(0, 1\.5fr\) minmax\(300px, 1fr\)/.test(body))).toBe(true); // 2列(760px以下は1列へ切替)
    expect(value(".correction-grid > *", "min-width")).toBe("0");
    expect(rules(".correction-grid").join(";")).toContain("grid-template-columns");
    expect(value(".correction-image", "grid-template-columns")).toBe("minmax(0, 1fr)"); // 画像のnatural widthで暗黙の列が広がらない
    expect(value(".correction-media", "min-width")).toBe("0");
  });
  it("読取値修正ダイアログ: 横長のドラムcropを確認できるよう幅は min(1100px, 96vw)(固定の巨大幅にしない)", () => {
    expect(value(".correction-modal", "width")).toBe("min(1100px, 96vw)");
  });
  it("拡大表示: 画像全体を contain で表示(幅100%・高さauto・92vh以内)", () => {
    expect(value(".correction-zoom-image", "object-fit")).toBe("contain");
    expect(value(".correction-zoom-image", "width")).toBe("100%");
    expect(value(".correction-zoom-image", "height")).toBe("auto");
    expect(value(".correction-zoom-image", "max-height")).toBe("92vh");
  });
  it("記録Drawer: 画像のnatural widthでDrawer自体が広がらない(min-width: 0 / overflow-x: hidden)", () => {
    expect(value(".record-drawer", "min-width")).toBe("0");
    expect(value(".record-drawer", "overflow-x")).toBe("hidden");
    expect(value(".record-drawer > *", "min-width")).toBe("0");
  });
});

describe("limitImageUpscale", () => {
  const img = (naturalWidth: number) => Object.assign(document.createElement("img"), {}) as HTMLImageElement & { naturalWidth: number };
  it("小さい画像は最大2倍まで(最小240px)、大きい画像は枠が決める(2倍の上限は枠より大きい)", () => {
    const small = document.createElement("img");
    Object.defineProperty(small, "naturalWidth", { value: 120 });
    limitImageUpscale(small);
    expect(small.style.maxWidth).toBe("240px");
    const medium = document.createElement("img");
    Object.defineProperty(medium, "naturalWidth", { value: 300 });
    limitImageUpscale(medium);
    expect(medium.style.maxWidth).toBe("600px");
    const unloaded = img(0);
    limitImageUpscale(unloaded);
    expect(unloaded.style.maxWidth).toBe(""); // 未読込(naturalWidth 0)では何もしない
  });
});

describe("記録Drawer / 読取値修正ダイアログの画像", () => {
  const carried = record({ id: 84, monitor_id: 4, monitor_name: "食堂前機械室内メータ用", value_source: "carried_forward", validation_status: "invalid_format", correctable: true, correctable_reason: "carried_forward" });

  it("元画像 / 推論結果画像を切り替えても、同じ枠(.drawer-image)・同じimg要素の配置(containで全体表示)", async () => {
    mockFetch([get("/api/records/84/corrections", { corrections: [] })]);
    const user = userEvent.setup();
    render(<RecordDrawer record={carried} onClose={() => {}} onCorrected={() => {}} />);
    const frame = () => document.querySelector(".drawer-image") as HTMLElement;
    const original = frame().querySelector("img") as HTMLImageElement;
    expect(original).toHaveAttribute("alt", "記録時の元画像");
    expect(original.getAttribute("src")).toContain("/api/records/84/image/original");
    const classBefore = frame().className;
    await user.click(screen.getByRole("tab", { name: "推論結果画像" }));
    const overlay = frame().querySelector("img") as HTMLImageElement;
    expect(overlay).toHaveAttribute("alt", "記録時の推論結果画像"); // Drawerの推論結果画像
    expect(overlay.getAttribute("src")).toContain("/api/records/84/image/overlay");
    expect(frame().className).toBe(classBefore); // 枠は同じ(画像の種類で別の表示規則にしない)
    expect(document.querySelectorAll(".drawer-image")).toHaveLength(1);
    expect(overlay.closest(".record-drawer")).not.toBeNull(); // Drawerの内側に収まる
  });

  it("画像の読込後、小さい画像の拡大を制限する(onLoad)", async () => {
    mockFetch([get("/api/records/84/corrections", { corrections: [] })]);
    render(<RecordDrawer record={carried} onClose={() => {}} onCorrected={() => {}} />);
    const image = document.querySelector(".drawer-image img") as HTMLImageElement;
    Object.defineProperty(image, "naturalWidth", { value: 100 });
    fireEvent.load(image);
    expect(image.style.maxWidth).toBe("240px");
  });

  it("読取値修正ダイアログ: overlay画像は .correction-image の中のimgで、情報欄(dl)と同じgridに並ぶ", () => {
    mockFetch([get("/api/monitors/4/reading/baseline", { monitor_id: 4, baseline: null, conflict: null })]);
    render(<CorrectionDialog record={carried} onClose={() => {}} onCorrected={() => {}} />);
    const grid = document.querySelector(".correction-grid") as HTMLElement;
    const image = grid.querySelector(".correction-image img") as HTMLImageElement;
    expect(image).toHaveAttribute("alt", "記録時のAI読取結果画像");
    expect(image.getAttribute("src")).toContain("/api/records/84/image/overlay");
    expect(grid.querySelector(".correction-facts")).not.toBeNull();
    expect(grid.children).toHaveLength(2);
  });

  it("読取値修正ダイアログ: 推論結果画像 / 元画像を切り替えられ、どちらも同じ枠(.correction-image)で全体表示される", async () => {
    mockFetch([get("/api/monitors/4/reading/baseline", { monitor_id: 4, baseline: null, conflict: null })]);
    const user = userEvent.setup();
    render(<CorrectionDialog record={carried} onClose={() => {}} onCorrected={() => {}} />);
    const frame = () => document.querySelector(".correction-image") as HTMLElement;
    expect(frame().querySelector("img")).toHaveAttribute("alt", "記録時のAI読取結果画像"); // 既定は推論結果
    await user.click(screen.getByRole("tab", { name: "元画像" }));
    const original = frame().querySelector("img") as HTMLImageElement;
    expect(original).toHaveAttribute("alt", "記録時の元画像");
    expect(original.getAttribute("src")).toContain("/api/records/84/image/original");
    expect(document.querySelectorAll(".correction-image")).toHaveLength(1);
    await user.click(screen.getByRole("tab", { name: "推論結果画像" }));
    expect(frame().querySelector("img")).toHaveAttribute("alt", "記録時のAI読取結果画像");
  });

  it("読取値修正ダイアログ: 画像クリックで拡大(同じsrc・全体表示)、Escで拡大だけが閉じて修正ダイアログは残る", async () => {
    mockFetch([get("/api/monitors/4/reading/baseline", { monitor_id: 4, baseline: null, conflict: null })]);
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<CorrectionDialog record={carried} onClose={onClose} onCorrected={() => {}} />);
    expect(document.querySelector(".correction-lightbox")).toBeNull();
    await user.click(screen.getByRole("img", { name: "記録時のAI読取結果画像" }));
    const zoom = screen.getByRole("img", { name: "拡大表示: 記録時のAI読取結果画像" });
    expect(zoom.getAttribute("src")).toContain("/api/records/84/image/overlay");
    expect(zoom).toHaveClass("correction-zoom-image");
    await user.keyboard("{Escape}");
    expect(document.querySelector(".correction-lightbox")).toBeNull();
    expect(screen.getByRole("dialog", { name: "読取値の修正" })).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("img", { name: "記録時のAI読取結果画像" }));
    await user.click(screen.getByRole("button", { name: "拡大表示を閉じる" }));
    expect(document.querySelector(".correction-lightbox")).toBeNull();
  });

  it("読取値修正ダイアログ: 元画像しかない記録は元画像を表示、画像が無ければ「記録画像なし」(切替タブなし)", () => {
    mockFetch([get("/api/monitors/4/reading/baseline", { monitor_id: 4, baseline: null, conflict: null })]);
    const { unmount } = render(<CorrectionDialog record={{ ...carried, overlay_image_path: null }} onClose={() => {}} onCorrected={() => {}} />);
    expect(screen.getByRole("img", { name: "記録時の元画像" })).toBeInTheDocument();
    expect(screen.queryByRole("tab")).toBeNull();
    unmount();
    render(<CorrectionDialog record={{ ...carried, image_status: "not_saved", overlay_image_path: null, original_image_path: null }} onClose={() => {}} onCorrected={() => {}} />);
    expect(screen.getByText("記録画像なし")).toBeInTheDocument();
  });

  it("画像の読込に失敗しても、情報欄・入力欄は残る(画像だけ代替表示)", () => {
    mockFetch([get("/api/monitors/4/reading/baseline", { monitor_id: 4, baseline: null, conflict: null })]);
    render(<CorrectionDialog record={carried} onClose={() => {}} onCorrected={() => {}} />);
    fireEvent.error(screen.getByRole("img", { name: "記録時のAI読取結果画像" }));
    expect(screen.getByText("保存した画像を読み込めません")).toBeInTheDocument();
    expect(document.querySelector(".correction-facts")).not.toBeNull();
  });
});
