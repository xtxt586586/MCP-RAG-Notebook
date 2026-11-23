#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null
if command -v python3 >/dev/null && python3 --version >/dev/null 2>&1; then
  python_cmd=python3
elif command -v python >/dev/null && python --version >/dev/null 2>&1; then
  python_cmd=python
else
  printf '%s\n' '需要 Python 3.11 或更高版本。' >&2
  exit 1
fi
if [ ! -f .env ]; then
  if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
    printf '%s\n' '请先设置 DEEPSEEK_API_KEY 环境变量。' >&2
    exit 1
  fi
  "$python_cmd" scripts/setup_env.py
fi
build_args=()
if [ -n "${CONTAINER_HTTP_PROXY:-}" ]; then
  build_args+=(--build-arg "HTTP_PROXY=$CONTAINER_HTTP_PROXY")
fi
if [ -n "${CONTAINER_HTTPS_PROXY:-}" ]; then
  build_args+=(--build-arg "HTTPS_PROXY=$CONTAINER_HTTPS_PROXY")
fi
if [ -n "${CONTAINER_NO_PROXY:-}" ]; then
  build_args+=(--build-arg "NO_PROXY=$CONTAINER_NO_PROXY")
fi
if [ -n "${GO_MODULE_PROXY:-}" ]; then
  build_args+=(--build-arg "GOPROXY=$GO_MODULE_PROXY")
fi
minio_image=$(docker compose config --images minio)
if ! docker image inspect "$minio_image" >/dev/null 2>&1; then
  if ! docker pull "$minio_image"; then
    if [ "$minio_image" != 'minio/minio:RELEASE.2024-12-18T13-15-44Z' ]; then
      printf '%s\n' "无法获取配置的 MinIO 镜像：$minio_image" >&2
      exit 1
    fi
    printf '%s\n' '官方 MinIO 镜像不可用，改为从固定版本源码构建。'
    minio_image=local/mcp-rag-minio:RELEASE.2024-12-18T13-15-44Z
    if ! docker image inspect "$minio_image" >/dev/null 2>&1; then
      docker build "${build_args[@]}" -t "$minio_image" deploy/minio
    fi
    printf '\nMINIO_IMAGE=%s\n' "$minio_image" >> .env
    export MINIO_IMAGE="$minio_image"
  fi
fi
docker compose build "${build_args[@]}"
docker compose run --rm --no-deps backend python -m app.scripts.prepare_models
docker compose up -d --no-build --wait
"$python_cmd" demo/run_demo.py
