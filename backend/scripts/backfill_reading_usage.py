"""既存のreading_recordsへ、usageの新しい再計算ルール(信頼できる正式値)を限定的に適用する開発確認用バックフィル。

- 更新するのは派生値の previous_value / usage だけ(value・numeric_value・raw_*・validation_status・value_source・baseline_conflict・
  inference_at・画像パス・修正履歴・baseline履歴は一切変更しない)。
- 計算は本番と同じ is_trusted_record() / compute_usage()(reading_correction_service._recompute_usage経由)を再利用する(ロジックを複製しない)。
  今回と直前1時間の両方がtrustedなら usage = 今回 - 直前、どちらかがuntrustedならnull。修正済み(correction_count>0)はtrusted。
  未修正のcarried_forwardはuntrusted(usage=null のまま)。
- Monitor IDと日付(JST)を必ず指定する(全Monitor・全期間へは適用しない)。dry-runが既定で、--applyで更新する。
- 対象のDBは ARGUS_DATA_DIR(未設定ならリポジトリの data/)の argus.db。実行時に接続先を表示する。--apply の前に、SQLiteのバックアップを自動で作成する。

使い方(backendディレクトリで):
    py -m scripts.backfill_reading_usage --monitor-id 3 --date 2026-10-09           # dry-run
    py -m scripts.backfill_reading_usage --monitor-id 3 --date 2026-10-09 --apply   # バックアップ後に更新
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings as app_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models import Monitor, ReadingRecord  # noqa: E402
from app.services.reading_correction_service import _neighbor, _recompute_usage  # noqa: E402
from app.services.reading_record_service import is_trusted_record  # noqa: E402


def _backup(db_path: Path) -> Path:
    target_dir = db_path.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{db_path.stem}_{datetime.now():%Y%m%d_%H%M%S}_before_usage_backfill.db"
    source = sqlite3.connect(str(db_path))
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)  # WAL中でも整合したスナップショットを取れる
        finally:
            destination.close()
    finally:
        source.close()
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--monitor-id", type=int, required=True)
    parser.add_argument("--date", required=True, help="対象日(JST) YYYY-MM-DD")
    parser.add_argument("--apply", action="store_true", help="更新する(未指定ならdry-run)")
    args = parser.parse_args()
    datetime.strptime(args.date, "%Y-%m-%d")

    db_path = Path(app_settings.database_url.replace("sqlite:///", ""))
    print(f"DB: {db_path}")
    print(f"対象: monitor {args.monitor_id} / {args.date} (JST) / {'APPLY' if args.apply else 'dry-run'}")
    db = SessionLocal()
    monitor = db.get(Monitor, args.monitor_id)
    if monitor is None:
        print("Monitorが見つかりません")
        return 2
    records = list(db.scalars(select(ReadingRecord).where(ReadingRecord.monitor_id == args.monitor_id, ReadingRecord.hour_bucket.like(f"{args.date}T%"))
                              .order_by(ReadingRecord.hour_bucket)))
    print(f"対象件数: {len(records)}")
    plan = []
    for record in records:
        before_previous, before_usage = record.previous_value, record.usage
        previous = _neighbor(db, record, -1)
        trusted, previous_trusted = is_trusted_record(record), is_trusted_record(previous)
        after_usage = _recompute_usage(db, record, monitor.created_at)  # previous_valueも同時に設定される
        record.usage = after_usage  # 保存するのはprevious_valueとusageの派生値だけ
        after_previous = record.previous_value
        plan.append((record, trusted, previous_trusted, before_previous, after_previous, before_usage, after_usage))
    print("hour  id   value      trusted prev_trusted  previous_value(before→after)   usage(before→after)")
    changed = 0
    for record, trusted, previous_trusted, bp, ap, bu, au in plan:
        change = (bp != ap) or (bu != au)
        changed += change
        print(f"{record.hour_bucket[11:16]} {record.id:<4} {str(record.value):<10} {str(trusted):<7} {str(previous_trusted):<12} {str(bp):>10}→{str(ap):<10} {str(bu):>8}→{str(au):<8} {'*' if change else ''}")
    if not args.apply:
        db.rollback()  # dry-run: previous_valueの一時的な設定も含め、何も保存しない
        print(f"(dry-run) 更新対象 {changed} 件 / 変更なし {len(plan) - changed} 件。--apply で更新します")
        db.close()
        return 0

    backup = _backup(db_path)
    print(f"バックアップ: {backup}")
    success = failed = 0
    try:
        db.commit()  # previous_value/usage以外は変更していない(上でrecordに設定したのは派生値のみ)
        success = changed
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        failed = changed
        print(f"FAIL: {exc}")
    print(f"完了: 更新 {success} / スキップ(変更なし) {len(plan) - changed} / 失敗 {failed}")
    db.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
