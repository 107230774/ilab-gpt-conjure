# Yuanshu Image Playground Runbook

Last updated: 2026-06-26 11:45 CST

This file is the project-local source of truth for Yuanshu online image playground development, release, deployment, rollback, and production status. Future work in this repository should read this file first instead of depending on Sub2API-side deployment notes.

## Scope

This repository, `/Users/yijiewang/sub2api-src/ilab-gpt-conjure`, provides the customized ilab WebUI service embedded by Yuanshu as the online image playground iframe.

The Yuanshu main site and image billing gateway live in the separate Sub2API service. Ordinary changes in this repository should deploy only the target-side `yuanshu-image-playground` container unless the change explicitly requires Sub2API gateway, account, billing, usage log, migration, or frontend shell changes.

## Current Production State

Public entry:

- User console page: `https://yuans.vip/image-playground-console`
- Embedded playground page: `https://yuans.vip/image-playground/`
- Playground ilab API prefix: `https://yuans.vip/image-playground/api/`
- Image gateway prefix handled by Sub2API: `https://yuans.vip/image-playground/api/v1/images/`

Hosts:

- `yuan` / `173.242.119.18`: public Nginx entry, Yuanshu main site, Sub2API gateway, PostgreSQL, Redis, and the active `yuanshu-image-playground` container.
- `target` / `23.95.10.133`: previous backend/backup host. Keep its old `yuanshu-image-playground` container and data for rollback during the migration observation window.
- Local SSH config reaches `target` through `yuan`.

Nginx routing on `yuan`:

- `/image-playground/api/v1/images/` -> local Sub2API on `127.0.0.1:8080`.
- `/image-playground/api/` -> local ilab service on `127.0.0.1:18080`.
- `/image-playground/static/` -> local ilab service on `127.0.0.1:18080/static/`, with Nginx gzip and static cache.
- `/image-playground/` -> local ilab page service on `127.0.0.1:18080`.

Active yuan image service:

- Container name: `yuanshu-image-playground`
- Runtime image: `yuanshu-image-playground:0.1.1-ilab-yuanshu-quality-medium-cachebump-20260626`
- Image ID: `sha256:e768a7a1d07890d6ecb86e7363b814f853acec563e2f4e6ec84283a387be5010`
- Host port: `127.0.0.1:18080` -> container port `8787`
- Persistent data: `/opt/yuanshu-image-playground/ilab-output` mounted at `/app/output`
- Backup root: `/opt/yuanshu-image-playground/backups`

Current rollback anchor:

- Old target container is intentionally still running during the 24-hour observation window after the 2026-06-26 migration.
- Previous yuan image before the quality hotfix: `yuanshu-image-playground:0.1.1-ilab-yuanshu-preview-loading-20260625`.
- Inspect backup before final quality hotfix cutover: `/opt/yuanshu-image-playground/backups/yuanshu-image-playground-before-quality-medium-cachebump-20260626-113846.json`.
- Intermediate inspect backup before first quality hotfix cutover: `/opt/yuanshu-image-playground/backups/yuanshu-image-playground-before-quality-medium-20260626-113545.json`.
- Nginx config backup before migration: `/etc/nginx/conf.d/sub2api.conf.bak-image-migrate-to-yuan-20260626-103450`.
- Static cache config backup before migration: `/etc/nginx/conf.d/00-yuanshu-image-static-cache.conf.bak-image-migrate-to-yuan-20260626-103450`.

Important Sub2API boundary:

- Do not deploy the Yuanshu main app to `target`.
- Do not rebuild or restart Sub2API, PostgreSQL, or Redis for ordinary ilab WebUI changes.
- Do not change account pool, billing, usage logs, image gateway, or database migrations from this repository.

Current image gateway group configuration:

- User-facing image key `image2-key` / key id `22` is bound to group `13` (`图像生成｜生图分组`).
- Group `13` must have at least two active OpenAI-compatible image accounts so a temporary upstream 403 on one account does not take the whole playground down.
- As of 2026-06-26 12:40 CST, group `13` contains:
  - Account `96` / `gloryCode生图1`, priority `1`, upstream `https://ai.dearglory.cn/v1`.
  - Account `95` / `glorycode文生图2（codesonline）`, priority `2`, upstream `https://image.codesonline.dev/v1`.
