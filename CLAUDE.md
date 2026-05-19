# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Vendasta fork of [Weblate](https://github.com/WeblateOrg/weblate). The fork carries a handful of customizations on top of an upstream Weblate source tree (the full `weblate/` package is vendored). Upstream is tracked via the `upstream` git remote; `vendasta` is the deployable branch.

## Vendasta customizations

Everything else is upstream. The only meaningful Vendasta surface:

- `weblate/vendasta/` — Vendasta-specific package
  - `auth.py` — `VendastaOpenIdConnect` SSO backend
  - `access.py` — `set_permissions` social-auth pipeline step (sets group membership from the `roles` SSO claim)
  - `addons/notify_lexicon.py` — `NotifyLexicon` addon that pings Lexicon's webhook on translation changes
  - `scripts/apply_translations_from_history.py` — `ApplyTranslationsFromHistory` addon
- Wired into `weblate/settings_docker.py` at: `AUTHENTICATION_BACKENDS`, `SOCIAL_AUTH_PIPELINE` (last step), `WEBLATE_ADDONS`
- `mscli-Dockerfile` — the production image (NOT upstream's Dockerfile)
- `microservice.yaml`, `deploy_prod.json`, `deploy_demo.json` — Mission Control deploy config
- `start` — container entrypoint; runs `migrate → collectstatic → compress → check --deploy` at boot

## Local development

The dev workflow builds our production image (`mscli-Dockerfile`) so what you test locally matches what ships:

```bash
# One-time: write the local env file (gitignored). UID 1000 and GID 0 match
# how the image lays out perms; mismatched IDs make supervisord fail silently.
cat > dev-docker/.env <<EOF
USER_ID=1000
GROUP_ID=0
DOCKER_PYTHON=3.11
WEBLATE_HOST=127.0.0.1:8080
EOF

# One-time: drop your local env vars and ports in dev-docker/docker-compose.override.yml
# (gitignored). At minimum it should set:
#   user: "1000:0"        — keep the image's UID, not your host UID
#   volumes: !reset []    — don't overlay your source on the baked-in install
#   ports: ["8080:8080"]  — port 80 needs root on macOS; use 8080
#   environment: WEBLATE_ADMIN_PASSWORD, WEBLATE_ADMIN_EMAIL, WEBLATE_SITE_DOMAIN=localhost, WEBLATE_HOST=localhost

# Build the prod image and tag it for the dev compose
docker build -t weblate-dev:latest -f mscli-Dockerfile .

# Boot Postgres-15 + Redis-7 + our image
cd dev-docker && docker compose up
```

Then open `http://127.0.0.1:8080/` and log in with the credentials from your override file.

What `start` runs on boot (you'll see these in the container log):
1. `weblate migrate` — applies schema migrations
2. `weblate createadmin` — creates/updates the admin user from env vars
3. `weblate collectstatic --noinput --clear`
4. `weblate compress --force --traceback`
5. `weblate check --deploy || true` — non-blocking deployment readiness check
6. Launches nginx + supervisord (gunicorn + 6 celery workers + nginx)

If migrations or a settings rewrite breaks, you'll see it before nginx comes up. The `check --deploy` step is allowed to exit non-zero (SMTP timeout, DEBUG=True etc. are normal in dev). SSO won't work locally without a real OIDC provider — log in with the local admin instead.

### Why the user/UID dance

The image creates a `weblate` user (uid 1000) in the `root` group and `chgrp -R 0 / chmod 770` the dirs supervisord needs (`/run`, `/var/log/nginx`, `/app/data`, `/app/cache`). The upstream dev compose at `dev-docker/docker-compose.yml` defaults to `user: $USER_ID:$GROUP_ID` with tmpfs mounts owned by the same IDs — designed for upstream's `FROM weblate/weblate:bleeding` image, which expects to run as your host UID. Our image doesn't, so we override `user: "1000:0"` and set `USER_ID=1000/GROUP_ID=0` in `.env` so tmpfs ownership matches.

## Production deploy

Deploy is gitops-driven. After merging code here:

1. CI builds a new image: `gcr.io/repcore-prod/weblate:<sha>`
2. Open a PR in `vendasta/gitops` bumping the image tag in:
   - `weblate/demo/deployment.yaml` (line ~152)
   - `weblate/prod/deployment.yaml` (line ~172)
3. ArgoCD picks up the gitops merge and rolls out

Demo and prod use the same image SHA. Stagger demo-first soak if the change is risky.

## Upgrade discipline

Upstream Weblate has a mandatory no-skip upgrade ladder. From any 4.x:
- 4.x → 5.0.2 (first mandatory stop)
- 5.0.2 → 5.10.4 (second mandatory stop)
- 5.10.4 → latest

Each hop has **two source repos** to cross-reference:
- [WeblateOrg/weblate](https://github.com/WeblateOrg/weblate) — Python source. We fork it; merge `weblate-X.Y.Z` tag into a `merge-weblate-X.Y.Z` branch.
- [WeblateOrg/docker](https://github.com/WeblateOrg/docker) — the upstream Dockerfile. We forked it once into `mscli-Dockerfile` and haven't re-synced. For each hop, diff against `WeblateOrg/docker` at the closest tag (e.g., `5.0.2.2`) and mirror **necessary** changes — apt deps, COPY list, pip flags — into `mscli-Dockerfile`. Do not adopt upstream's `pip install "Weblate==$VERSION"` from PyPI; we install from our local fork (`pip install -e /usr/src`).

Historical pattern (e.g., PR #928 merged 4.17). See `docs/plans/2026-05-17-001-refactor-weblate-modernization-plan.md` (on `docs/weblate-modernization-plan` branch) for the in-progress 5.0.2 → 5.10.4 → 2026.5 plan.

## Production database access

Read-only access for debugging:

```bash
# In one shell — tunnel the Cloud SQL instance
cloud-sql-proxy --address 127.0.0.1 --port 5432 repcore-prod:us-central1:weblate

# In another — connect (password is in microservice.yaml; never paste it)
/opt/homebrew/opt/libpq/bin/psql -h 127.0.0.1 -U weblate weblate
```

Demo Cloud SQL: `repcore-prod:us-central1:weblate-demo` (same workflow, different instance).

## Commit message style

Match the existing pattern: Conventional Commits style (`feat(scope):`, `fix(scope):`, `refactor:`, `chore:`). Co-author trailers are common.

## Things to NOT touch

- Upstream `weblate/` source — leave it as upstream wrote it unless a customization is genuinely needed in Vendasta land. Carry as little fork delta as possible to keep upgrade hops manageable.
- `setup.py`, `pyproject.toml` — upstream's. Don't fork.
- The hotfix patch mechanism (`*.patch` files applied via `find ... | xargs patch` in the Dockerfile) — exists for upstream pin pain, not for our customizations.
