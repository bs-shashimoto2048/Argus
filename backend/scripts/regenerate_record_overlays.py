"""保存済みの元画像から、推論結果overlay画像だけを再生成する(開発中の目視確認用)。

対象: original画像があり、overlay画像が無いreading_record。
- 入力は記録に保存された元画像(現在のLive映像は使わない)。
- 推論は、対象Monitorの「現在の」推論設定(model/engine/ROI/前処理/confidence等)で行う。
  overlayの描画は、InferenceScheduler._infer_latest()の既存処理をそのまま再利用する(bbox描画を別実装しない)。
- 保存するファイル名は `*_overlay_regenerated.jpg`。これは「当時保存されたoverlay」ではなく、
  保存元画像を現在設定で再推論した確認画像であることを表す。
- DBは、対象recordの overlay_image_path だけを更新する(value/raw_value/usage/baseline等の計測値・修正履歴は一切変更しない)。
  すでにoverlay_image_pathがあるrecordは対象外(上書きしない)。元画像も変更しない。

使い方(backendディレクトリで。既定は件数確認のみ):
    py -m scripts.regenerate_record_overlays            # 対象件数の確認(dry-run)
    py -m scripts.regenerate_record_overlays --apply    # 生成して保存
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings as app_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.inference.registry import model_registry  # noqa: E402
from app.models import ReadingRecord  # noqa: E402
from app.services import monitor_service  # noqa: E402
from app.services.record_image_service import _write_atomic, resolve_image_path  # noqa: E402
from app.services.storage_settings_service import load_config  # noqa: E402
from runtime.inference_scheduler import InferenceScheduler  # noqa: E402

SUFFIX = "_overlay_regenerated.jpg"


class _StillBuffer:
    """1枚の保存済み画像を返すだけのframe buffer(InferenceSchedulerのbufferの代わり)。"""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def get(self):
        return self.data, None


def _target_path(original_relative: str) -> str:
    base = original_relative
    for tail in ("_original.jpg",):
        if base.endswith(tail):
            return base[: -len(tail)] + SUFFIX
    return base.rsplit(".", 1)[0] + SUFFIX


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="overlayを生成して保存する(未指定なら対象件数の確認のみ)")
    args = parser.parse_args()

    db = SessionLocal()
    config = load_config(db)
    records = list(db.scalars(select(ReadingRecord).where(ReadingRecord.original_image_path.is_not(None), ReadingRecord.original_image_path != "",
                                                           (ReadingRecord.overlay_image_path.is_(None)) | (ReadingRecord.overlay_image_path == "")).order_by(ReadingRecord.id)))
    print(f"対象(originalあり・overlayなし): {len(records)} 件 / 画像保存先: {config.image_root}")
    by_monitor: dict[int, int] = {}
    for record in records:
        by_monitor[record.monitor_id] = by_monitor.get(record.monitor_id, 0) + 1
    print("Monitor別:", by_monitor)
    if not args.apply:
        print("(dry-run) --apply を付けると生成します")
        return 0

    schedulers: dict[int, InferenceScheduler | None] = {}
    ok = failed = skipped = 0
    for record in records:
        label = f"record {record.id} (monitor {record.monitor_id})"
        try:
            source = resolve_image_path(config.image_root, record.original_image_path)
            if source is None or not source.exists():
                print(f"SKIP {label}: 元画像が見つかりません ({record.original_image_path})")
                skipped += 1
                continue
            data = source.read_bytes()
            if record.monitor_id not in schedulers:
                try:
                    monitor = monitor_service.get_monitor(db, record.monitor_id)
                    inference_settings = monitor_service._build_inference_settings(monitor.inference)
                except ValueError:
                    inference_settings = None
                # on_result/baselineは使わない(再推論の結果をDB・Runtimeへ反映しない)
                schedulers[record.monitor_id] = (InferenceScheduler(record.monitor_id, _StillBuffer(b""), inference_settings, model_registry, app_settings.data_dir / "models", lambda *_: None)
                                                 if inference_settings else None)
            scheduler = schedulers[record.monitor_id]
            if scheduler is None or scheduler.engine is None:
                print(f"SKIP {label}: Monitorの推論設定がありません")
                skipped += 1
                continue
            scheduler.buffer = _StillBuffer(data)
            scheduler.latest_overlay = None
            scheduler.latest_result = None
            scheduler._infer_latest()
            result = scheduler.latest_result
            if scheduler.latest_overlay is None or result is None or result.error:
                print(f"FAIL {label}: 再推論に失敗しました ({getattr(result, 'error', None)})")
                failed += 1
                continue
            target_relative = _target_path(record.original_image_path)
            target = resolve_image_path(config.image_root, target_relative)
            if target is None:
                print(f"FAIL {label}: 保存先パスが不正です")
                failed += 1
                continue
            _write_atomic(target, scheduler.latest_overlay)
            record.overlay_image_path = target_relative  # 変更するのはこの列だけ
            db.commit()
            print(f"OK   {label}: 再推論={result.value} (保存値 raw={record.raw_value} value={record.value}) -> {target_relative}")
            ok += 1
        except Exception as exc:  # 1件の失敗で全体を止めない
            db.rollback()
            print(f"FAIL {label}: {exc}")
            failed += 1
    for scheduler in schedulers.values():
        if scheduler is not None:
            scheduler.stop()
    print(f"完了: 対象 {len(records)} / 成功 {ok} / 失敗 {failed} / スキップ {skipped}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