- Do not leave key id `22` pointing at a group with only one image account. If account `96` receives `OpenAI 403 temporary cooldown`, group `13` needs account `95` or another healthy image account for failover.
- Group `6` (`图像生成分组｜支持在线生图功能｜image2 稳定生图`) historically contained account `95`; do not assume users bound to group `13` can use group `6` accounts unless `account_groups` also maps those accounts into group `13`.

## Project Development

Always start from a clean understanding of the local worktree:

```bash
rtk git status --short --branch
rtk git diff --stat
```

Frontend source files live under:

- `codex_image/webui/frontend/src/`
- generated static assets under `codex_image/webui/static/`

For TypeScript or CSS changes, generated static assets must be committed with the source changes.

Primary validation:

```bash
rtk npm run check:webui
rtk zsh -lc 'python3 -m py_compile $(/usr/bin/find codex_image -name "*.py" -type f)'
```

`npm run check:webui` runs:

- `build:webui:css`
- `typecheck:webui`
- `build:webui`

For user-facing UI changes, check the generated bundle for expected strings or CSS selectors when a browser smoke test is not available:

```bash
rtk rg -n "expected-string|expected-class" codex_image/webui/static/app.js codex_image/webui/static/history.js codex_image/webui/static/styles.css
```

## Release Naming

Use target image names in this shape:

```text
yuanshu-image-playground:0.1.1-ilab-yuanshu-<short-change-name>-YYYYMMDD
```

Examples:

- `yuanshu-image-playground:0.1.1-ilab-yuanshu-preview-loading-20260625`
- `yuanshu-image-playground:0.1.1-ilab-yuanshu-history-return-layout-20260625`

Use build directories in the matching target path:

```text
/opt/yuanshu-image-playground/builds/0.1.1-ilab-yuanshu-<short-change-name>-YYYYMMDD
```

Use rollback inspect backups in:

```text
/opt/yuanshu-image-playground/backups/yuanshu-image-playground-before-<short-change-name>-YYYYMMDD-HHMM.json
```

## Local Source Package

After local validation, package the exact committed source state with `git archive`. This avoids shipping `.git`, `node_modules`, `output`, local data, and other machine-only files.

```bash
COMMIT="$(rtk git rev-parse --short HEAD)"
SLUG="preview-loading"
PKG="/tmp/ilab-gpt-conjure-${SLUG}-${COMMIT}.tgz"
WORK="/tmp/ilab-deploy-${COMMIT}"

rtk rm -rf "$WORK"
rtk mkdir -p "$WORK"
rtk git archive --format=tar HEAD | tar -x -C "$WORK"
rtk tar -czf "$PKG" -C "$WORK" .
rtk shasum -a 256 "$PKG"
rtk scp "$PKG" target:"$PKG"
```

Known harmless warning during Docker build:

- `tar: Ignoring unknown extended header keyword 'LIBARCHIVE.xattr.com.apple.provenance'`

This comes from macOS archive metadata and did not block the 2026-06-25 deployment. Prefer cleaner tar flags later if this gets noisy, but do not treat it as a production failure by itself.

## Runtime Dockerfile

The target runtime image is intentionally simple: Python slim, ilab source, WebUI requirements, uvicorn on port `8787`.

Create the target build directory and Dockerfile:

```bash
SLUG="preview-loading"
TAG="yuanshu-image-playground:0.1.1-ilab-yuanshu-${SLUG}-20260625"
BUILD="/opt/yuanshu-image-playground/builds/0.1.1-ilab-yuanshu-${SLUG}-20260625"
PKG="/tmp/ilab-gpt-conjure-${SLUG}-3cb5a0d.tgz"

rtk ssh target "set -e; rm -rf '$BUILD'; mkdir -p '$BUILD'"
rtk scp "$PKG" target:"$BUILD/source.tgz"
```

Dockerfile contents:

```dockerfile
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ILAB_CONJURE_DATA_DIR=/app/output \
    YUANSHU_IMAGE_PLAYGROUND_PUBLIC_MODE=true \
    YUANSHU_IMAGE_PLAYGROUND_API_BASE=https://yuans.vip/image-playground/api/v1 \
    YUANSHU_IMAGE_PLAYGROUND_PATH_PREFIX=/image-playground
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
COPY source.tgz /tmp/source.tgz
RUN tar -xzf /tmp/source.tgz -C /app && rm -f /tmp/source.tgz && python -m pip install --no-cache-dir -r requirements-webui.txt
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 CMD curl -fsS http://127.0.0.1:8787/ >/dev/null || exit 1
CMD ["python", "-m", "uvicorn", "codex_image.webui.app:app", "--host", "0.0.0.0", "--port", "8787", "--no-access-log"]
```

