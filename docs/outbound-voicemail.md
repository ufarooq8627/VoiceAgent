# Outbound voicemail pilot

Outbound calling is a separate feature from the inbound receptionist. It uses a dedicated worker process and is disabled by default.

## Current first-release boundary

- Twilio only.
- US contacts with an explicit timezone and state; calls are limited to 08:00-21:00 local time.
- One approved audio file per campaign; no live Gemini conversation or per-call message generation.
- No automatic retry. Ambiguous provider submissions require manual reconciliation.
- Campaign launch requires a human approval note. Marketing campaigns also require a recent documented Do Not Call review.
- The Do Not Call review is an operator-recorded gate; this pilot does not connect to federal or state registry services.
- AMD delivers audio only for machine_end_beep; all other results end without a message.

## Setup

1. Install dependencies from requirements.txt.
2. Configure these values in .env:
   - OUTBOUND_ENABLED=false until the legal and operational gates are ready.
   - OUTBOUND_PUBLIC_BASE_URL=https://your-public-host
   - TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN
   - OUTBOUND_AUDIO_DIR for private local audio storage.
   - For PostgreSQL, set `DATABASE_URL` to `postgresql+psycopg://USER:PASSWORD@HOST/DBNAME`.
3. For local development, starting the FastAPI app creates missing tables. For production, run `alembic upgrade head` before starting the app. If upgrading an existing database that has the old application schema but no Alembic history, follow the migration section below first.
4. Log in to the admin portal and use the authenticated /admin/outbound/* endpoints in /docs:
   - Register a business opt-out number.
   - Upload and approve an MP3 or WAV asset.
   - Create a campaign with a caller ID registered to that business in business_phone_numbers.
   - Import a CSV with name,phone,timezone,state,consent_type,evidence_reference,consented_at.
   - Run preflight; approve only after the campaign and message have received the required review.
5. Configure the business opt-out number's Twilio voice webhook as:
   POST https://your-public-host/api/telephony/twilio/outbound/opt-out
6. Enable outbound only after readiness review, then start the worker in a separate process:
   python -m app.outbound.worker

A paused campaign can be resumed with the start endpoint. The campaign worker is intentionally a single instance for this pilot. It uses database rows for claiming and pacing rather than adding Redis or Celery. Use PostgreSQL for production campaign traffic; SQLite is for local development.

## Important controls

- Twilio webhooks require X-Twilio-Signature validation using the account auth token.
- Signed, short-lived media URLs are served from the private outbound audio directory.
- A stop or pause prevents new calls and causes a pending AMD webhook to hang up instead of playing. Already playing audio can finish; stop and pause do not terminate an active call.
- Callback opt-outs apply the scope configured for that opt-out number. In-call keypad opt-outs suppress the campaign purpose.
- Playback completion is recorded only when Twilio returns from the Gather/Play sequence. A completed call alone is not treated as proof that the audio finished.

This code provides technical controls; campaign eligibility, consent language, calling windows, opt-out script content, and human-answer handling still require approval for the intended jurisdiction and campaign type.

## Database migrations

The CSV must provide each recipient's IANA time zone (for example, `America/Los_Angeles`). The system rejects missing or invalid time zones during preflight; it does not infer time zones from area codes because numbers can be ported or used outside their original area. `tzdata` is included for Windows hosts that do not have an IANA timezone database installed.

Alembic is the production schema migration tool. New blank databases use `alembic upgrade head`. For an older database that has only the legacy tables, verify its schema and back it up, then run `alembic stamp 8c92c8e1a17a` followed by `alembic upgrade head` to apply outbound tables. If the previous app version has already created the outbound tables with `create_all()`, verify that all outbound tables are present and run `alembic stamp head` instead. Do not stamp until the schema has been checked. The app no longer calls `create_all()` in production and refuses startup when migrations are not at the current head.

Create later schema changes with `alembic revision --autogenerate -m "describe change"`, inspect and edit the generated revision, then deploy with `alembic upgrade head`. Alembic's autogeneration produces candidate migrations that need human review.

Audio uploads are stored privately under `OUTBOUND_AUDIO_DIR` (default `storage/outbound_audio`) and streamed to Twilio over a signed, short-lived HTTPS URL. Upload accepts MP3 and WAV; Twilio's `<Play>` verb downloads the URL and plays the returned audio. See the [Twilio Play documentation](https://www.twilio.com/docs/voice/twiml/play) for supported behavior.
