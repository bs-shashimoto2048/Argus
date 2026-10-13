import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { defaultRecordPeriod, oneMonthAgoJst, oneMonthBefore } from "../utils/records";
import { get, renderApp, standardMocks } from "./helpers";
import type { Call } from "./helpers";

// 今日 = 2026-10-09 (JST)
beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-10-09T05:30:00Z")); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

const recordCalls = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/records?")).map((c) => new URL(c.url, "http://x").searchParams);
const dateInputs = () => [screen.getByLabelText("開始日") as HTMLInputElement, screen.getByLabelText("終了日") as HTMLInputElement];

describe("暦上の1か月前", () => {
  it("同じ日付の前月(30日前ではない)", () => {
    expect(oneMonthBefore("2026-10-13")).toBe("2026-09-13");
    expect(oneMonthBefore("2026-10-31")).toBe("2026-09-30"); // 9月は30日まで → 最終日へ丸める
    expect(oneMonthBefore("2026-12-31")).toBe("2026-11-30");
  });
  it("月末は存在する最終日へ丸める(うるう年を含む)", () => {
    expect(oneMonthBefore("2026-03-31")).toBe("2026-02-28");
    expect(oneMonthBefore("2028-03-31")).toBe("2028-02-29");
    expect(oneMonthBefore("2026-03-29")).toBe("2026-02-28");
    expect(oneMonthBefore("2028-03-29")).toBe("2028-02-29");
    expect(oneMonthBefore("2026-05-31")).toBe("2026-04-30");
  });
  it("1月は前年12月", () => {
    expect(oneMonthBefore("2026-01-15")).toBe("2025-12-15");
    expect(oneMonthBefore("2026-01-31")).toBe("2025-12-31");
  });
  it("JSTの今日を基準にする(UTCでは前日でもJSTの日付で計算)", () => {
    expect(oneMonthAgoJst(new Date("2026-03-30T16:00:00Z"))).toBe("2026-02-28"); // JST 3/31 01:00
    expect(defaultRecordPeriod(new Date("2026-10-13T00:00:00Z"))).toEqual({ mode: "today", startDate: "2026-09-13", endDate: "2026-10-13" });
  });
});

describe("任意期間の初期値(1か月前 〜 今日)", () => {
  it("Dashboard: 初めて「任意期間」を押すと、すぐ1か月前〜今日で表示・取得される。今日表示中のAPIは今日だけ", async () => {
    const mocks = standardMocks();
    const user = userEvent.setup();
    renderApp("/");
    await waitFor(() => expect(recordCalls(mocks.calls).length).toBeGreaterThan(0));
    expect(recordCalls(mocks.calls).some((p) => p.get("from") === "2026-10-09T00:00:00+09:00" && p.get("limit") === "1000")).toBe(true); // 既定の表示は今日のまま
    await user.click(screen.getByRole("button", { name: "任意期間" }));
    const [start, end] = dateInputs();
    expect(start.value).toBe("2026-09-09");
    expect(end.value).toBe("2026-10-09");
    await waitFor(() => expect(recordCalls(mocks.calls).some((p) => p.get("from") === "2026-09-09T00:00:00+09:00" && p.get("to") === "2026-10-10T00:00:00+09:00")).toBe(true));
  });

  it("手動で変えた日付は、今日/過去7日へ切り替えて戻っても上書きされない", async () => {
    standardMocks();
    const user = userEvent.setup();
    renderApp("/");
    await user.click(screen.getByRole("button", { name: "任意期間" }));
    fireEvent.change(dateInputs()[0], { target: { value: "2026-09-20" } });
    expect(dateInputs()[0].value).toBe("2026-09-20");
    await user.click(screen.getByRole("button", { name: "今日" }));
    await user.click(screen.getByRole("button", { name: "過去7日" }));
    await user.click(screen.getByRole("button", { name: "任意期間" }));
    expect(dateInputs()[0].value).toBe("2026-09-20");
    expect(dateInputs()[1].value).toBe("2026-10-09");
  });

  it("履歴・データ画面も同じ初期値", async () => {
    standardMocks();
    const user = userEvent.setup();
    renderApp("/history");
    await user.click(await screen.findByRole("button", { name: "任意期間" }));
    expect(dateInputs().map((i) => i.value)).toEqual(["2026-09-09", "2026-10-09"]);
  });
});
