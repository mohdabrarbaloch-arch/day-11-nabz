# Setup

## Requirements

- Python 3.11+
- Docker (optional, for the PostgreSQL path)

## Local, SQLite (fastest)

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-11-nabz.git
cd day-11-nabz

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000>. The demo account is pre-filled on the login screen:

```
demo@nabz.pk
nabz-demo-2026
```

On first boot the app creates `nabz.db`, seeds 12 therapies and 10 synthetic
patients, and logs what it created. Delete `nabz.db` to start over.

## Docker, PostgreSQL

```bash
export SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")
docker compose up --build
```

Same URL, same demo account. The app waits for the database healthcheck before
starting, and runs as a non-root user inside the container.

## Configuration

Every variable is documented in `.env.example`. The ones that matter:

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | Set to `production` to enable HSTS and the SECRET_KEY guard |
| `SECRET_KEY` | dev placeholder | **Must** be ≥ 32 random characters in production, or the app refuses to boot |
| `DATABASE_URL` | `sqlite:///./nabz.db` | Use `postgresql+psycopg://…` for Postgres |
| `CORS_ORIGINS` | `http://localhost:8000` | Comma-separated. Never `*` with credentials |
| `RATE_LIMIT_PER_MINUTE` | `120` | Per client IP, per process |
| `LOGIN_RATE_LIMIT_PER_MINUTE` | `10` | Tighter bucket for `/api/auth/login` |
| `BCRYPT_ROUNDS` | `12` | Lower only in tests |
| `SEED_ON_STARTUP` | `true` | Set `false` for a clean deployment |

## Tests and linting

```bash
pytest -q                 # 53 tests
ruff check app tests      # must be clean
black --check app tests   # must be clean
```

## Troubleshooting

**`RuntimeError: SECRET_KEY must be a random value…`**
You set `ENVIRONMENT=production` without a real key. Generate one:
`python3 -c "import secrets;print(secrets.token_urlsafe(48))"`.

**`sqlite3.OperationalError: unable to open database file`**
The working directory isn't writable. On a read-only filesystem (most serverless
platforms) point `DATABASE_URL` at PostgreSQL instead — SQLite cannot work there.

**Login returns 401 with the demo credentials**
The database was seeded before a schema change. Delete `nabz.db` and restart.

**429 on every request**
You're behind a proxy that isn't setting `X-Forwarded-For`, so every request
looks like it comes from one IP. Either set the header or raise the limit.