Build on `target`:

```bash
rtk ssh target "set -euo pipefail; cd '$BUILD'; sha256sum source.tgz; docker build -t '$TAG' .; docker image inspect '$TAG' --format 'image={{.Id}} created={{.Created}}'"
```

Do not run Node or TypeScript builds on the VPS.

## Canary Deploy

Use a separate smoke output directory and port `18081`. Do not mount production `/opt/yuanshu-image-playground/ilab-output` for canary.

```bash
rtk ssh target "set -euo pipefail
TAG='yuanshu-image-playground:0.1.1-ilab-yuanshu-preview-loading-20260625'
SMOKE='/opt/yuanshu-image-playground/ilab-output-smoke-preview-loading'
mkdir -p \"\$SMOKE\"
docker rm -f yuanshu-image-playground-canary-preview-loading >/dev/null 2>&1 || true
docker run -d --name yuanshu-image-playground-canary-preview-loading \
  -p 18081:8787 \
  -e ILAB_CONJURE_DATA_DIR=/app/output \
  -e YUANSHU_IMAGE_PLAYGROUND_PUBLIC_MODE=true \
  -e YUANSHU_IMAGE_PLAYGROUND_API_BASE=https://yuans.vip/image-playground/api/v1 \
  -e YUANSHU_IMAGE_PLAYGROUND_PATH_PREFIX=/image-playground \
  -v \"\$SMOKE:/app/output\" \
  \"\$TAG\"
for i in \$(seq 1 45); do
  if curl -fsS http://127.0.0.1:18081/api/health; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:18081/ | grep -E '/image-playground/static/(styles.css|app.js)' | head
curl -fsS http://127.0.0.1:18081/history | grep -E '/image-playground/static/(styles.css|history.js)' | head
curl -fsSI http://127.0.0.1:18081/static/app.js | head -10
docker ps --filter name=yuanshu-image-playground-canary-preview-loading --format '{{.Names}} {{.Image}} {{.Status}} {{.Ports}}'
"
```

After successful production cutover, remove canary:

```bash
rtk ssh target "docker rm -f yuanshu-image-playground-canary-preview-loading >/dev/null 2>&1 || true"
```

## Production Cutover

This service is managed by direct Docker container replacement, not by a project-local compose file. Preserve the old container inspect JSON before removing the container.

```bash
rtk ssh target "set -euo pipefail
ROOT='/opt/yuanshu-image-playground'
TAG='yuanshu-image-playground:0.1.1-ilab-yuanshu-preview-loading-20260625'
BACKUP=\"\$ROOT/backups/yuanshu-image-playground-before-preview-loading-20260625-2203.json\"
docker inspect yuanshu-image-playground > \"\$BACKUP\"
echo backup=\"\$BACKUP\"
echo old_image=\$(docker inspect yuanshu-image-playground --format '{{.Config.Image}}')
docker rm -f yuanshu-image-playground
mkdir -p \"\$ROOT/ilab-output\"
docker run -d --name yuanshu-image-playground \
  -p 18080:8787 \
  -e ILAB_CONJURE_DATA_DIR=/app/output \
  -e YUANSHU_IMAGE_PLAYGROUND_PUBLIC_MODE=true \
  -e YUANSHU_IMAGE_PLAYGROUND_API_BASE=https://yuans.vip/image-playground/api/v1 \
  -e YUANSHU_IMAGE_PLAYGROUND_PATH_PREFIX=/image-playground \
  -v \"\$ROOT/ilab-output:/app/output\" \
  \"\$TAG\"
for i in \$(seq 1 45); do
  if curl -fsS http://127.0.0.1:18080/api/health; then break; fi
  sleep 1
done
docker ps --filter name=yuanshu-image-playground --format '{{.Names}} {{.Image}} {{.Status}} {{.Ports}}'
docker image inspect \"\$TAG\" --format 'new_image={{.Id}}'
"
```

## Production Verification

Target-side verification:

```bash
rtk ssh target "set -e
docker ps --filter name=yuanshu-image-playground --format '{{.Names}} {{.Image}} {{.Status}} {{.Ports}}'
test -z \"\$(docker ps --filter name=canary --format '{{.Names}}')\" && echo no_canary
curl -fsS http://127.0.0.1:18080/api/health | head -c 500
curl -fsS http://127.0.0.1:18080/ | grep -E '/image-playground/static/(styles.css|app.js)' | head
curl -fsS http://127.0.0.1:18080/history | grep -E '/image-playground/static/(styles.css|history.js)' | head
docker logs --since 5m yuanshu-image-playground 2>&1 | grep -Ei 'traceback|panic|fatal|migration failed|checksum mismatch' | tail -20 || true
"
```

