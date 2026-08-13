# Dialectic deployment

This directory contains the production systemd and nginx templates for the
FastAPI backend, React frontend, and WebSocket transport.

The deployment model is intentionally release-based:

- `/root/DwoodAmo` is the canonical Git clone.
- `/opt/dialectic/releases/<release>` is an immutable worktree for one commit.
- `/opt/dialectic/current` points at the active backend release.
- `/var/www/dialectic-releases/<release>` contains one built frontend.
- `/var/www/dialectic-current` points at the active frontend release.
- `/etc/dialectic/dialectic.env` contains production secrets.

Do not run `git pull` in the active release. A new release is built and checked
before either `current` symlink moves, which makes rollback deterministic and
does not disturb a dirty canonical checkout.

## Files

- `dialectic.service` — systemd unit installed at
  `/etc/systemd/system/dialectic.service`.
- `defuddle.service` — systemd unit for the optional article-extraction
  sidecar (`defuddle_service/`), installed at
  `/etc/systemd/system/defuddle.service`. The `read_article` tool degrades
  gracefully when this unit is stopped.
- `nginx.conf.example` — static frontend, REST proxy, WebSocket proxy, HTTP
  redirect, and TLS configuration.

## Prerequisites

The commands below target Ubuntu 24.04 and PostgreSQL 16. Adjust the pgvector
package name if the host uses another PostgreSQL major version.

```bash
apt-get update
apt-get install -y \
  git rsync python3 python3-venv \
  postgresql postgresql-16-pgvector redis-server \
  nginx certbot python3-certbot-nginx

node --version  # Node 20.19+ or 22.12+
npm --version
```

Install a supported Node release before continuing if those commands are
missing or too old.

## 1. Clone the repository and create a release

The Git root is `/root/DwoodAmo`; `dialectic` is a directory inside it.

```bash
git clone <repository-url> /root/DwoodAmo
git -C /root/DwoodAmo fetch --all --prune

export COMMIT=<full-tested-commit-sha>
export RELEASE="$(date -u +%Y%m%dT%H%M%SZ)-${COMMIT:0:12}"
export RELEASE_DIR="/opt/dialectic/releases/$RELEASE"

install -d -m 0755 /opt/dialectic/releases
git -C /root/DwoodAmo worktree add --detach "$RELEASE_DIR" "$COMMIT"
cd "$RELEASE_DIR/dialectic"
```

For an existing canonical clone, start at `git fetch`. Uncommitted work in that
clone is not included: release the commit named by `COMMIT`, never an ambiguous
working tree.

## 2. Install, test, and build

Python dependencies live in a release-local virtual environment. The React
frontend uses its committed npm lockfile.

```bash
make python-setup
venv/bin/python -m pytest -q

make frontend-install
make frontend-lint
make frontend-build

# Article-extraction sidecar (defuddle) — own lockfile, not the yarn workspace.
(cd defuddle_service && npm ci --omit=dev)
```

Do not activate a release unless tests, lint, and the production build all
succeed.

## 3. Initialize a fresh database

`make db-setup` is a **fresh database baseline only**. It refuses to run when
the database already exists. `schema.sql` already incorporates migrations 002,
003, and `cross_session_memories`; the distinct baseline additions are
`001_llm_self_model.sql` and `add_indexes.sql`.

Create a dedicated login role interactively, then let the PostgreSQL admin
create and baseline the database with that owner:

```bash
sudo -u postgres createuser --pwprompt dialectic_app
make DB_USER=postgres DB_OWNER=dialectic_app DB_NAME=dialectic db-setup
```

The baseline runs under `ON_ERROR_STOP` and one transaction. Any SQL error
fails the command instead of being filtered or ignored.

### Existing databases

There is not yet a migration ledger. Never replay `schema.sql` or every file in
`migrations/` against an existing database. Back up first, review the one
forward migration required by the release, and apply it transactionally:

```bash
install -d -m 0700 /var/backups/dialectic
sudo -u postgres pg_dump -Fc --dbname=dialectic \
  > "/var/backups/dialectic/$RELEASE-before.dump"

sudo -u postgres psql --no-psqlrc \
  --set=ON_ERROR_STOP=1 \
  --single-transaction \
  --dbname=dialectic \
  --file=migrations/NNN_reviewed_migration.sql
```

Record the applied migration in the release manifest until a migration ledger
is added. If a release has no database change, do not run any SQL file.

## 4. Configure production environment

Copy the example outside the Git checkout and restrict it before adding real
values:

```bash
install -d -m 0750 /etc/dialectic
install -m 0600 .env.example /etc/dialectic/dialectic.env
${EDITOR:-vi} /etc/dialectic/dialectic.env
```

Production values must include:

```dotenv
DATABASE_URL=postgresql://dialectic_app:<url-encoded-password>@127.0.0.1/dialectic
ANTHROPIC_API_KEY=sk-ant-...
JWT_SECRET_KEY=<output-of-openssl-rand-hex-32>
OPENAI_API_KEY=sk-...
ALLOWED_ORIGINS=https://dialectic.example.com
HOST=127.0.0.1
PORT=8002
PRODUCTION=1
WEB_CONCURRENCY=2
REDIS_URL=redis://127.0.0.1:6379
```

Generate the JWT secret with `openssl rand -hex 32`. Do not paste secrets into
shell history, logs, email, or Git. OpenAI is optional for basic dialogue but is
required for provider fallback and real semantic embeddings. Redis is required
when `WEB_CONCURRENCY` is greater than one so WebSocket broadcasts reach users
connected to different workers.

## 5. Stage backend and frontend releases

Capture the current targets in a release manifest, then switch the backend
symlink:

```bash
install -d -m 0700 /var/backups/dialectic
export PREVIOUS_RELEASE="$(readlink -f /opt/dialectic/current 2>/dev/null || true)"
export PREVIOUS_WEB="$(readlink -f /var/www/dialectic-current 2>/dev/null || true)"
printf 'release=%s\ncommit=%s\nprevious_backend=%s\nprevious_frontend=%s\n' \
  "$RELEASE" "$COMMIT" "$PREVIOUS_RELEASE" "$PREVIOUS_WEB" \
  > "/var/backups/dialectic/$RELEASE.manifest"

ln -sfn "$RELEASE_DIR" /opt/dialectic/current.next
mv -Tf /opt/dialectic/current.next /opt/dialectic/current
```

Stage the frontend separately and switch it atomically:

```bash
export WEB_RELEASE="/var/www/dialectic-releases/$RELEASE"
install -d -m 0755 "$WEB_RELEASE"
rsync -a --delete frontend/app/dist/ "$WEB_RELEASE/"
chown -R root:root "$WEB_RELEASE"

ln -sfn "$WEB_RELEASE" /var/www/dialectic-current.next
mv -Tf /var/www/dialectic-current.next /var/www/dialectic-current
```

Save the release name, commit, database backup, previous symlink targets, and
SHA-256 hashes of `index.html` and its assets in an operator release record.

## 6. Install systemd service

The bundled unit runs the release-local uvicorn from the current symlink, binds
only to loopback, and uses two workers. Redis carries room broadcasts between
those workers.

```bash
install -m 0644 deploy/dialectic.service /etc/systemd/system/dialectic.service
systemctl daemon-reload
systemctl enable dialectic.service
systemctl restart dialectic.service

systemctl status dialectic.service --no-pager
curl --fail --silent --show-error http://127.0.0.1:8002/health
```

The local health response must report both `db: connected` and
`redis: connected` before nginx is switched to the release.

Install the defuddle sidecar alongside it. It binds loopback only and needs
no secrets; the backend's `read_article` tool answers "extractor unavailable"
rather than failing the turn when the unit is stopped, so it is safe to
install later or omit entirely.

```bash
install -m 0644 deploy/defuddle.service /etc/systemd/system/defuddle.service
systemctl daemon-reload
systemctl enable defuddle.service
systemctl restart defuddle.service

curl --fail --silent --show-error http://127.0.0.1:8010/health
```

## 7. Install nginx and TLS

