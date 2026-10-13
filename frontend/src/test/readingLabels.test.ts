import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import {
  AI_VALUE_AUTOFILL_ALLOWED, AI_VALUE_AUTOFILL_BLOCKED_MESSAGE, AI_VALUE_AUTOFILL_WARNING, BASELINE_FAR_MESSAGE, CORRECTION_FAR_MESSAGE,
  baselineActionLabel, baselineSourceLabel, baselineStateLabel, carriedNoteBody, internalName, userErrorMessage,
  validationStatusDescription, validationStatusLabel, valueSourceDescription, valueSourceLabel,
} from "../utils/readingLabels";

describe("読取結果(validation_status)の日本語化", () => {
  it.each([
    ["confirmed", "採用"],
    ["low_confidence", "信頼度が低いため要確認"],
    ["decrease_detected", "読取基準値より小さいため不採用"],
    ["rate_exceeded", "増加量が設定上限を超えたため不採用"],
    ["invalid_format", "表示桁数・小数部の形式が一致しないため不採用"],
    ["no_reading", "読取値を取得できません"],
    ["pending", "判定中"],
  ])("%s → %s", (status, label) => expect(validationStatusLabel(status)).toBe(label));

  it("未知のstatusは「判定状態を確認してください」。値が無ければ「--」", () => {
    expect(validationStatusLabel("something_new")).toBe("判定状態を確認してください");
    expect(validationStatusLabel(null)).toBe("--");
  });

  it("説明: 減少 — 現在の読取基準値との比較と、直前の正式値の継続使用を説明する(内部名は出さない)", () => {
    const text = validationStatusDescription("decrease_detected", "0215993", "215998")!;
    expect(text).toBe("今回のAI読取値「215993」は、現在の読取基準値「215998」より小さいため採用されませんでした。\nそのため、直前まで使用していた正式値をこの記録でも使用しています。");
    expect(text).not.toMatch(/decrease_detected/);
  });
  it("説明: 形式不一致 / 増加量超過 / 読取不能", () => {
    expect(validationStatusDescription("invalid_format", "37245.7")).toBe("今回のAI読取値「37245.7」は、設定された表示桁数・小数部の形式と一致しなかったため、正式値として採用されませんでした。\nそのため、直前の正式値を継続使用しています。");
    expect(validationStatusDescription("rate_exceeded", "372500")).toBe("今回のAI読取値「372500」は、設定した1分あたりの最大増加量を超えたため採用されませんでした。\nそのため、直前の正式値を継続使用しています。");
    expect(validationStatusDescription("no_reading")).toBe("この時刻はAI読取値を取得できなかったため、直前の正式値を継続使用しています。");
  });
  it("説明: 採用(confirmed)・未知は説明なし。carriedNoteBodyは未知でも一般的な説明を返す", () => {
    expect(validationStatusDescription("confirmed", "1")).toBeNull();
    expect(validationStatusDescription("unknown", "1")).toBeNull();
    expect(carriedNoteBody({ validation_status: "unknown", raw_value: "0123" })).toBe("今回のAI読取値「123」は採用されなかったため、直前の正式値を継続使用しています。");
  });
  it("技術者向け画面の併記: 日本語（内部名）", () => {
    expect(internalName(validationStatusLabel("decrease_detected"), "decrease_detected")).toBe("読取基準値より小さいため不採用（decrease_detected）");
  });
});

describe("最新のAI読取値の自動入力の可否", () => {
  it("形式が成立していない読取結果は不可。形式が正常なまま不採用だったものは警告つきで可", () => {
    for (const status of ["invalid_format", "no_reading", "pending", "something_new", ""]) expect(AI_VALUE_AUTOFILL_ALLOWED.has(status)).toBe(false);
    for (const status of ["confirmed", "low_confidence", "decrease_detected", "rate_exceeded"]) expect(AI_VALUE_AUTOFILL_ALLOWED.has(status)).toBe(true);
    expect([...AI_VALUE_AUTOFILL_WARNING].sort()).toEqual(["decrease_detected", "rate_exceeded"]);
    expect(AI_VALUE_AUTOFILL_BLOCKED_MESSAGE).toBe("最新のAI読取値は、設定された表示桁数・小数部の形式と一致しないため自動入力できません。画像を確認して正式値を入力してください。");
  });
});

describe("正式値の決まり方・読取基準値の用語", () => {
  it("正式値の決まり方", () => {
    expect(valueSourceLabel("confirmed")).toBe("今回のAI読取値を採用");
    expect(valueSourceLabel("carried_forward")).toBe("直前の正式値を継続使用");
    expect(valueSourceLabel("none")).toBe("正式値なし");
    expect(valueSourceLabel("carried_forward", true)).toBe("直前の正式値を継続使用 → 運用者が確認・修正");
    expect(valueSourceLabel("confirmed", true)).toBe("運用者が確認・修正");
    expect(valueSourceDescription("carried_forward")).toContain("直前まで使用していた正式値");
  });
  it("読取基準値: 決まり方・状態・操作の名称(rebase / reset を出さない)", () => {
    expect(baselineSourceLabel("confirmed")).toBe("通常確定");
    expect(baselineSourceLabel("operator_rebase")).toBe("運用者が変更");
    expect(baselineStateLabel("pending_reset")).toBe("未設定（次の正常なAI読取値を自動設定）");
    expect(baselineStateLabel("active")).toBe("有効");
    expect(baselineActionLabel("reset")).toBe("読取基準値を未設定に戻す");
    expect(baselineActionLabel("rebase")).toBe("読取基準値を変更");
    expect(baselineActionLabel("auto_semantic_reset")).toBe("読取設定の変更に伴い読取基準値を自動解除");
    expect(baselineActionLabel("x")).not.toMatch(/rebase|reset/);
  });
});

describe("APIエラーの利用者向け表示(内部codeを出さない)", () => {
  const apiError = (code: string, message: string, status = 409) => new ApiError(status, { code, message });
  it("補正・基準値の確認要求は日本語の案内にする", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(userErrorMessage(apiError("CORRECTION_FORCE_REQUIRED", "x"))).toBe(CORRECTION_FAR_MESSAGE);
    expect(userErrorMessage(apiError("REBASE_FORCE_REQUIRED", "x"))).toBe(BASELINE_FAR_MESSAGE);
    expect(userErrorMessage(apiError("FORCE_REQUIRED", "x"))).toBe(BASELINE_FAR_MESSAGE);
    expect(userErrorMessage(apiError("NO_CHANGE", "x"))).toBe("現在の値と同じです。");
    expect(userErrorMessage(apiError("NOT_CORRECTABLE", "x"))).toBe("この記録の正式値は修正できません。");
    expect(userErrorMessage(apiError("INVALID_VALUE", "桁数が期待桁数(7桁)を超えています", 422))).toBe("桁数が期待桁数(7桁)を超えています");
    expect(warn).toHaveBeenCalled(); // 内部codeはconsoleへ
    warn.mockRestore();
  });
  it("codeそのものがmessageのとき・messageが無いときは、codeを出さず一般的な案内にする", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(userErrorMessage(new ApiError(409, { code: "SOME_CODE", message: "SOME_CODE" }))).toBe("処理に失敗しました（HTTP 409）");
    expect(userErrorMessage(new ApiError(500, undefined))).toBe("処理に失敗しました（HTTP 500）");
    warn.mockRestore();
  });
  it("ApiError以外はそのメッセージ", () => expect(userErrorMessage(new Error("ネットワークに接続できません"))).toBe("ネットワークに接続できません"));
});
