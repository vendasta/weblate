# -*- coding: utf-8 -*-
from weblate.auth.models import Group
from weblate.logger import LOGGER
from weblate.vendasta.constants import VENDASTA_DEVELOPERS


def set_permissions(strategy, backend, user, details, **kwargs):
    """Set permissions for new Vendasta users.

    All authenticated users get Viewers. Users whose SSO `roles` claim contains
    "developer" additionally get Vendasta Developers. Empty or unknown roles
    fall through to Viewers only — fail-closed default for least privilege.
    """
    LOGGER.info("details from api: %s", details)

    groups_to_add = [Group.objects.get(name="Viewers", internal=False)]

    if "developer" in details.get("roles", []):
        groups_to_add.append(Group.objects.get(name=VENDASTA_DEVELOPERS))

    user.groups.add(*[group for group in groups_to_add if group])
