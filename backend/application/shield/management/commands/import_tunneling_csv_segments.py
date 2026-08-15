# -*- coding: utf-8 -*-
import csv
import io
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from application.shield.models import ProjectInfo, ShieldMachineBasicInfo, ShieldTunnelingData
from application.shield.views import (
    _average_tunneling_records,
    _build_tunneling_record,
    _extract_ring_no_from_filename,
    _safe_segment_count,
    _split_records_into_time_segments,
)


class Command(BaseCommand):
    help = "Import tunneling CSV data as fixed time-ordered segments per ring."

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True, help="CSV file path.")
        parser.add_argument("--project", required=True, help="Project id or project code.")
        parser.add_argument("--shield-machine", required=True, help="Shield machine database id.")
        parser.add_argument("--ring-no", default="", help="Ring number. Defaults to value parsed from filename.")
        parser.add_argument("--segment-count", type=int, default=10, help="Segments to create per ring. Default: 10.")
        parser.add_argument("--replace", action="store_true", help="Delete existing records for the same ring before import.")
        parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing to database.")

    def _load_csv_text(self, path):
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "gbk", "gb18030"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise CommandError("CSV encoding cannot be detected. Use UTF-8 or GBK.")

    def _project(self, value):
        query = ProjectInfo.objects.all()
        if str(value).isdigit():
            project = query.filter(id=value).first()
            if project:
                return project
        project = query.filter(project_id=value).first()
        if not project:
            raise CommandError(f"Project not found: {value}")
        return project

    def handle(self, *args, **options):
        path = Path(options["csv"])
        if not path.exists():
            raise CommandError(f"CSV file not found: {path}")

        project = self._project(options["project"])
        shield_machine = ShieldMachineBasicInfo.objects.filter(id=options["shield_machine"]).first()
        if not shield_machine:
            raise CommandError(f"Shield machine not found: {options['shield_machine']}")

        ring_no = options["ring_no"] or _extract_ring_no_from_filename(path.name)
        if not ring_no:
            raise CommandError("Ring number is required. Pass --ring-no or use a filename containing '第N环'.")
        segment_count = _safe_segment_count(options["segment_count"])

        rows = list(csv.DictReader(io.StringIO(self._load_csv_text(path))))
        records = []
        skipped = 0
        for row in rows:
            record = _build_tunneling_record(row, project.id, shield_machine.id, ring_no=str(ring_no))
            if record is None:
                skipped += 1
                continue
            records.append(record)

        if not records:
            raise CommandError("No valid tunneling records found in CSV.")

        segments = _split_records_into_time_segments(records, segment_count, lambda item: item.record_time)
        averaged = [
            _average_tunneling_records(
                segment,
                import_source=str(path),
                segment_index=segment_index,
                segment_count=segment_count,
            )
            for segment_index, segment in segments
        ]

        self.stdout.write(
            f"Parsed {len(rows)} row(s), valid {len(records)}, skipped {skipped}, "
            f"ring {ring_no}, segments {len(averaged)}."
        )
        for item in averaged:
            meta = item.raw_parameters or {}
            self.stdout.write(
                f"  segment {meta.get('segment_index')}/{meta.get('segment_count')}: "
                f"{meta.get('start_time')} -> {meta.get('end_time')}, "
                f"points={item.point_count}, thrust={item.thrust}, torque={item.torque}, "
                f"speed={item.cutterhead_speed}, penetration={item.penetration}"
            )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run only. Database was not changed."))
            return

        if options["replace"]:
            deleted, _ = ShieldTunnelingData.objects.filter(
                project=project,
                shield_machine=shield_machine,
                ring_no=str(ring_no),
            ).delete()
        else:
            deleted = 0

        ShieldTunnelingData.objects.bulk_create(averaged, batch_size=1000)
        self.stdout.write(self.style.SUCCESS(
            f"Imported {len(averaged)} tunneling segment record(s); deleted {deleted} old record(s)."
        ))
