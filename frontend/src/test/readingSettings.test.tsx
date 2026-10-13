/// <reference types="vite/client" />
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import stylesheet from "../styles.css?raw";
import { ReadingSettingsPanel, candidateDifference, judgement } from "../components/ReadingSettingsPanel";
import type { BaselineStatus, ReadingDiagnostics, ReadingSettings } from "../types";

const css = stylesheet.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = (selector: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].filter((m) => m[1].split(",").map((x: string) => x.trim()).includes(selector)).map((m) => m[2]);
const decl = (selector: string, property: string) => { const hits = rules(selector).map((b) => new RegExp(`(?:^|[;\\s])${property}\\s*:\\s*([^;]+)`).exec(b)?.[1]?.trim()).filter(Boolean); return hits[hits.length - 1]; };

const reading: ReadingSettings = { enabled: true, mode: "majority", window_size: 5, required_matches: 3, min_confidence: 0.6, expected_digits: 7, decimal_position: 0, monotonic: true, max_rate_per_minute: null, max_consecutive_failures: 5, allow_rollover: false, rollover_max: null };

const status = (over: Partial<BaselineStatus> = {}, baselineValue: string | null = "215998"): BaselineStatus => ({
  monitor_id: 3,
  baseline: baselineValue === null ? null : { value: baselineValue, numeric_value: baselineValue, confirmed_at: "2026-10-13T04:00:12Z", age_seconds: 30, source: "confirmed", state: "active", epoch: 6, decimal_position: 0, expected_digits: 7 },
  conflict: null, candidate: { value: "215993", agreement_count: 5 }, latest_raw: "0215993", current_confirmed: "215998",
  reading: { enabled: true, monotonic: true, allow_rollover: false, max_rate_per_minute: null, decimal_position: 0, expected_digits: 7 }, alert_seconds: 300, runtime_active: true, ...over,
});
const diagnostics = (validation: string): ReadingDiagnostics => ({
  enabled: true, mode: "majority", consecutive_failures: 0, recent_raw: [], baseline: null, candidate: null, conflict: null,
  confirmed: { value: "215998", confidence: 0.9, confirmed_at: null, raw_count: 5, agreement_count: 5, engine: "cpp_onnx", validation_status: validation, raw_value: "0215993", raw_confidence: 0.9 },
});

function renderPanel(props: { value?: Partial<ReadingSettings>; baseline?: BaselineStatus | null | undefined; diagnostics?: ReadingDiagnostics | null; onChange?: (v: ReadingSettings) => void; open?: boolean }) {
  const onChange = props.onChange ?? vi.fn();
  render(<ReadingSettingsPanel value={{ ...reading, ...props.value }} onChange={onChange} open={props.open ?? true} onToggleOpen={() => {}} baseline={props.baseline} diagnostics={props.diagnostics} />);
  return onChange;
}
const card = () => screen.getByLabelText("現在の判定状態");

describe("積算値チェック: 読取基準値・最新候補値・差・判定(read-only)", () => {
  it("1. 現在の読取基準値が表示される(由来・確定日時は詳細に)", () => {
    renderPanel({ baseline: status() });
    expect(within(card()).getByText("現在の読取基準値")).toBeInTheDocument();
    expect(within(card()).getByText("215998")).toBeInTheDocument();
    expect(screen.getByText(/由来 通常確定 \/ epoch 6/)).toBeInTheDocument();
    expect(card().querySelector(".rs-status-detail")).toBeNull(); // 詳細は見出し行(カードの外)で、閉じている間は高さを増やさない
    expect((document.querySelector(".rs-group-head details") as HTMLDetailsElement).open).toBe(false);
  });
  it("2. 基準値が未設定の場合は「未設定」", () => {
    renderPanel({ baseline: status({ candidate: null, latest_raw: null }, null) });
    expect(within(card()).getByText("未設定")).toBeInTheDocument();
    expect(screen.getByText(/基準値は未設定です/)).toBeInTheDocument();
  });
  it("3/4. 最新候補値と、基準値との差(-5)が表示される", () => {
    renderPanel({ baseline: status() });
    expect(within(card()).getByText("最新候補値")).toBeInTheDocument();
    expect(within(card()).getByText("215993")).toBeInTheDocument();
    expect(within(card()).getByText("-5")).toBeInTheDocument();
  });
  it("5. 候補が基準値未満(decrease_detected)なら「基準値未満のため不採用」を警告表示し、英語のstatusだけを表示しない", () => {
    renderPanel({ baseline: status(), diagnostics: diagnostics("decrease_detected") });
    expect(within(card()).getByText("基準値未満のため不採用")).toBeInTheDocument();
    expect(card()).toHaveClass("warn");
    expect(card().textContent).not.toContain("decrease_detected");
  });
  it("candidate APIが無くてもlatest_rawの先頭0を除いて候補値にする", () => {
    renderPanel({ baseline: status({ candidate: null, latest_raw: "0215993" }) });
    expect(within(card()).getByText("215993")).toBeInTheDocument();
  });
  it("候補が基準値以上なら不採用にしない(通常の表示)", () => {
    renderPanel({ baseline: status({ candidate: { value: "216001", agreement_count: 5 } }), diagnostics: diagnostics("confirmed") });
    expect(within(card()).getByText("+3")).toBeInTheDocument();
    expect(card()).not.toHaveClass("warn");
  });
  it("7. 基準値の取得に失敗しても「取得できません」と表示し、設定自体は操作できる", () => {
    const onChange = renderPanel({ baseline: null });
    expect(within(card()).getByText("取得できません")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("判定ウィンドウ"), { target: { value: "7" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ window_size: 7 }));
  });
  it("基準値を読み込み中の表示", () => {
    renderPanel({ baseline: undefined, diagnostics: null });
    expect(within(card()).getByText(/読み込み中/)).toBeInTheDocument();
  });
  it("基準値そのものはこの画面で編集できず、reset / rebase は診断タブへ案内する", () => {
    renderPanel({ baseline: status() });
    expect(screen.getByText(/reset \/ rebase は、診断タブから操作します/)).toBeInTheDocument();
    expect(within(card()).queryAllByRole("textbox")).toHaveLength(0);
    expect(within(card()).queryAllByRole("spinbutton")).toHaveLength(0);
  });
});

