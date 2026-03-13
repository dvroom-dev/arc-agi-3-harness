# ARC-AGI Harness UI

Operator UI for launching harness runs, monitoring live progress, and inspecting run artifacts plus `super` activity.

## Local Run

From [ui/package.json](/home/dvroom/projs/arc-agi-harness/ui/package.json):

```bash
npm run dev
```

The UI runs on `http://0.0.0.0:3456`.

## Scripts

```bash
npm run dev
npm run build
npm run start
npm run lint
```

## Notes

- The left and middle panes are harness-specific.
- The right pane is mostly a `super` activity inspector, with the logs tab intentionally mixing harness logs and `super` raw events.
- UI code reads real harness artifacts from the repo root via App Router API routes under `ui/src/app/api`.
