from pydantic import BaseModel


class CsvExportSettingsInput(BaseModel):
    """PUT /api/system/csv-export のリクエストボディ(Issue #17)。

    output_folderはBrowser File System API等を使わず、パス文字列の直接入力+
    Backend側validation(実際の出力時にフォルダの存在/書込可否をチェック)で扱う。
    Windowsローカルパス/UNCパスをそのまま受け付ける(ここでは書式チェックのみ)。
    """
    enabled: bool
    output_folder: str | None = None


class CsvExportSettingsResponse(BaseModel):
    enabled: bool
    output_folder: str | None = None


class CsvExportMonitorStatus(BaseModel):
    monitor_id: int
    display_name: str
    last_exported_hour: str | None = None
    last_exported_at: str | None = None
    last_error: str | None = None


class CsvExportStatusResponse(BaseModel):
    enabled: bool
    output_folder: str | None = None
    worker_running: bool
    last_tick_at: str | None = None
    # テスト出力(本番のdedup/最終出力日時とは無関係、argus_hourly_readings_test.csvへの
    # 追記)を最後に実行した時刻。UI側の確認用のみで、本番の状態には一切影響しない。
    last_test_run_at: str | None = None
    monitors: list[CsvExportMonitorStatus]


class CsvExportRunOutcome(BaseModel):
    monitor_id: int
    display_name: str
    status: str
    detail: str | None = None


class CsvExportRunResponse(BaseModel):
    outcomes: list[CsvExportRunOutcome]
