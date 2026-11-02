#!/bin/bash
# ==============================================================================
# Container Entrypoint Script for Smart Emergency Drone System
# ==============================================================================
set -e

echo "[*] Initializing Smart Emergency Drone Delivery System Container..."

# Wait for MySQL database if DB_HOST is set and not a local SQLite database
if [ -n "$DB_HOST" ] && [ "$DB_HOST" != "127.0.0.1" ] && [ "$DB_HOST" != "localhost" ]; then
    echo "[*] Waiting for MySQL database at $DB_HOST:${DB_PORT:-3306} to be ready..."
    MAX_RETRIES=30
    COUNTER=0
    until python -c "
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
try:
    s.connect(('$DB_HOST', int('${DB_PORT:-3306}')))
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
        COUNTER=$((COUNTER + 1))
        if [ $COUNTER -ge $MAX_RETRIES ]; then
            echo "[X] Timed out waiting for database connection."
            exit 1
        fi
        echo "    Waiting for database ($COUNTER/$MAX_RETRIES)..."
        sleep 2
    done
    echo "[+] Database port is reachable."
fi

# Apply database initialization / migrations safely
echo "[*] Running database initialization..."
python scripts/init_db.py

# Optionally provision master administrator if configured
if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASSWORD" ]; then
    echo "[*] Checking/Provisioning Master Administrator account..."
    python scripts/create_admin.py || echo "[!] Admin creation skipped or already completed."
fi

echo "[+] Starting Gunicorn WSGI production server..."
exec gunicorn \
    --bind "0.0.0.0:${PORT:-5000}" \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-2}" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    wsgi:app
