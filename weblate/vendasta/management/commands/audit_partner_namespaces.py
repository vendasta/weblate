# -*- coding: utf-8 -*-
"""Audit partner-namespaced languages in the Weblate database.

Produces a CSV inventory of every `*~*` Language row with usage signal:
translation count, distinct components, last translator activity, recent
activity within a configurable window, and matching namespace-Group user
count. Run before removing the partner-override system to identify any
partners with active customizations who need outreach before their
`fr~PARTNERX` data is deleted.

Usage in prod (via the admin shell at /admin/shell/ or `kubectl exec`):

    python manage.py audit_partner_namespaces > /tmp/partner-namespaces.csv

Optional flags:

    --output PATH        Write CSV to PATH instead of stdout
    --recent-days N      Window for recent-activity count (default 90)
"""
import csv
import sys
from datetime import timedelta

from django.utils import timezone

from weblate.auth.models import Group
from weblate.lang.models import Language
from weblate.trans.models import Change, Translation
from weblate.utils.management.base import BaseCommand
from weblate.vendasta.constants import NAMESPACE_SEPARATOR


class Command(BaseCommand):
    help = "Audit partner-namespaced (`*~*`) Language usage in the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=None,
            help="Write CSV to this path instead of stdout",
        )
        parser.add_argument(
            "--recent-days",
            type=int,
            default=90,
            help="Window for the recent-activity column (default: 90)",
        )

    def handle(self, *args, **options):
        recent_days = options["recent_days"]
        recent_cutoff = timezone.now() - timedelta(days=recent_days)

        languages = Language.objects.filter(
            code__contains=NAMESPACE_SEPARATOR
        ).order_by("code")

        output_path = options["output"]
        output_stream = open(output_path, "w") if output_path else sys.stdout
        try:
            writer = csv.writer(output_stream)
            writer.writerow(
                [
                    "language_id",
                    "language_code",
                    "partner_namespace",
                    "translation_count",
                    "component_count",
                    "last_change_timestamp",
                    f"changes_last_{recent_days}d",
                    "namespace_group_user_count",
                ]
            )

            row_count = 0
            for language in languages:
                _, _, namespace = language.code.partition(NAMESPACE_SEPARATOR)
                translations = Translation.objects.filter(language=language)
                translation_count = translations.count()
                component_count = (
                    translations.values("component_id").distinct().count()
                )

                language_changes = Change.objects.filter(language=language)
                last_change = (
                    language_changes.order_by("-timestamp")
                    .values_list("timestamp", flat=True)
                    .first()
                )
                recent_changes = language_changes.filter(
                    timestamp__gte=recent_cutoff
                ).count()

                namespace_group = Group.objects.filter(name=namespace).first()
                namespace_group_user_count = (
                    namespace_group.user_set.count() if namespace_group else 0
                )

                writer.writerow(
                    [
                        language.id,
                        language.code,
                        namespace,
                        translation_count,
                        component_count,
                        last_change.isoformat() if last_change else "",
                        recent_changes,
                        namespace_group_user_count,
                    ]
                )
                row_count += 1

            if output_path:
                self.stderr.write(
                    f"Wrote {row_count} partner-namespaced language rows to {output_path}"
                )
            else:
                self.stderr.write(
                    f"Wrote {row_count} partner-namespaced language rows to stdout"
                )
        finally:
            if output_path:
                output_stream.close()
