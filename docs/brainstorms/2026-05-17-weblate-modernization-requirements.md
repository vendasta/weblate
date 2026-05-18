---
date: 2026-05-17
topic: weblate-modernization
---

# Weblate Modernization: Override Removal, Upgrade, and Demo Mirror

## Summary

Strip the partner-namespace override system from the Vendasta Weblate fork, replace it with a "nominated language collaborator" model, walk a no-skip Weblate 4.17 → 5.x upgrade, and stand up a persistent demo Weblate that mirrors prod and pairs with Lexicon's existing `demo` environment. Lexicon's API surface stays as-is; `partner_id` remains a required parameter for auth/identity reasons even after overlay routing is removed.

---

## Problem Frame

Vendasta's Weblate is a fork of upstream Weblate carrying ~460 lines of custom code in `weblate/vendasta/` to support a partner-specific language override system: each partner can have private translations for a language via codes like `fr~PARTNERX`, served downstream by Lexicon (which fetches both `fr` and `fr~PARTNERX` and merges the overlay).

The fork is currently pinned to Weblate 4.17 on Python 3.11; upstream is on the 5.x line. Past upgrade attempts have been difficult because the namespace-override code intersects with Weblate's auth model, language model, and view layer — exactly the areas where upstream churns most across major versions. Documented prior incidents reinforce that destructive operations against this system carry real risk.

Usage signal suggests the overrides matter less than the carrying cost implies: Lexicon already hard-codes a `PartnerCustomizationBlacklist` containing `VMF`, meaning at least one partner was explicitly opted out of the override mechanism because it was causing more pain than value. `GetSupportedLanguages` also filters `~`-containing codes from public listings, signaling these are already treated as internal artifacts rather than first-class languages.

The cost shape: every Weblate version bump compounds upgrade debt; the override system's per-partner complexity makes support and admin work harder; partners with brand-specific terminology needs have no clear voice in the shared translation outside the private-fork mechanism.

---

## Actors

- A1. **Vendasta developer/admin**: Operates the Weblate instance, runs the upgrade hops, manages the IAM-driven group assignments, and monitors Lexicon for downstream signal during the dynamic audit.
- A2. **Partner**: Vendasta customer whose products consume Lexicon-served translations. Today may have an `fr~PARTNERX` override; after the change, can nominate a collaborator in lieu of a private fork.
- A3. **Nominated language collaborator**: Person nominated by a partner who receives Translator rights on a specific shared language via a Weblate-side group membership added by a Weblate admin. SSO still handles their authentication; the group assignment itself is a manual admin step inside Weblate, not driven by IAM roles. Their edits affect every consumer of that language globally.
- A4. **Lexicon SDK caller (microservice)**: Any Vendasta microservice that calls Lexicon's `GetTranslation`/`GetTranslations` API with `partner_id`. Continues to pass `partner_id` after the change; the parameter remains required for auth/identity even though overlay routing is removed.

---

## Key Flows

- F1. **Dynamic audit ramp via Lexicon overlay-ignore flag**
  - **Trigger:** Vendasta developer enables the overlay-ignore flag for a specific partner in Lexicon.
  - **Actors:** A1, A2, A4
  - **Steps:** (1) Flag flips for partner P; (2) Lexicon stops merging `fr~P` overlay onto `fr` for any request bearing `partner_id=P`; (3) Soak window begins; (4) A1 monitors for partner support tickets or product-team escalations; (5) If signal arrives, flag flips back instantly and the override is treated as load-bearing; (6) If silent through the soak window, P is marked clean and added to a "safe to delete" list.
  - **Outcome:** Each partner is classified as either "overlay actually matters" (preserved for collaborator-conversion conversation) or "overlay was orphaned" (safe to delete from Weblate).
  - **Covered by:** R3, R4, R5

