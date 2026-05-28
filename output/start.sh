#!/bin/bash
set -e

echo "=========================================="
echo "  OpenCrew — Starting All Services"
echo "=========================================="

# Wait for Redis to be ready
echo "[start] Waiting for Redis..."
until redis-cli ping 2>/dev/null; do
    sleep 1
done
echo "[start] Redis is ready!"

# Start all services via supervisord
echo "[start] Starting supervisord..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/opencrew.conf
