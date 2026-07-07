#!/bin/sh
set -eu

if [ "${APP_ENV:-}" = "production" ] && [ -z "${PAYMENT_BACKEND:-}" ]; then
  export PAYMENT_BACKEND=paypal
fi

python scripts/wait_for_services.py postgres
python scripts/wait_for_services.py redis
alembic upgrade head

if [ "${AUTO_SEED_DATA:-true}" = "true" ]; then
  python scripts/seed_week2.py
fi

python scripts/validate_admin_manager.py

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
