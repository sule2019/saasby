# Saasby

Saasby is a curated product directory for AI builders. It is a Flask app designed to run on Render with Neon Postgres and Neon Auth.

## Stack

- Flask
- SQLAlchemy
- Neon Postgres
- Neon Auth
- Render

## Features

- Product-focused landing page and browse flows
- Top 100 and Most Popular product views
- Neon Auth-backed signup and login
- Product launch submissions saved to Postgres
- Render-ready deployment config

## Local development

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Copy the example env values and set your own:

```bash
cp .env.example .env
```

3. Export the env vars or load them with your preferred local env tool:

```bash
export SECRET_KEY='change-me'
export DATABASE_URL='postgresql://USER:PASSWORD@HOST/DB?sslmode=require'
export NEON_AUTH_BASE_URL='https://YOUR-NEON-AUTH-HOST/api/auth'
export APP_BASE_URL='http://127.0.0.1:5000'
export AUTO_INIT_DB=1
```

4. Run the app:

```bash
flask --app app run
```

## Render deployment

The repo includes `render.yaml`, so you can connect this repo directly in Render and set:

- `DATABASE_URL`
- `SECRET_KEY`
- `NEON_AUTH_BASE_URL`
- `APP_BASE_URL`
- optional: `AUTO_INIT_DB=1`

## Neon setup

Use Neon for both:

- Postgres
- Neon Auth with email/password enabled

Recommended auth settings:

- provider: `better_auth`
- require email verification
- send verification email on sign up
- use link-based email verification
- trust your Render domain and local dev domain

## Health check

The app exposes:

```bash
GET /health
```

It returns a simple app + database status payload.
