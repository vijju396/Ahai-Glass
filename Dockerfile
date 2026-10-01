# The deployed image: one process, one origin, one URL.
#
# Stage 1 builds the React app. Stage 2 is the FastAPI runtime and serves that
# build itself (app/main.py `_mount_web_app`), so there is no second service,
# no CORS allowlist to keep in step with a hostname, and `VITE_API_BASE` stays
# at its `/api` default.
#
# The layout under /app mirrors the repository exactly — backend/, data/,
# runtime/, frontend/dist — because `app/core/config.py` derives every path
# from the backend package's own location. Moving a directory here would mean
# overriding a setting there.

# --- stage 1: the page ------------------------------------------------------
FROM node:20-slim AS web

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# --- stage 2: the application ----------------------------------------------
# 3.12, matching the development venv. Not a free choice: `xgboost-cpu==3.3.0`
# publishes no wheel below cp312 and pip refuses the pin outright on 3.11,
# which is how this was found. Resolved on 3.12 the whole set is wheels — and
# it resolves to the versions the suite was run against, scipy 1.17.1 against
# numpy 1.26.4 included, so the deployed stack is the tested stack.
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libgomp is XGBoost's OpenMP runtime; it is not in the slim base and the
# import fails without it. curl is for the container health probe.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
# The test-only packages are installed too. They are small next to TensorFlow,
# and leaving them in means the deployed image can run the suite it claims to
# pass rather than a different dependency set.
RUN pip install --no-cache-dir -r backend/requirements.txt

# `.dockerignore` keeps backend/.env out of this, and `deploy/env.azure` takes
# its place — the same settings with the OpenAI key removed. The key is a
# Container Apps secret injected at run time, so it exists in no image layer.
COPY backend/ backend/
COPY deploy/env.azure backend/.env
COPY --from=web /web/dist frontend/dist

# The data, and only the workspace's share of it: one training run, its panel,
# its fitted models, and the order durations cut to the deployment's branches.
# Built by `scripts/build_scoped_bundle.py`, which must be run before this —
# `deploy/bundle/` is generated, not tracked.
#
# 68 MB instead of 348 MB. What it leaves behind is a 81 MB panel over 68,675
# series no live run reads, six superseded monthly training runs, and four
# client workbooks that only ingestion opens (D-137).
#
# `BUNDLE.json` goes to the project root on purpose: it is what the health
# check reads to report the withheld files as a deliberate scope rather than
# as four files gone missing.
COPY deploy/bundle/runtime/ runtime/
COPY deploy/bundle/data/ data/
COPY deploy/bundle/BUNDLE.json ./BUNDLE.json

ENV AIS_ENVIRONMENT=azure \
    AIS_DEBUG=false \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

WORKDIR /app/backend
# One worker, deliberately. The job runner is in-process (CLAUDE.md), so a
# second worker would be a second scheduler racing the first over one SQLite
# file. `--reload` is absent for the same reason it is absent locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
