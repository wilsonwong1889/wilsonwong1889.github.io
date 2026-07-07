# BIPOC Creative Innovation Studio

Studio booking MVP built with FastAPI, PostgreSQL, Redis, Celery, Alembic, and a lightweight multi-page HTML frontend served by the backend.

Default booking currency: `CAD`.

## MVP Decision

For this MVP, the project will keep the current lightweight HTML frontend under [backend/app/frontend](/Users/wilson/Desktop/StudioBookingSoftware/backend/app/frontend) instead of replacing it with Next.js.

Why:
- It already covers the user and admin flows needed for launch.
- It keeps deployment simple while the booking/payment workflow is being finalized.
- It can be replaced later without changing the backend API contract.

## What Works

- User signup, login, profile update, password change
- Room catalog and admin room management
- Availability lookup and booking creation
- Webhook-driven payment confirmation flow
- Cancellation and refund handling
- Admin booking lookup and manual booking creation
- Background task hooks for emails, reminders, and cleanup
- Docker-based local stack with automatic waits, migrations, and seed data

## Local Startup

### Option 1: Full stack with Docker

```bash
cd /Users/wilson/Desktop/StudioBookingSoftware/backend
cp .env.example .env
docker compose up --build
```

What happens automatically:
- Postgres starts
- Redis starts
- the API waits for dependencies
- Alembic migrations run
- seed data is created when `AUTO_SEED_DATA=true`
- the API starts on `http://127.0.0.1:8000`
- the Celery worker starts
- the Celery beat scheduler starts for reminders and pending-booking cleanup

### Option 3: Production-style compose

```bash
cd /Users/wilson/Desktop/StudioBookingSoftware/backend
cp .env.example .env
docker compose -f docker-compose.prod.yml up --build -d
```

Notes:
- this disables auto seeding by default
- the API healthcheck uses `/ready` instead of `/health`
- the image now runs as a non-root user

### Option 2: Backend on host

Requirements:
- local Postgres running on `localhost:5432`
- local Redis running on `localhost:6379`

```bash
cd /Users/wilson/Desktop/StudioBookingSoftware/backend
cp .env.example .env
venv/bin/alembic upgrade head
venv/bin/python scripts/seed_week2.py
venv/bin/uvicorn app.main:app --reload
```

## Seed Data

The startup seed script is [backend/scripts/seed_week2.py](/Users/wilson/Desktop/StudioBookingSoftware/backend/scripts/seed_week2.py).

These env vars control the seeded admin:
- `SEED_ADMIN_EMAIL`
- `SEED_ADMIN_PASSWORD`
- `SEED_ADMIN_FULL_NAME`
- `SEED_ADMIN_PHONE`
- `SEED_ADMIN_ROLE`
- `SEED_ADMIN_ROTATE_PASSWORD`

Seed values from [backend/.env.example](/Users/wilson/Desktop/StudioBookingSoftware/backend/.env.example):
- email: `adminstudiobipoc@gmail.com`
- password: must be set in `SEED_ADMIN_PASSWORD` before seeding
- full name: `BIPOC Foundation Admin`
- phone: blank by default
- role: `AdminManager`
- password rotation for an existing admin is off unless `SEED_ADMIN_ROTATE_PASSWORD=true`

## Admin Login

If you use the default seed settings:
- email: `adminstudiobipoc@gmail.com`
- password: the value configured in `SEED_ADMIN_PASSWORD`

If you changed seed env vars, use those values instead.

Startup validates that at least one active `AdminManager` account exists after migrations and optional seeding.

## Payments And Webhooks

### Current default

The project defaults to local-safe stub mode:
- `PAYMENT_BACKEND=stub`
- `EMAIL_BACKEND=console`
- `SMS_BACKEND=console`

That is enough for local development and automated tests.

### Production PayPal settings

Update [backend/.env](/Users/wilson/Desktop/StudioBookingSoftware/backend/.env) for local testing, or your Render service environment variables for production:

```env
APP_ENV=production
PAYMENT_BACKEND=paypal
PAYPAL_CLIENT_ID=your_paypal_rest_client_id
PAYPAL_CLIENT_SECRET=your_paypal_rest_client_secret
PAYPAL_WEBHOOK_ID=your_paypal_webhook_id
PAYPAL_ENV=sandbox
EMAIL_BACKEND=sendgrid
SMS_BACKEND=twilio
SENDGRID_API_KEY=SG.your_key
EMAIL_FROM=bookings@yourdomain.com
EMAIL_REPLY_TO=support@yourdomain.com
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_FROM_NUMBER=+14035551234
```

`PAYPAL_ENV=sandbox` is allowed on the production site while the studio is still taking test-mode payments. Switch it to `live` only when the PayPal app and webhook were created in live mode.

You can also use Gmail SMTP instead of SendGrid:

```env
EMAIL_BACKEND=smtp
EMAIL_FROM=bookings@example.com
EMAIL_REPLY_TO=support@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=bookings@example.com
SMTP_PASSWORD=your_gmail_app_password
SMTP_USE_TLS=true
```

When `APP_ENV=production`, the app now validates launch-critical settings at startup and will fail fast if you try to run with placeholder secrets, stub payments, console email, eager Celery tasks, insecure `APP_BASE_URL`, or localhost CORS origins.

### PayPal webhook endpoint

Register the PayPal webhook URL as `{APP_BASE_URL}/api/webhooks/paypal` and copy the webhook id into `PAYPAL_WEBHOOK_ID`.

## Running Tests

```bash
cd /Users/wilson/Desktop/StudioBookingSoftware/backend
venv/bin/python -m unittest discover -s tests -v
```

The suite includes:
- smoke coverage for auth, rooms, bookings, admin, frontend routes
- operational tests for reminders, cleanup, and conflict handling
- end-to-end booking/payment confirmation coverage
- payment-session coverage for pending booking checkout setup
- runtime config validation coverage

## Important Env Flags

- `AUTO_SEED_DATA=true`: seed default admin and rooms on API startup
- `CELERY_TASK_ALWAYS_EAGER=true|false`: run tasks inline or through the worker
- `REMINDER_HOURS_BEFORE=24,1`: reminder windows to dispatch
- `REMINDER_DISPATCH_INTERVAL_MINUTES=30`: how often the scheduler checks for reminders
- `PENDING_BOOKING_CLEANUP_INTERVAL_MINUTES=10`: how often the scheduler checks for expired pending bookings
- `PENDING_BOOKING_EXPIRY_MINUTES=15`: when an unpaid pending booking should be cancelled automatically
- `ALLOWED_CORS_ORIGINS=...`: comma-separated frontend origins for browser access
- `PAYMENT_BACKEND=stub|paypal`: local tests use `stub`; production must use `paypal`
- `PAYPAL_CLIENT_ID=...`: required for browser checkout in PayPal mode
- `PAYPAL_CLIENT_SECRET=...`: required for PayPal Orders API calls
- `PAYPAL_WEBHOOK_ID=...`: required for PayPal webhook signature verification
- `PAYPAL_ENV=sandbox|live`: selects the PayPal API environment
- `WEBHOOK_TOLERANCE_SECONDS=300`: stub-mode webhook signature timestamp tolerance
- `EMAIL_REPLY_TO=...`: optional support address for email replies
- `EMAIL_BACKEND=console|sendgrid|smtp`
- `SMTP_HOST=...`: required when `EMAIL_BACKEND=smtp`
- `SMTP_PORT=587`: required when `EMAIL_BACKEND=smtp`
- `SMTP_USERNAME=...`: required when `EMAIL_BACKEND=smtp`
- `SMTP_PASSWORD=...`: required when `EMAIL_BACKEND=smtp`
- `SMTP_USE_TLS=true|false`: enable STARTTLS for SMTP delivery
- `SMS_BACKEND=console|twilio`
- `TWILIO_ACCOUNT_SID=...`: required when `SMS_BACKEND=twilio`
- `TWILIO_AUTH_TOKEN=...`: required when `SMS_BACKEND=twilio`
- `TWILIO_FROM_NUMBER=...`: required when `SMS_BACKEND=twilio`

## Current MVP Boundary

Included in MVP:
- backend API
- lightweight frontend served by FastAPI
- Docker local runtime
- booking/admin lifecycle

Deferred until after MVP:
- replacing the frontend with Next.js
- advanced analytics/reporting
- non-essential UI polish beyond core flows