Public verification:

```bash
rtk curl -fsS --max-time 12 https://yuans.vip/health
rtk curl -fsS --max-time 12 https://yuans.vip/image-playground/api/health | rtk head -c 300
rtk curl -fsS --max-time 12 https://yuans.vip/image-playground/ | rtk grep -E '/image-playground/static/(styles.css|app.js)' | rtk head -2
rtk curl -fsS --max-time 12 https://yuans.vip/image-playground/history | rtk grep -E '/image-playground/static/(styles.css|history.js)' | rtk head -2
rtk curl -fsSI --max-time 15 https://yuans.vip/image-playground-console | rtk head -12
rtk curl -fsSI --max-time 15 https://yuans.vip/image-playground/static/app.js | rtk head -12
rtk curl -fsSI --max-time 15 https://yuans.vip/image-playground/static/history.js | rtk head -12
```

Expected notes:

- `HEAD /image-playground/` or `HEAD /image-playground/history` may return `405 Method Not Allowed`; use `GET` for page verification.
- `/image-playground/api/health` can report `auth_available=false` and `yuanshu_status=auth_expired` when called without iframe bootstrap session. That is expected for unauthenticated direct probes as long as `ok=true`.

## Rollback

Rollback is app-only for the target ilab service.

1. Identify previous image from the latest backup or this runbook.
2. Recreate only the `yuanshu-image-playground` container with the old image.
3. Keep `/opt/yuanshu-image-playground/ilab-output` mounted.
4. Re-run the production verification checklist.

Example:

```bash
rtk ssh target "set -euo pipefail
ROOT='/opt/yuanshu-image-playground'
OLD='yuanshu-image-playground:0.1.1-ilab-yuanshu-history-return-layout-20260625'
docker rm -f yuanshu-image-playground
docker run -d --name yuanshu-image-playground \
  -p 18080:8787 \
  -e ILAB_CONJURE_DATA_DIR=/app/output \
  -e YUANSHU_IMAGE_PLAYGROUND_PUBLIC_MODE=true \
  -e YUANSHU_IMAGE_PLAYGROUND_API_BASE=https://yuans.vip/image-playground/api/v1 \
  -e YUANSHU_IMAGE_PLAYGROUND_PATH_PREFIX=/image-playground \
  -v \"\$ROOT/ilab-output:/app/output\" \
  \"\$OLD\"
curl -fsS http://127.0.0.1:18080/api/health
"
```

Do not run these for this project deployment:

```bash
docker compose down -v
docker volume prune
rm -rf /opt/yuanshu-image-playground/ilab-output
rm -rf /opt/sub2api/deploy/data
rm -rf /opt/sub2api/deploy/postgres_data
rm -rf /opt/sub2api/deploy/redis_data
```

## Target Disk Cleanup

2026-06-25 23:12 CST, `target` image service disk cleanup:

- Reason: `target` disk usage was high after several same-day image service builds and hotfix deploys.
- Scope: target-side cleanup only. Did not restart or rebuild `yuanshu-image-playground`, Sub2API, PostgreSQL, Redis, or Nginx.
- Before cleanup: `/dev/vda2` was `43G`, used `33G`, available `7.9G`, `81%`.
- After cleanup: `/dev/vda2` was `43G`, used `28G`, available `14G`, `68%`.
- Reclaimed about `5G`.
- Important finding: `/opt/yuanshu-image-playground/backups` was only `104K`, so old rollback JSON backups were not the disk pressure source.
- Main reclaim sources:
  - Removed older image service build contexts from `/opt/yuanshu-image-playground/builds`.
  - Removed temporary smoke/runtime output directories: `/opt/yuanshu-image-playground/ilab-output-smoke*` and `/opt/yuanshu-image-playground/runtime-output-backup-*`.
  - Ran `docker builder prune -af` to clear Docker build cache. Build cache dropped from about `6.974GB` to `0B`.
