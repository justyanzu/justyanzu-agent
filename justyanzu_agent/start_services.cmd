@echo off
REM 本机运行 python cli.py；Docker 仅起 Redis，宿主机 127.0.0.1:6379
docker compose up -d
if errorlevel 1 (
    echo Failed to start containers. Try: docker compose logs
    exit /b 1
)
echo OK. Redis on 127.0.0.1 — then in project root run: python cli.py
