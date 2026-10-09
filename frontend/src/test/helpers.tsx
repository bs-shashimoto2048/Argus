import { vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { render } from "@testing-library/react";
import App from "../App";
import type { DataStorageSettings, DataStorageStatus, Monitor, ReadingRecord } from "../types";

export function monitor(over: Partial<Monitor> & { id: number }): Monitor {
  return {
    name: `m${over.id}`, display_name: `メーター${over.id}`, location: "", enabled: true, status: "running", created_at: "2026-10-01T00:00:00", updated_at: "2026-10-01T00:00:00",
    source: null, inference: { engine: "cpp_onnx", model_id: "digital_production_v1.onnx" } as Monitor["inference"], current_value: "265803", previous_value: null, confidence: 0.95,
    last_updated: "2026-10-09T00:00:00", previous_confidence: null, previous_confirmed_at: null, inference_status: "ok", last_inference_error: null, current_inference_error: null, reading_baseline: null, ...over,
  };
}

export function record(over: Partial<ReadingRecord> & { id: number }): ReadingRecord {
  return {
    monitor_id: 2, monitor_name: "エネセン内ガスメータ用２", hour_bucket: "2026-10-09T08:00:00+09:00", recorded_at: "2026-10-08T23:00:20", value: "265803", value_source: "confirmed",
    numeric_value: "265803", raw_value: "0265803", previous_value: "265799", usage: "4", confidence: 0.957, validation_status: "confirmed", display_status: "normal", baseline_conflict: false,
    engine: "cpp_onnx", model_id: "digital_production_v1.onnx", original_image_path: "a/orig.jpg", overlay_image_path: "a/over.jpg", image_status: "ok", image_error: null, ...over,
  };
}

export const storageSettings: DataStorageSettings = {
  image_root_folder: null, effective_image_root: "C:\\Argus\\data\\images", excel_output_folder: null, effective_excel_output_folder: "C:\\Argus\\data\\exports",
  save_original_image: true, save_overlay_image: true, storage_warn_free_gb: 10, storage_stop_free_gb: 5,
};
export const storageStatus: DataStorageStatus = {
  state: "ok", image_root: "C:\\Argus\\data\\images", image_root_is_default: true, save_original_image: true, save_overlay_image: true, free_gb: 296.5, warn_free_gb: 10, stop_free_gb: 5, space: "ok",
  worker_running: true, queue_length: 0, writing_seconds: null, circuit_open: false, counts: { ok: 3, failed: 1, dropped: 2 }, last_success_at: null, last_error: null, last_error_at: null, last_free_bytes: null,
};

export type Call = { url: string; method: string; body: unknown };
type Handler = { test: (url: string, method: string) => boolean; respond: (call: Call) => Response | Promise<Response> };

export const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

/** fetchをモックする。後から登録したhandlerが優先。呼び出し履歴(calls)を返す。 */
export function mockFetch(handlers: Handler[] = []) {
  const calls: Call[] = [];
  const all = [...handlers];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const call: Call = { url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    for (const h of [...all].reverse()) if (h.test(url, method)) return h.respond(call);
    return json({ detail: "not mocked" }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return { calls, on: (h: Handler) => { all.push(h); }, fn };
}

export const route = (method: string, prefix: string, respond: Handler["respond"]): Handler => ({
  test: (url, m) => m === method && url.split("?")[0] === prefix, respond,
});
export const get = (prefix: string, body: unknown | ((c: Call) => unknown), status = 200) => route("GET", prefix, (c) => json(typeof body === "function" ? (body as (c: Call) => unknown)(c) : body, status));

export function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

export function renderApp(path = "/") {
  return render(<MemoryRouter initialEntries={[path]}><App /><LocationProbe /></MemoryRouter>);
}

/** 標準のAPIモック: 3台のMonitor・空の履歴・既定のデータ保存設定。 */
export function standardMocks(extra: Handler[] = []) {
  const monitors = [monitor({ id: 2, display_name: "エネセン内ガスメータ用２" }), monitor({ id: 3, display_name: "エネセン内ガスメータ用１\t", current_value: "215836" }), monitor({ id: 4, display_name: "食堂前機械室内メータ用", current_value: "372414.3", inference: { engine: "cpp_onnx", model_id: "drum_production_v1.onnx" } as Monitor["inference"] })];
  return mockFetch([
    get("/api/monitors", { monitors }),
    get("/api/records", { items: [], total: 0, limit: 20, offset: 0 }),
    get("/api/system/data-storage/status", storageStatus),
    get("/api/system/data-storage", storageSettings),
    ...extra,
  ]);
}