- Preserved production data: `/opt/yuanshu-image-playground/ilab-output` was not deleted.
- Preserved rollback/build anchors:
  - `0.1.1-ilab-yuanshu-preview-loading-20260625`
  - `0.1.1-ilab-yuanshu-history-return-layout-20260625`
  - `0.1.1-ilab-yuanshu-sw-cache-cleanup-route-20260625`
  - `0.1.1-ilab-yuanshu-sw-cache-cleanup-20260625`
  - `0.1.1-ilab-yuanshu-history-fields-fix-20260625`
  - `0.1.1-ilab-yuanshu-p0p1-isolation-limits-20260625`
- Remaining `/opt/yuanshu-image-playground` size after cleanup: `157M`.
- Remaining build contexts after cleanup: `122M`.
- Remaining persistent output size after cleanup: `11M`.
- Docker after cleanup:
  - Images: `87` total, `14.45GB`.
  - Build cache: `0B`.
  - Local volumes: `54.05MB`; not pruned.
- Service validation:
  - `yuanshu-image-playground` stayed up and healthy on image `yuanshu-image-playground:0.1.1-ilab-yuanshu-preview-loading-20260625`.
  - `http://127.0.0.1:18080/api/health` returned OK payload.
  - Recent `yuanshu-image-playground` logs showed no `traceback`, `panic`, `fatal`, or `error`.
  - Public `https://yuans.vip/health` returned `{"status":"ok"}`.
  - Public `/image-playground/api/health` returned OK payload.
  - Public static `app.js` still returned `200`, gzip, and `X-Yuanshu-Static-Cache: HIT`.

Safe repeat pattern for future target disk cleanup:

```bash
rtk ssh target "set -e
df -hT / /opt 2>/dev/null || df -hT
du -xhd1 /opt/yuanshu-image-playground 2>/dev/null | sort -h
docker system df
docker ps --filter name=yuanshu-image-playground --format '{{.Names}} {{.Image}} {{.Status}}'
"
```

Then remove only clearly old build contexts and temporary smoke/runtime directories, keep the current and recent rollback build directories, and run:

```bash
rtk ssh target "docker builder prune -af"
```

Verify after cleanup:

```bash
rtk ssh target "set -e
df -hT / /opt 2>/dev/null || df -hT
docker system df
docker ps --filter name=yuanshu-image-playground --format '{{.Names}} {{.Image}} {{.Status}}'
curl -fsS http://127.0.0.1:18080/api/health | head -c 300
docker logs --since 10m yuanshu-image-playground 2>&1 | grep -Ei 'traceback|panic|fatal|error' | tail -30 || true
"
rtk ssh yuan "set -e
curl -fsS --max-time 10 https://yuans.vip/health
curl -fsS --max-time 12 https://yuans.vip/image-playground/api/health | head -c 300
curl -fsSI --compressed --max-time 12 https://yuans.vip/image-playground/static/app.js | grep -Ei 'HTTP/|cache-control|content-encoding|x-yuanshu'
"
```

Do not delete these without explicit approval and a fresh backup/rollback plan:

```bash
rm -rf /opt/yuanshu-image-playground/ilab-output
docker volume prune
docker image prune -a
docker rm -f yuanshu-image-playground
```

Optional next cleanup tier if disk pressure returns:

- Remove older tagged `yuanshu-image-playground` images that are not the current image and not one of the recent rollback anchors.
- Remove old exited containers after confirming they are not needed for forensic rollback.
- Do not prune Docker volumes unless their owners and contents are explicitly verified.

## Nginx Static Cache Optimization

2026-06-25 22:32 CST, `yuan` Nginx static cache/gzip optimization:

- Type: `yuan` Nginx-only optimization; did not restart Sub2API, PostgreSQL, Redis, or target `yuanshu-image-playground`.
- Goal: keep target as origin but reduce repeated public downloads and cross-host origin fetches for `/image-playground/static/*`.
- Config backup: `/etc/nginx/conf.d/sub2api.conf.bak-image-static-cache-20260625-223126`.
- Full `nginx -T` snapshot: `/etc/nginx/conf.d/sub2api-nginxT-before-image-static-cache-20260625-223126.txt`.
- Cache zone file: `/etc/nginx/conf.d/00-yuanshu-image-static-cache.conf`.
- Cache directory: `/var/cache/nginx/yuanshu_image_static`, `max_size=100m`, `inactive=1h`.
- Only `/image-playground/static/*` is cached and gzipped. `/image-playground/api/*`, `/image-playground/`, `/image-playground/history`, `/outputs/*`, and `/inputs/*` remain uncached.
- Static response headers now include `Cache-Control: public, max-age=3600`, `Content-Encoding: gzip`, `Vary: Accept-Encoding`, and `X-Yuanshu-Static-Cache`.
- Cache was confirmed warm with `X-Yuanshu-Static-Cache: HIT` for `app.js`, `history.js`, and `styles.css`.
- Compressed transfer sizes observed from public curl:
  - `app.js`: `2111087` bytes before -> `410199` bytes after.
  - `history.js`: `1040803` bytes before -> `203508` bytes after.
  - `styles.css`: `244865` bytes before -> `37638` bytes after.