- F2. **Partner converts from override to nominated collaborator**
  - **Trigger:** Partner with a load-bearing override is contacted and chooses to nominate a collaborator.
  - **Actors:** A1, A2, A3
  - **Steps:** (1) Partner identifies a person from their org; (2) That person logs into Weblate once via SSO to establish an account; (3) A Weblate admin adds them to the relevant language-collaborator group inside Weblate's admin UI; (4) They review the existing partner override translations; (5) Edits that should apply globally are merged into the shared language; brand-specific terminology that does not fit globally is deliberately dropped (partner accepts the trade-off).
  - **Outcome:** Partner has voice in the shared language going forward; private override data is no longer needed.
  - **Covered by:** R6, R7, R8

- F3. **No-skip Weblate version upgrade hop**
  - **Trigger:** Override removal is complete in prod; A1 begins the upgrade walk in the demo mirror.
  - **Actors:** A1
  - **Steps:** (1) Demo is snapshot-current with prod data; (2) A1 walks one major version hop (e.g., 4.17 → 4.18) following upstream's documented upgrade procedure; (3) Smoke tests run: NotifyLexicon addon fires, SSO login works, translations save, Lexicon receives the webhook and serves the updated value; (4) If the hop fails, demo is restored from snapshot, the issue is debugged or escalated, and the hop is retried; (5) If the hop succeeds, the next hop begins.
  - **Outcome:** Demo reaches the current 5.x release with each hop validated; prod is then upgraded along the same path with confidence.
  - **Covered by:** R12, R13, R14

---

## Requirements

**Demo mirror**
- R1. A persistent Weblate demo instance exists that mirrors prod configuration (auth, addons, integrations) and is the target of Lexicon's existing `demo` environment.
- R2. The demo can be loaded with a recent snapshot of prod data on demand, so each upgrade hop is validated against realistic content rather than an empty database.

**Dynamic audit via Lexicon**
- R3. Lexicon supports an "ignore partner overlay" flag scoped per partner, ramped via configuration without requiring a deploy per flip (the existing `PartnerCustomizationBlacklist` pattern is the reference shape).
- R4. When the flag is set for partner P, `GetTranslation`/`GetTranslations` calls bearing `partner_id=P` return only the base language; cache keys are recomputed accordingly so a stale overlay cannot be served.
- R5. The flag can be flipped back instantly (rollback is a config change, not a deploy) if a partner reports an issue during the soak window.

**Override-to-collaborator conversion**
- R6. A Weblate-managed group exists for each shared language, scoped to that language and carrying the Translate role, so that adding a user to the group grants Translator rights on only that language across all components.
- R7. Collaborator group membership is managed entirely inside Weblate by an admin — no IAM role, no SSO claim, no change to the existing `set_permissions` flow. SSO continues to handle authentication only.
- R8. Edits made by a nominated collaborator apply to the shared language globally (no per-partner overlay); this is the deliberate replacement for the private namespace.

**Weblate fork cleanup**
- R9. After the dynamic audit confirms all partners are clean, all `fr~PARTNERX`-style language rows and associated components are deleted from Weblate.
- R10. The `weblate/vendasta/` namespace-override code is removed: the `new_namespaced_language` view, the `Partner Users` / `View Partner Languages` / `Translate Partner Languages` groups in `constants.py`, the namespace-group creation in `access.py`, and the partner-tier check in `aa_sdk.py`.
- R11. `NotifyLexicon` and `ApplyTranslationsFromHistory` addons are preserved (they are not part of the override system).

