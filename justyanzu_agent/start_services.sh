#!/bin/bash
# 本机运行 python cli.py；Docker 仅起 Redis（Valkey），供 Skill 缓存等使用（宿主机 127.0.0.1:6379）。
if [ -f .env ]; then
    # shellcheck source=/dev/null
    source .env
fi

command_exists() {
    command -v "$1" &> /dev/null
}

if ! command_exists docker; then
    echo "Error: Docker is not installed. Please install Docker first."
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "Error: Docker daemon is not running. Start Docker Desktop or system docker service."
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command_exists docker-compose; then
    COMPOSE_CMD="docker-compose"
else
    echo "Error: Docker Compose is not installed."
    exit 1
fi

if [ ! -f "docker-compose.yml" ]; then
    echo "Error: docker-compose.yml not found in the current directory."
    exit 1
fi

echo "Starting Redis (compose service: redis)..."
if ! $COMPOSE_CMD up -d; then
    echo "Error: Failed to start containers. Try: $COMPOSE_CMD logs"
    exit 1
fi

echo "OK. Redis on 127.0.0.1:${REDIS_PUBLISH_PORT:-6379} — then in project root run: python cli.py"