- Public timing still varies with client TLS/network, but repeated static transfers are materially smaller and no longer need every request to refetch from target origin after cache warmup.
- Validation after reload:
  - `https://yuans.vip/health` returned 200.
  - `/image-playground/api/health`, `/image-playground/`, `/image-playground/history`, `/image-playground/static/app.js`, `/image-playground/static/history.js`, `/image-playground/static/styles.css` returned 200.
  - Unauthenticated `POST /image-playground/api/v1/images/generations` still returned 401, confirming image API was not statically cached.
  - `docker stats --no-stream` on `yuan` showed low resource pressure; Nginx workers stayed small.
  - Nginx error log after reload showed no new cache/gzip/upstream errors; cache directory held 3 files, about `3.3M`.

Rollback for this Nginx optimization:

```bash
rtk ssh yuan "set -euo pipefail
cp /etc/nginx/conf.d/sub2api.conf.bak-image-static-cache-20260625-223126 /etc/nginx/conf.d/sub2api.conf
rm -f /etc/nginx/conf.d/00-yuanshu-image-static-cache.conf
nginx -t
systemctl reload nginx
curl -fsS https://yuans.vip/health
curl -fsS https://yuans.vip/image-playground/ >/dev/null
curl -fsSI https://yuans.vip/image-playground/static/app.js | head
"
```

## Migration To Yuan

2026-06-26 10:42 CST, `yuanshu-image-playground` was migrated from `target` to `yuan` because upstream traffic from `23.95.10.133` was being classified as robot IP traffic.

- Type: runtime migration only; no code rebuild.
- Old host: `target` / `23.95.10.133`.
- New active host: `yuan` / `173.242.119.18`.
- Image copied from target and loaded on yuan:
  - `yuanshu-image-playground:0.1.1-ilab-yuanshu-preview-loading-20260625`
  - Image ID: `sha256:509c197c6a5006cebc4c409b954b6db01544036f50c0f167ead299d71eca6195`
  - Transfer package: `/tmp/yuanshu-image-playground-preview-loading-20260626.tar.gz`
  - Package SHA256: `daf5f6f89f9e7d8acbcce697e3f58daca8b5c7130422e9800e7ecb37d189def8`
- Data synced from target to yuan:
  - Source: `target:/opt/yuanshu-image-playground/ilab-output/`
  - Destination: `yuan:/opt/yuanshu-image-playground/ilab-output/`
  - Synced state at cutover: `25M`, `65` files.
- New yuan container:
  - Name: `yuanshu-image-playground`
  - Port: `127.0.0.1:18080 -> 8787`
  - Data mount: `/opt/yuanshu-image-playground/ilab-output:/app/output`
- Nginx origin changes:
  - `/image-playground/api/` -> `http://127.0.0.1:18080/api/`
  - `/image-playground/static/` -> `http://127.0.0.1:18080/static/`
  - `/image-playground/` -> `http://127.0.0.1:18080/`
  - `/image-playground/api/v1/images/` and `/image-playground/api/v1/session/verify` still go to local Sub2API on `127.0.0.1:8080`.
- Old target service was not stopped during cutover and should remain available for the observation window.
- Observation default: keep old target service running for 24 hours, then `docker stop yuanshu-image-playground` on target only if yuan has been stable.
- Do not delete target data, target images, or target backups during the observation window.

Validation after cutover:

- `https://yuans.vip/health` returned `{"status":"ok"}`.
- `/image-playground/api/health`, `/image-playground/`, and `/image-playground/history` returned OK.
- `/image-playground/static/app.js` returned 200 with gzip and static cache; second check was `X-Yuanshu-Static-Cache: HIT`.
- yuan `yuanshu-image-playground`, `sub2api`, PostgreSQL, and Redis containers were healthy.
- Initial yuan resource usage after cutover:
  - `yuanshu-image-playground`: about `43MiB` memory.
  - `sub2api`: about `103MiB` memory.
  - PostgreSQL: about `196MiB` memory.
  - Redis: about `6MiB` memory.
