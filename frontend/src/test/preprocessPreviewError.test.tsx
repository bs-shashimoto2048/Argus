import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { PreprocessEditor } from "../components/PreprocessEditor";
import { json, mockFetch, route } from "./helpers";

const roi = { x: 0.5, y: 0, width: 0.02, height: 1 };
const props = { monitorId: 4, roi, initial: {}, onClose: () => {}, onSaved: () => {} };

describe("前処理Previewの出力サイズ上限(Issue #81)", () => {
  it("上限超過で422が返ると、理由(ROIの幅/Resize widthの見直し)を画面に表示する", async () => {
    const detail = "前処理Previewの出力サイズ(4096x116413px)が上限を超えます。ROIの幅を広げるか、Resize widthを小さくしてください";
    mockFetch([route("POST", "/api/monitors/4/preprocess/preview", () => json({ detail }, 422))]);
    render(<PreprocessEditor {...props} />);
    await waitFor(() => expect(screen.getByText(/出力サイズ\(4096x116413px\)が上限を超えます/)).toBeInTheDocument());
    expect(screen.getByText(/ROIの幅を広げるか、Resize widthを小さくしてください/)).toBeInTheDocument();
    expect(screen.queryByText("Preview待機中")).not.toBeInTheDocument();
  });

  it("通常は従来どおり、取得できるまで『Preview待機中』を表示する", () => {
    mockFetch([route("POST", "/api/monitors/4/preprocess/preview", () => new Promise<Response>(() => {}) as unknown as Response)]);
    render(<PreprocessEditor {...props} />);
    expect(screen.getByText("Preview待機中")).toBeInTheDocument();
  });
});