**Weblate upgrade**
- R12. The upgrade follows Weblate's no-skip-releases discipline: every major version between 4.17 and the current 5.x release is walked in sequence in the demo mirror before prod is touched.
- R13. Each hop is validated against the smoke-test surface from F3 (NotifyLexicon, SSO, save+webhook+serve roundtrip) before the next hop begins.
- R14. The Python runtime version is upgraded only as required by a given Weblate release (upstream's upgrade docs are the authority), not preemptively.

**Lexicon API surface**
- R15. `partner_id` remains a required parameter on Lexicon's `GetTranslation`, `GetTranslations`, and `InvalidateCache` APIs. After the cleanup, it no longer routes to a partner-specific overlay but it remains load-bearing for auth/identity (the `InvalidateCache` `AccessPartnerMarket` check is the existing precedent).
- R16. No coordinated SDK upgrade is required across consuming microservices; existing callers continue working unchanged.

---

## Acceptance Examples

- AE1. **Covers R3, R4, R5.** Given partner P has an `fr~P` overlay in Weblate and the overlay-ignore flag is OFF, when a microservice calls `GetTranslation(component, "fr", "P")`, Lexicon returns the merged result (base `fr` + `fr~P` overlay). When the flag is flipped ON for P, the next call returns only the base `fr` translation, and the cache key for the partner+language is recomputed so no stale overlay is served. Flipping the flag back OFF restores the merged result on the next call.

- AE2. **Covers R8.** Given a nominated collaborator C is assigned the `fr` language-collaborator role, when C edits the French translation of a key in any component, the change is visible to every microservice calling `GetTranslation(component, "fr", any_partner_id)` after the standard `NotifyLexicon` propagation, regardless of which partner the original nomination came from.

- AE3. **Covers R12, R13.** Given the demo mirror is on Weblate 4.17 with a recent prod snapshot, when A1 attempts to jump directly from 4.17 to 5.0 (skipping intermediate hops), the upgrade is rejected at the planning step. When A1 instead walks 4.17 → 4.18 with the F3 smoke-test surface passing, the next hop begins; the snapshot-restore-and-retry path is exercised at least once during the walk to validate the rollback procedure.

- AE4. **Covers R15.** Given a Lexicon SDK caller passes `partner_id=""` (empty), the API rejects the call with an auth error even after the override system is removed — `partner_id` remains required for identity, not just for overlay lookup.

---

## Success Criteria

- The Weblate fork is running the current upstream 5.x release and tracks future upstream major versions through documented hop walks rather than ad-hoc patching.
- Zero partner-namespaced (`*~*`) language rows remain in Weblate; the `weblate/vendasta/` package contains only addon and SSO code, no override-system code.
- Every partner that had a load-bearing override at the start of the project either (a) has a nominated collaborator with Translator rights on the relevant language, or (b) was contacted and accepted that the shared translation supersedes their previous brand-specific override.
- Lexicon's `GetTranslation`/`GetTranslations`/`InvalidateCache` API contract is unchanged from the consuming microservice's perspective; no downstream SDK or callsite changes were required.
- The demo Weblate is a permanent fixture used to validate every future upgrade hop before prod; it is not torn down after this project ends.
- The next person who attempts a Weblate version upgrade can follow F3 without reading this brainstorm.

---

## Scope Boundaries

- Lexicon SDK signature changes (Go, Python, TypeScript). `partner_id` stays required and load-bearing.
- Coordinated migration of every downstream microservice that passes `partner_id`. The API surface is preserved precisely to avoid this.
- Deprecating or rewriting Lexicon. Lexicon gets one targeted feature (overlay-ignore flag) and otherwise stays as-is.
- A v2 multi-tenant translation isolation system. The override mechanism was a flawed take on this need; we are not replacing it with a "better" version.
- New translation review/approval workflow tooling beyond what Weblate ships natively. If Weblate's built-in suggestion/review flow is insufficient for collaborator governance, that is a separate brainstorm.
- Backporting Vendasta fork patches upstream to weblate.org. The README mentions this as an aspiration; it is its own effort and not coupled to this project.
- Changes to the `NotifyLexicon` or `ApplyTranslationsFromHistory` addons, the SSO/IAM integration shape, or Weblate's translation file formats.
- Brand-preserving "soft override" mechanisms that try to give partners some private control without a full namespace fork. The intent is explicitly the opposite: no private forks of any shape.

---

## Key Decisions

- **Hybrid A+D sequencing**: Use Lexicon's overlay-ignore flag as the dynamic audit before any destructive Weblate work. Real-world signal beats static-analysis guesswork, and rollback is a config flip rather than a data restore. The `VMF` blacklist already proves this mechanism's shape works.
- **Nominated collaborators get full Translator rights, not Suggestor**: Suggestor-with-review would preserve implicit per-partner overrides through delayed merges and contradict the "no private forks" intent. Translator means changes go live for everyone immediately, matching the shared-language model.
- **Collaborator group membership managed inside Weblate, not in IAM**: SSO continues to handle authentication; per-language Translator rights are an admin action inside Weblate after the user has logged in once. Avoids IAM coordination and keeps the rollout self-contained inside the Weblate admin surface.
- **`partner_id` stays required on Lexicon API**: It remains load-bearing for auth and identity (precedent: `InvalidateCache`'s `AccessPartnerMarket` check). Removing it would force coordinated changes across every consuming microservice and weaken auth at the same time.
- **Persistent demo, not throwaway**: The cost amortizes across every future Weblate version bump. Weblate ships often; one-shot demos would have to be rebuilt every time.
- **Rigid cutover order**: Lexicon flag fully ramped → Weblate namespace data deleted → Weblate fork code stripped → upgrade walk begins. The upgrade does not start until the namespace code is gone — anything else carries the namespace hack through hops, which is the original "very hard to upgrade" problem.
- **No-skip upgrade discipline**: Follow upstream's documented per-version upgrade path (`https://docs.weblate.org/en/latest/admin/upgrade.html`). Skipping is not an option upstream supports and is the most common way Weblate upgrades fail.

---

## Dependencies / Assumptions

- Lexicon team's bandwidth to add and operate the overlay-ignore flag mechanism.
- A Weblate admin is available to manage collaborator group membership manually as partners nominate people. No IAM or SSO work is required for this.
- Static audit of `*~*` language rows in prod returns "very few" as expected; if the static audit reveals broad usage, the timeline for the dynamic-audit ramp extends correspondingly.
- Partner support channel is available and responsive for the conversion conversations in F2.
- Weblate's upstream upgrade documentation is the canonical reference for version-to-version steps; this doc does not duplicate it.
- Lexicon's `demo` environment is reachable from the new demo Weblate via the same `NotifyLexicon` webhook mechanism used today.

---

## Outstanding Questions

### Deferred to Planning

- [Affects R3, R4][Technical] Granularity of the Lexicon overlay-ignore flag: all-or-nothing per partner, or per-(partner, language). Answer depends on what the static audit finds — if every partner with an override only has one, per-partner is sufficient; otherwise per-(partner, language) earns its keep.
- [Affects R9][Technical] Is deleting `*~*` Language rows in Weblate a soft-delete or hard-delete? Cascade behavior across components, translations, change history, and stats needs to be confirmed against the Weblate data model.
- [Affects R3, R5][Technical] What is the existing config-flip mechanism for `PartnerCustomizationBlacklist`, and can it host the new overlay-ignore flag, or does the flag warrant its own mechanism (e.g., a Lexicon admin endpoint, a config file in VStore)?
- [Affects R12, R13][Needs research] What is the actual chain of major Weblate versions between 4.17 and current, and which hops are known to have breaking changes against the `NotifyLexicon` addon or the SSO backend? Upstream's release notes need to be walked.
- [Affects R10][Technical] Does removing the `Partner Users` group break any existing user assignments mid-flight? A migration that reassigns those users to the new collaborator groups (or to nothing) is needed before the code rip.
- [Affects R2][Technical] What is the prod-to-demo snapshot mechanism — DB dump + restore, anonymized export, or something else? Privacy and PII considerations apply.
- [Affects R1][Needs research] Does the existing `deploy_demo.json` config still work, or is the demo deployment configuration drift-broken? "Persistent staging mirror" assumes a working baseline.