- Nginx error log showed no new image/upstream errors immediately after cutover.

Rollback for this migration:

```bash
rtk ssh yuan "set -euo pipefail
cp /etc/nginx/conf.d/sub2api.conf.bak-image-migrate-to-yuan-20260626-103450 /etc/nginx/conf.d/sub2api.conf
nginx -t
systemctl reload nginx
curl -fsS https://yuans.vip/health
curl -fsS https://yuans.vip/image-playground/api/health | head -c 300
"
```

Note: because target IP was classified as robot IP traffic by the upstream provider, this rollback may restore page/history service but may not restore successful image generation.

## Latest Release Record

2026-06-26 11:45 CST, `image-playground quality medium hotfix`:

- Type: yuan-local image playground hotfix; did not rebuild or restart Sub2API, PostgreSQL, Redis, billing, account pool, usage logs, or the main Yuanshu app.
- Root cause: the upstream OpenAI-compatible image provider accepts `response_format=url`, `output_format=png`, and explicit `quality=low|medium|high`, but rejects the combination that included `quality=auto`. When account 96 received a 403 from that upstream call, Sub2API temporarily cooled it, and group 13 then had no available compatible account.
- Code fix: `OpenAIImagesImageClient` now omits `quality` when the UI/client value is `auto`; explicit `low`, `medium`, and `high` are still sent.
- UI fix: the quality selector default is now `medium`, and form reset also returns to `medium`.
- Cache fix: homepage static runtime version was bumped from `runtime-384` to `runtime-385` so browsers and yuan Nginx do not reuse the older cached `app.js`.
- Source package: `/tmp/ilab-gpt-conjure-quality-medium-cachebump-20260626.tgz`.
- Source package SHA256: `210e691db923a015506febc26b11c45e7af9bd646579c732b57e15c86d191dda`.
- New image: `yuanshu-image-playground:0.1.1-ilab-yuanshu-quality-medium-cachebump-20260626`.
- New image ID: `sha256:e768a7a1d07890d6ecb86e7363b814f853acec563e2f4e6ec84283a387be5010`.
- Rollback backup: `/opt/yuanshu-image-playground/backups/yuanshu-image-playground-before-quality-medium-cachebump-20260626-113846.json`.
- Previous image retained: `yuanshu-image-playground:0.1.1-ilab-yuanshu-preview-loading-20260625`.
- Local validation: `npm run check:webui`; `python3 -m unittest tests.test_client -v`.
- Direct payload validation: `auto` is omitted from image requests; `medium`, `low`, and `high` are preserved.
- Public validation: `https://yuans.vip/health`, `/image-playground/api/health`, `/image-playground/`, `/image-playground/history`, and `/image-playground/static/app.js?v=runtime-385` returned OK.
- Static validation: `/image-playground/static/app.js?v=runtime-385` returned gzip and `X-Yuanshu-Static-Cache: MISS` on the first request, confirming the cache-bumped asset path was used.
- Gateway quality validation through local Sub2API `/v1/images/generations` with the production image group:
  - `quality=low`: HTTP 200 and image URL returned.
  - `quality=medium`: HTTP 200 and image URL returned.
  - `quality=high`: HTTP 200 and image URL returned.
- Post-cutover resource check: `yuanshu-image-playground` used about `43MiB` memory; Sub2API, PostgreSQL, and Redis remained low-pressure.
- Log check: `yuanshu-image-playground` had no recent `traceback`, `panic`, `fatal`, or `error`. Nginx only showed transient `connection refused` entries during the seconds when the image container was intentionally replaced.

Rollback for this hotfix:

```bash
rtk ssh yuan "set -euo pipefail
docker rm -f yuanshu-image-playground
docker run -d --name yuanshu-image-playground \
  -p 127.0.0.1:18080:8787 \
  -e ILAB_CONJURE_DATA_DIR=/app/output \
  -e YUANSHU_IMAGE_PLAYGROUND_PUBLIC_MODE=true \
  -e YUANSHU_IMAGE_PLAYGROUND_API_BASE=https://yuans.vip/image-playground/api/v1 \
  -e YUANSHU_IMAGE_PLAYGROUND_PATH_PREFIX=/image-playground \
  -v /opt/yuanshu-image-playground/ilab-output:/app/output \
  yuanshu-image-playground:0.1.1-ilab-yuanshu-preview-loading-20260625
curl -fsS http://127.0.0.1:18080/api/health | head -c 300
curl -fsS https://yuans.vip/image-playground/ >/dev/null
"
```

