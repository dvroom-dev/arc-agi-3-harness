# ARC-AGI Harness UI: Local Agent Rules

These rules apply when the current working directory is `ui/`.

## Purpose

The UI is an operator surface for launching runs, inspecting live progress, reviewing artifacts, and comparing scores. It must reflect real harness state without weakening benchmark integrity or inventing backend behavior in the browser.

## Architecture

- The app is a Next.js App Router project under `ui/src/app`.
- API routes in `ui/src/app/api/**` are the bridge from the browser to harness artifacts in the repo root.
- Shared data contracts belong in `ui/src/lib/**`.
- Visual components belong in `ui/src/components/**`.
- Local score computation is backend-owned. Keep canonical scoring logic in Python or server helpers, not duplicated across multiple client components.

## UI Rules

- Prefer server-side derivation for run params, run state, scores, file trees, and trace mappings.
- If a value is inferred rather than directly recorded, label it clearly in the UI or code comments.
- Keep empty states explicit. A missing scorecard, trace, or log is different from a zero score or an empty transcript.
- One-click launch flows must reuse persisted recent params without silently reusing stale run ids or session names.
- Treat tooltip content as an inspection surface for real run metadata, not a place for guessed summaries.
- Avoid hidden coupling between tabs. Switching runs should reset per-run component state cleanly.

## Validation

- Run `npm run lint` in `ui/` after UI changes.
- If server routes depend on Python helpers or harness artifacts, also run the relevant repo-root tests before committing.
- Do not commit `ui/.next`, `ui/node_modules`, or other generated assets.

## Design And UX

- Preserve the established UI language unless the task is an intentional redesign.
- Desktop and mobile both matter. Check narrow viewports for launcher, sidebar, and dashboard overflow regressions.
- Live views should reflect polling/refresh behavior honestly; do not imply live updates when the page requires manual reloads.
