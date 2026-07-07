#!/bin/sh
set -eu

if [ "${APP_ENV:-}" = "production" ] && [ -z "${PAYMENT_BACKEND:-}" ]; then
  export PAYMENT_BACKEND=paypal
fi

python scripts/wait_for_services.py postgres
python scripts/wait_for_services.py redis

exec celery -A app.celery_app.celery_app worker -l info