describe("文言・summary", () => {
  it("6. 減少チェックの説明: ON / OFF で説明が変わる(内部用語 monotonic は前面に出さない)", () => {
    const { unmount } = render(<ReadingSettingsPanel value={reading} onChange={() => {}} open onToggleOpen={() => {}} baseline={status()} />);
    expect(screen.getByRole("note")).toHaveTextContent("現在の読取基準値より小さい候補値は、減少と判断して採用しません。");
    expect(screen.getByRole("switch", { name: "積算値の減少を検出する" })).toHaveAttribute("aria-checked", "true");
    unmount();
    render(<ReadingSettingsPanel value={{ ...reading, monotonic: false }} onChange={() => {}} open onToggleOpen={() => {}} baseline={status()} />);
    expect(screen.getByRole("note")).toHaveTextContent("OFFの場合、基準値より小さい値でも、他の判定条件を満たせば採用されます。");
    expect(screen.getByRole("switch", { name: "積算値の減少を検出する" })).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByText("値の減少を許可しない")).toBeNull();
  });
  it("8. summary: 有効 / 3回一致 / 減少チェックON / 基準値 215998(majorityや単調増加は前面に出さない)", () => {
    const { unmount } = render(<ReadingSettingsPanel value={reading} onChange={() => {}} open={false} onToggleOpen={() => {}} baseline={status()} />);
    expect(screen.getByText("有効 / 3回一致 / 減少チェックON / 基準値 215998")).toBeInTheDocument();
    unmount();
    render(<ReadingSettingsPanel value={{ ...reading, monotonic: false, enabled: false }} onChange={() => {}} open={false} onToggleOpen={() => {}} baseline={status({}, null)} />);
    expect(screen.getByText("無効 / 3回一致 / 減少チェックOFF / 基準値 未設定")).toBeInTheDocument();
  });
  it("最大変化率・期待桁数・小数点位置の説明がある。majority/consecutiveは詳細設定の「多数決/連続一致」に置く", () => {
    renderPanel({ baseline: status() });
    expect(screen.getByText(/1分あたりに許容する最大増加量。制限なしの場合は急増チェックを行いません。/)).toBeInTheDocument();
    expect(screen.getByText(/推論結果として期待する数字の桁数。異なる桁数は invalid_format として採用しません/)).toBeInTheDocument();
    expect(screen.getByText(/右から何桁を小数部として扱うか（例: 2 → 12345 は 123.45）/)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "多数決（majority）" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "連続一致（consecutive）" })).toBeInTheDocument();
  });
  it("グループ見出し: 判定の安定化 / 桁・数値形式 / 読取失敗 / 積算値チェック", () => {
    renderPanel({ baseline: status() });
    for (const name of ["判定の安定化", "桁・数値形式", "読取失敗", "積算値チェック"]) expect(screen.getByRole("heading", { name })).toBeInTheDocument();
  });
  it("安定化のON/OFFはswitch(ON/OFF表示)で、操作すると設定が変わる", () => {
    const onChange = renderPanel({ baseline: status() });
    fireEvent.click(screen.getByRole("switch", { name: "安定化" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
    fireEvent.click(screen.getByRole("switch", { name: "積算値の減少を検出する" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ monotonic: false }));
  });
});

describe("純粋関数", () => {
  it("candidateDifference: 小数桁を揃え、符号つきで返す", () => {
    expect(candidateDifference("215993", "215998")).toEqual({ text: "-5", negative: true });
    expect(candidateDifference("216001", "215998")).toEqual({ text: "+3", negative: false });
    expect(candidateDifference("372449.9", "372446.8")).toEqual({ text: "+3.1", negative: false });
    expect(candidateDifference("100.0", "100")).toEqual({ text: "0.0", negative: false });
    expect(candidateDifference(null, "1")).toBeNull();
  });
  it("judgement: 減少チェックONで候補<基準値なら不採用、OFFなら比較しない", () => {
    expect(judgement(true, { negative: true }, "confirmed")).toEqual({ text: "基準値未満のため不採用", warn: true });
    expect(judgement(false, { negative: true }, null)?.text).toBe("減少チェックOFFのため基準値との比較なし");
    expect(judgement(true, null, "invalid_format")?.text).toContain("桁数");
    expect(judgement(true, null, null)).toBeNull();
  });
});

describe("コンパクトなレイアウト(入力欄の幅・列数・高さ)", () => {
  it("9. 数値入力はすべて専用のcompactなfield内にあり、幅は7rem(長い項目は10rem)で、100%幅ではない", () => {
    renderPanel({ baseline: status() });
    const inputs = document.querySelectorAll<HTMLInputElement>('.reading-settings-body input[type="number"]');
    expect(inputs.length).toBeGreaterThanOrEqual(7);
    for (const input of inputs) expect(input.closest(".reading-setting-field")).not.toBeNull();
    expect(decl('.settings-tab .reading-setting-field input[type="number"]', "width")).toBe("7rem");
    expect(decl('.settings-tab .reading-setting-field.compact-wide input[type="number"]', "width")).toBe("10rem");
    expect(parseFloat(decl('.settings-tab .reading-setting-field.compact-wide input[type="number"]', "width")!)).toBeLessThanOrEqual(12);
    expect(document.querySelectorAll(".reading-setting-field.compact-wide")).toHaveLength(3); // 最大変化率・連続読取失敗許容回数・判定方式
  });
  it("10. 通常幅では2〜4列のgrid(max-contentの列)で横並び", () => {
    expect(decl(".reading-settings-grid", "display")).toBe("grid");
    const has = (selector: string, text: string) => rules(selector).some((body) => body.includes(text));
    expect(has(".reading-settings-grid.cols-3", "grid-template-columns: repeat(3, minmax(0, max-content))")).toBe(true);
    expect(has(".reading-settings-grid.cols-4", "grid-template-columns: repeat(4, minmax(0, max-content))")).toBe(true);
    expect(has(".rs-groups", "grid-template-columns: repeat(2, minmax(0, 1fr))")).toBe(true); // グループも2列
  });
  it("11. 狭い幅では1〜2列へ折り返す(1100px以下で2列、520px以下で1列)", () => {
    const narrow = [...stylesheet.matchAll(/@media \(max-width: 1100px\) \{([\s\S]*?)\n\}/g)].map((m) => m[1]).join("\n");
    expect(narrow).toMatch(/\.rs-groups \{ grid-template-columns: minmax\(0, 1fr\); \}/);
    expect(narrow).toMatch(/\.reading-settings-grid\.cols-3, \.reading-settings-grid\.cols-4 \{ grid-template-columns: repeat\(2, minmax\(0, max-content\)\); \}/);
    const tiny = [...stylesheet.matchAll(/@media \(max-width: 520px\) \{([\s\S]*?)\n\}/g)].map((m) => m[1]).join("\n");
    expect(tiny).toContain(".reading-settings-grid.cols-4");
    expect(tiny).toContain("grid-template-columns: minmax(0, 1fr)");
  });
  it("12. 長い説明文は常時表示せず(折りたたみ/短い1行)、説明は小さい行間で高さを増やさない", () => {
    renderPanel({ baseline: status() });
    const advanced = document.querySelector("details.rs-advanced") as HTMLDetailsElement;
    expect(advanced.open).toBe(false); // 小数点位置の長い説明は「詳細設定」の中(閉じている)
    expect(advanced.textContent).toContain("先頭の0は確定値");
    expect(document.querySelectorAll("details.rs-more")).toHaveLength(0);
    for (const hint of document.querySelectorAll(".rs-hint")) if (!hint.closest(".rs-advanced")) expect(hint.textContent!.length).toBeLessThan(140);
    expect(decl(".rs-hint", "font-size")).toBe("11px");
    expect(parseFloat(decl(".rs-hint", "line-height")!)).toBeLessThanOrEqual(1.4);
  });
});