Point DNS at the host first. On a fresh host, obtain the certificate through
the default nginx web root before enabling the HTTPS template:

```bash
export DOMAIN=dialectic.example.com
certbot certonly --webroot --webroot-path /var/www/html --domain "$DOMAIN"

sed "s/dialectic\.example\.com/$DOMAIN/g" deploy/nginx.conf.example \
  > /etc/nginx/sites-available/dialectic
ln -sfn /etc/nginx/sites-available/dialectic /etc/nginx/sites-enabled/dialectic

nginx -t
systemctl reload nginx
```

The template proxies these active API prefixes:

`auth`, `rooms`, `threads`, `users`, `health`, `analytics`, `graph`, `replay`,
`stakes`, `messages`, `memories`, `personas`, and `notifications`.

It also forwards `/ws/` with the required upgrade headers. Keep this list in
sync with FastAPI. Do not expose port 8002 through the public firewall; public
traffic should enter through nginx on 443. Certbot's system timer handles
renewal; verify it with `certbot renew --dry-run` during scheduled maintenance.

## 8. Verify the release

```bash
systemctl is-active --quiet postgresql
systemctl is-active --quiet redis-server
systemctl is-active --quiet dialectic
systemctl is-active --quiet nginx

curl --fail --silent --show-error http://127.0.0.1:8002/health
curl --fail --silent --show-error "https://$DOMAIN/health"
curl --fail --silent --show-error "https://$DOMAIN/" | sha256sum
sha256sum /var/www/dialectic-current/index.html

ss -ltnp | grep ':8002'  # must show 127.0.0.1, not 0.0.0.0
```

Also verify that an API-only path such as `/notifications/badge` returns an API
authentication response and JSON content type, not the SPA's `index.html`.

Complete a two-client smoke test in separate browser profiles or devices:

1. Create two accounts.
2. Create a room with the first account and share its invite details.
3. Join with the second account.
4. Confirm both clients show connected presence and exchange messages.
5. Confirm typing events and a streamed Claude response reach both clients.
6. Reload both clients and re-enter the room.
7. Exercise a thread fork, memory operation, thinking protocol, analytics, and
   replay before declaring the advanced feature set ready.

## Updating to another release

Repeat the release worktree, install, test, build, backup, and staging steps
with a new `COMMIT` and `RELEASE`. Apply only that release's reviewed forward
migration, if any. Switch the backend symlink and restart the service, then
switch the frontend symlink and reload nginx. Verify health, hashes, and the
two-client workflow.

Never update by pulling into `/opt/dialectic/current`, and never use a hard
reset to clean the canonical checkout.

## Rollback

Use the previous targets recorded before activation:

```bash
export PREVIOUS_RELEASE=/opt/dialectic/releases/<previous-release>
export PREVIOUS_WEB=/var/www/dialectic-releases/<previous-release>

ln -sfn "$PREVIOUS_RELEASE" /opt/dialectic/current.next
mv -Tf /opt/dialectic/current.next /opt/dialectic/current
systemctl restart dialectic.service

ln -sfn "$PREVIOUS_WEB" /var/www/dialectic-current.next
mv -Tf /var/www/dialectic-current.next /var/www/dialectic-current
nginx -t
systemctl reload nginx
```

Repeat all health, asset-hash, proxy, and two-client checks. Additive,
backward-compatible database migrations can normally remain in place. If a
database change is not backward compatible, stop application writes and
restore the pre-release dump only with explicit approval: restoring a dump is
destructive and discards data created after that backup.

## Operations and troubleshooting

```bash
# Recent backend logs
journalctl -u dialectic -n 100 --no-pager

# Follow backend logs
journalctl -u dialectic -f

# Listener ownership
ss -ltnp | grep -E ':(443|8002|5432|6379)'

# Validate configs without restarting
systemd-analyze verify /etc/systemd/system/dialectic.service
nginx -t
```

If health reports a database or Redis failure, fix that dependency before
restarting traffic. If the service flaps, inspect the first exception in the
journal rather than repeatedly restarting it. If public API paths return HTML,
the nginx REST prefix list is stale or the wrong site configuration is active.
