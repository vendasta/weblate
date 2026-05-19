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
# One-time: drop your local env vars and ports in the override file
cp dev-docker/docker-compose.override.yml.example dev-docker/docker-compose.override.yml  # if example exists, otherwise edit directly
# The override file is gitignored. It sets WEBLATE_ADMIN_PASSWORD, SMTP creds, and exposes port 80.

# Build the prod image and tag it for the dev compose
docker build -t weblate-dev:latest -f mscli-Dockerfile .

# Boot Postgres-15 + Redis-7 + our image
cd dev-docker && docker compose up
```

Then open `http://localhost/` and log in with the credentials from your override file.

What `start` runs on boot (you'll see these in the container log):
1. `weblate migrate` — applies schema migrations
2. `weblate createadmin` — creates/updates the admin user from env vars
3. `weblate collectstatic --noinput --clear`
4. `weblate compress --force --traceback`
5. `weblate check --deploy || true` — non-blocking deployment readiness check
6. Launches nginx + supervisord (gunicorn + celery)

If migrations or a settings rewrite breaks, you'll see it before nginx comes up. SSO won't work locally without a real OIDC provider — log in with the local admin instead.

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

Each hop = a `merge-weblate-X.Y.Z` branch off `vendasta`, `git merge weblate-X.Y.Z`, resolve conflicts, PR, deploy.

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
