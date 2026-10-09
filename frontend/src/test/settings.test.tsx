import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { get, json, renderApp, route, standardMocks, storageSettings, storageStatus } from "./helpers";
import type { Call } from "./helpers";

afterEach(() => { vi.unstubAllGlobals(); });

const putCalls = (calls: Call[]) => calls.filter((c) => c.method === "PUT" && c.url === "/api/system/data-storage");

describe("システム設定: データ保存", () => {
  it("現在値を取得して表示する(未設定の保存先は既定値をplaceholderに)", async () => {
    standardMocks();
    renderApp("/settings");
    const imageInput = await screen.findByLabelText("画像保存先");
    expect(imageInput).toHaveValue("");
    expect(imageInput).toHaveAttribute("placeholder", "C:\\Argus\\data\\images");
    expect(screen.getByLabelText("Excel保存先")).toHaveAttribute("placeholder", "C:\\Argus\\data\\exports");
    expect(screen.getByLabelText("元画像を保存")).toBeChecked();
    expect(screen.getByLabelText("推論画像を保存")).toBeChecked();
    expect(screen.getByLabelText("容量警告しきい値 (GB)")).toHaveValue(10);
    expect(screen.getByLabelText("容量停止しきい値 (GB)")).toHaveValue(5);
  });

  it("保存状態(state・空き容量・しきい値・Worker・キュー・サーキット・失敗/見送り件数)を表示する", async () => {
    standardMocks();
    renderApp("/settings");
    const panel = await screen.findByLabelText("保存状態");
    expect(await within(panel).findByText("正常")).toHaveAttribute("data-state", "ok");
    expect(within(panel).getByText("296.5 GB")).toBeInTheDocument();
    expect(within(panel).getByText("10 GB")).toBeInTheDocument();
    expect(within(panel).getByText("5 GB")).toBeInTheDocument();
    expect(within(panel).getByText("稼働中")).toBeInTheDocument();
    expect(within(panel).getByText("0 件")).toBeInTheDocument(); // キュー
    expect(within(panel).getByText("閉(通常)")).toBeInTheDocument();
    expect(within(panel).getByText("1 件")).toBeInTheDocument(); // 保存失敗
    expect(within(panel).getByText("2 件")).toBeInTheDocument(); // 保存見送り
  });

  it.each([
    ["warning", "警告"], ["stopped", "保存停止"], ["failing", "保存先異常"], ["disabled", "保存無効"],
  ] as const)("状態 %s は「%s」と表示する", async (state, label) => {
    standardMocks([get("/api/system/data-storage/status", { ...storageStatus, state, circuit_open: state === "failing" })]);
    renderApp("/settings");
    expect(await screen.findByText(label)).toHaveAttribute("data-state", state);
  });

  it("Excel保存先・しきい値の変更は警告なしで保存できる(PUT)", async () => {
    const updated = { ...storageSettings, excel_output_folder: "\\\\server\\share\\Argus\\excel", storage_warn_free_gb: 20 };
    const mocks = standardMocks([route("PUT", "/api/system/data-storage", () => json(updated))]);
    const user = userEvent.setup();
    renderApp("/settings");
    const excel = await screen.findByLabelText("Excel保存先");
    await user.type(excel, "\\\\server\\share\\Argus\\excel");
    const warn = screen.getByLabelText("容量警告しきい値 (GB)");
    await user.clear(warn);
    await user.type(warn, "20");
    await user.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("データ保存設定を保存しました")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(); // Excel保存先の変更では警告しない
    expect(putCalls(mocks.calls)[0].body).toEqual({ image_root_folder: "", excel_output_folder: "\\\\server\\share\\Argus\\excel", save_original_image: true, save_overlay_image: true, storage_warn_free_gb: 20, storage_stop_free_gb: 5 });
  });

  it("画像保存先を変更するときは、保存前に警告を表示し、確認した場合だけ保存する", async () => {
    const updated = { ...storageSettings, image_root_folder: "D:\\ArgusData\\images", effective_image_root: "D:\\ArgusData\\images" };
    const mocks = standardMocks([route("PUT", "/api/system/data-storage", () => json(updated))]);
    const user = userEvent.setup();
    renderApp("/settings");
    await user.type(await screen.findByLabelText("画像保存先"), "D:\\ArgusData\\images");
    await user.click(screen.getByRole("button", { name: "保存" }));
    const dialog = await screen.findByRole("alertdialog", { name: "画像保存先の変更の確認" });
    expect(within(dialog).getByText("画像保存先を変更すると、以前の保存先にある過去画像を履歴画面から参照できなくなる場合があります。")).toBeInTheDocument();
    expect(putCalls(mocks.calls)).toHaveLength(0); // 確認前は保存しない

    await user.click(within(dialog).getByRole("button", { name: "キャンセル" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(putCalls(mocks.calls)).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "保存" }));
    await user.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "変更して保存" }));
    expect(await screen.findByText("データ保存設定を保存しました")).toBeInTheDocument();
    expect(putCalls(mocks.calls)).toHaveLength(1);
    expect((putCalls(mocks.calls)[0].body as { image_root_folder: string }).image_root_folder).toBe("D:\\ArgusData\\images");
  });

  it("画像保存先が未変更なら警告しない(UNCにも対応)", async () => {
    const unc = "\\\\server\\share\\Argus\\images";
    standardMocks([get("/api/system/data-storage", { ...storageSettings, image_root_folder: unc, effective_image_root: unc }), route("PUT", "/api/system/data-storage", () => json({ ...storageSettings, image_root_folder: unc, effective_image_root: unc }))]);
    const user = userEvent.setup();
    renderApp("/settings");
    expect(await screen.findByLabelText("画像保存先")).toHaveValue(unc);
    await user.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("データ保存設定を保存しました")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("不正なしきい値(停止 > 警告)は保存できない", async () => {
    standardMocks();
    const user = userEvent.setup();
    renderApp("/settings");
    const stop = await screen.findByLabelText("容量停止しきい値 (GB)");
    await user.clear(stop);
    await user.type(stop, "50");
    expect(await screen.findByText("停止しきい値は警告しきい値以下にしてください")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
  });

  it("保存がBackendに拒否されたらエラーを表示する", async () => {
    standardMocks([route("PUT", "/api/system/data-storage", () => json({ detail: "保存先は絶対パスで指定してください" }, 422))]);
    const user = userEvent.setup();
    renderApp("/settings");
    await user.type(await screen.findByLabelText("Excel保存先"), "relative");
    await user.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("保存先は絶対パスで指定してください");
  });

  it("書込みテスト: 画像保存先とExcel保存先それぞれで、入力中のパスを使って実行し結果を表示する", async () => {
    const mocks = standardMocks([route("POST", "/api/system/data-storage/test", (c) => {
      const body = c.body as { target: string; path?: string };
      return json(body.target === "image" ? { ok: true, path: body.path ?? null, message: "書き込みできました", free_gb: 123.4 } : { ok: false, path: body.path ?? null, message: "フォルダが見つかりません", free_gb: null });
    })]);
    const user = userEvent.setup();
    renderApp("/settings");
    await user.type(await screen.findByLabelText("画像保存先"), "D:\\ArgusData\\images");
    await user.click(screen.getByRole("button", { name: "画像保存先の書込みテスト" }));
    expect(await screen.findByText(/書き込みできました（空き容量 123.4 GB）/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Excel保存先"), "\\\\down\\share");
    await user.click(screen.getByRole("button", { name: "Excel保存先の書込みテスト" }));
    expect(await screen.findByText("フォルダが見つかりません")).toBeInTheDocument();
    const tests = mocks.calls.filter((c) => c.url === "/api/system/data-storage/test");
    expect(tests.map((c) => c.body)).toEqual([{ target: "image", path: "D:\\ArgusData\\images" }, { target: "excel", path: "\\\\down\\share" }]);
  });

  it("保存先が空欄の書込みテストは、既定の保存先を試す(pathを送らない)", async () => {
    const mocks = standardMocks([route("POST", "/api/system/data-storage/test", () => json({ ok: true, path: "C:\\Argus\\data\\exports", message: "書き込みできました", free_gb: 10 }))]);
    const user = userEvent.setup();
    renderApp("/settings");
    await user.click(await screen.findByRole("button", { name: "Excel保存先の書込みテスト" }));
    await waitFor(() => expect(screen.getByText(/書き込みできました/)).toBeInTheDocument());
    expect(mocks.calls.find((c) => c.url === "/api/system/data-storage/test")!.body).toEqual({ target: "excel" });
  });
});
