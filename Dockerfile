# Self-contained image: FalkorDB + the API + the built dashboard in one container.
# The graph is rebuilt from the synthetic company on every start, so no volume is needed
# (a restart also resets the public demo).

# 1. the React dashboard
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# 2. FalkorDB (same version CI tests against) + Python app
FROM falkordb/falkordb:v4.22.1
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=web /web/dist ./web/dist

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    FALKORDB_HOST=127.0.0.1 \
    FALKORDB_PORT=6379 \
    PORT=8000

EXPOSE 8000
ENTRYPOINT []
CMD ["sh", "scripts/start.sh"]
