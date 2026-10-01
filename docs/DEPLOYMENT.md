# Deployment

The application runs on Azure as **one container**: FastAPI serves the API and
the built React page from the same origin, so there is a single URL and no CORS
configuration to keep in step with a hostname.

This mirrors what the sibling demos in the same subscription do
(`ca-meriton-demo`, `ca-sodexo-demo`): Container Apps, images in a Basic ACR,
everything in `centralindia`.

## What is deployed

| Resource | Name | Notes |
| --- | --- | --- |
| Resource group | `rg-aisglass-demo-ci` | `centralindia` |
| Container registry | `acraisglassdemoci` | Basic, admin user enabled |
| Container Apps environment | `cae-aisglass-demo` | own Log Analytics workspace |
| Container app | `ca-aisglass-demo` | 2 vCPU / 4 GiB, external ingress on 8000 |

## The image carries the workspace's data, and only that

The deployment reports on one workspace — BENGALURU and DELHI-1, 136 SKUs — so
that is what ships. `scripts/build_scoped_bundle.py` writes `deploy/bundle/`:
**67.9 MB instead of 348 MB** (D-137).

- `runtime/db/ais.db` — the live training run, its champions, forecasts and
  recommendations. A `sqlite3 .backup` of the live file rather than a byte copy,
  because the live one has a write-ahead log attached, then pruned to that one
  run and vacuumed: 81.3 MB to 52.1 MB.
- `runtime/storage/` — that run's panel, its preprocessing output and its
  fitted model artefacts. 113 MB to 14.8 MB.
- `runtime/cache/lead_time/lines.parquet` — the parsed order durations cut to
  the workspace branches, 69,353 of 775,628 lines. 0.11 MB in place of a 67 MB
  workbook.
- `data/source/Location Master.csv` — 24 KB, shipped whole because the Ordered
  vs Dispatched Time page compares observed durations against the stated
  averages in it.
- `BUNDLE.json` at the project root — what was kept, what was withheld, and
  the path rewrite. `/api/health` reads it.

**Four client workbooks are not deployed**, so ingestion and preprocessing are
unavailable there. The health check says that by name rather than reporting
four files mysteriously missing. **The deployed run history is one run, not
seven**; the six dropped are superseded monthly runs whose forecasts cannot be
read at the current weekly grain anyway (D-105).

### Stored paths are rewritten to `/app`

The database records artefact locations as absolute paths on the machine that
trained the run. Left alone, the deployment returns 500 on any page that opens
the panel. The bundle script rewrites the development project root to `/app`
across every text column of every table and asserts that none survives; the
columns it changed are listed in `BUNDLE.json` under `stored_paths`.

### The build context is an allowlist, not `.dockerignore`

`az acr build` packs the context with its own archiver and **does not honor
`.dockerignore`** — a listed `frontend/node_modules/` still uploaded 15,956
entries, 309 MB against a 68 MB bundle. `scripts/stage_build_context.py` copies
the named trees and files into `deploy/context/` instead: 71.0 MB, 352 files,
and the upload fell from roughly fourteen minutes to one.

`deploy/bundle/`, `deploy/context/` and `deploy/env.azure` are generated and
gitignored. Build them before every image build.

## The OpenAI key is never in the image

`backend/.env` is in `.dockerignore`. `deploy/env.azure` takes its place — the
same settings with `OPENAI_API_KEY` removed — and the key is injected at run
time as a Container Apps secret. Anything copied into an image stays in that
image's layers whether or not a later line deletes it, so "copy it then remove
it" is not a fix.

Regenerate the env file whenever `backend/.env` changes:

```bash
python scripts/make_azure_env.py
```

## Deploying a new version

```bash
python scripts/make_azure_env.py
python scripts/build_scoped_bundle.py
python scripts/stage_build_context.py
az acr build --registry acraisglassdemoci --image ais-glass-demo:v3 --platform linux/amd64 --file Dockerfile deploy/context
az containerapp update -n ca-aisglass-demo -g rg-aisglass-demo-ci --image acraisglassdemoci.azurecr.io/ais-glass-demo:v3
```

Build from `deploy/context`, never from `.` — the repository root carries the
virtualenv, `node_modules` and the unscoped data, and the ignore file will not
stop them.

`az acr build` builds in Azure on amd64 hardware. Building locally on an Apple
Silicon machine would mean either an emulated amd64 build or pushing a
multi-gigabyte image over a home connection; neither is worth it.

Tag every build. `latest` alone gives Container Apps nothing to tell one
revision from the next, and a rollback then has no target.

## Things that are true of this deployment and worth stating

- **The database is in the container, so writes do not survive a restart.**
  Starting a training run from the deployed page works, and its results are
  gone when the revision restarts or a new image is deployed. The shipped run,
  its champions and its forecasts come back every time, because they are in the
  image. Making a run durable means mounting Azure Files at `/app/runtime` and
  is a separate decision.
- **Training cannot be started from the deployed page**, because the source
  workbooks it would ingest are not there. Every page reads the bundled run.
- **Ingress is external and there is no authentication.** The URL is
  unlisted, not protected, and the pages show real client demand data. The
  sibling demos are configured the same way. If that is not wanted, Container
  Apps can put Microsoft Entra in front of it without touching the image.
- **One worker, deliberately.** The job runner is in-process, so a second
  worker would be a second scheduler racing the first over one SQLite file.
- **`minReplicas` is 1, not 0.** The image is large and TensorFlow's import is
  slow; scaling to zero would make the first visit after an idle period look
  broken. The sibling Meriton app scales to zero and pays that cost.