2026-06-26 12:40 CST, `image gateway failover group fix`:

- Type: Sub2API configuration-only fix; did not rebuild or restart Sub2API, PostgreSQL, Redis, Nginx, or the image playground container.
- Symptom: user task `20260626042652-ef500f68` failed at `2026-06-26 12:26:53 CST` with upstream HTTP 403: `Upstream access forbidden, please contact administrator`.
- Request ID shown in the admin error detail: `17a2f41c-9b41-462b-a821-002d8aadcaa4`.
- Root cause: key id `22` was bound to group `13`, and group `13` only contained account `96`. When account `96` received an intermittent upstream 403, Sub2API temporarily cooled account `96` until `2026-06-26 12:36:53+08`; failover then had no compatible account left in the same group.
- Non-causes verified:
  - Public page was already serving `runtime-385`; this was not browser cache.
  - Default `quality=medium` was already active.
  - Direct upstream tests with `quality=medium`, `output_format=png`, `response_format=url`, and `moderation=auto` returned HTTP 200.
  - The stored WebUI request payload for task `20260626042652-ef500f68` returned HTTP 200 when replayed later, so the failure was not a deterministic payload incompatibility.
- Fix applied:

```sql
insert into account_groups(account_id, group_id, priority, created_at)
values (95, 13, 2, now())
on conflict (account_id, group_id) do update set priority = excluded.priority;
```

- Resulting group `13` account map:
  - `96 -> 13`, priority `1`.
  - `95 -> 13`, priority `2`.
- Validation:
  - Account `95` direct upstream smoke returned HTTP 200 and an image URL.
  - Key id `22` through local Sub2API `/v1/images/generations` returned HTTP 200 and an image URL after the group update.
  - Latest key id `22` success log after the change: usage log id `53431`, account `96`, created at `2026-06-26 12:37:33+08`.
  - Account `96` direct upstream smoke returned HTTP 200 in 3 consecutive attempts.
  - After account `96` runtime cooldown naturally expired, an only-96 platform smoke test returned HTTP 200 and usage log id `53441` confirmed `account_id=96` at `2026-06-26 12:54:19+08`.
  - Account `95` was restored to group `13` after the only-96 smoke test, and both accounts `95` and `96` had no active `temp_unschedulable_until`.

Rollback for this group fix:

```sql
delete from account_groups where account_id = 95 and group_id = 13;
```

Do not roll this back unless account `95` itself becomes unhealthy or billing/policy requires separating the two groups. Rolling back returns group `13` to a single-account failure mode.

2026-06-25 22:03 CST, `image-playground preview loading hotfix`:

- Type: target independent service hotfix; did not replace `yuan` main Sub2API container.
- ilab commit: `3cb5a0d fix: improve webui preview loading states`.
- Source package: `/tmp/ilab-gpt-conjure-preview-loading-3cb5a0d.tgz`.
- Source package SHA256: `13b5e16cae4b8af9f04d355603c67a40a690ded85b2e61d975ba2cd7c8ff2616`.
- New image: `yuanshu-image-playground:0.1.1-ilab-yuanshu-preview-loading-20260625`.
- New image ID: `sha256:509c197c6a5006cebc4c409b954b6db01544036f50c0f167ead299d71eca6195`.
- Rollback backup: `/opt/yuanshu-image-playground/backups/yuanshu-image-playground-before-preview-loading-20260625-2203.json`.
- Previous image retained: `yuanshu-image-playground:0.1.1-ilab-yuanshu-history-return-layout-20260625`.
- Local validation: `npm run check:webui`; `python3 -m py_compile` for `codex_image`.
- Canary validation: target `18081` `/api/health`, home page static references, history page static references, static `app.js`.
- Production validation: target container healthy; no canary left; public `/health`, `/image-playground/api/health`, `/image-playground/`, `/image-playground/history`, `/image-playground/static/app.js`, `/image-playground/static/history.js`, and `/image-playground-console` verified.
- Log check: no recent `traceback`, `panic`, `fatal`, `migration failed`, or `checksum mismatch`.

User-visible changes:

- Task selection renders the right preview card immediately and shows `图片加载中` while large images load.
- Yuanshu mode hides main model and web search settings and removes the reserved `modeSettingsSlot` height.
- History first screen shows task skeletons and detail placeholders.
- History detail output images show a loading placeholder and hide it after image load.
