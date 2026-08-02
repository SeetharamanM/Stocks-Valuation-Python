# Deploying on Ubuntu behind Tailscale

The app is a Flask front-end with no database and no API keys. The only
outbound call it can make is the optional Yahoo Finance lookup, and every
field that supplies can be typed into the form instead.

## Deploy key (private repo)

The repository is private, so the server cannot clone it anonymously. This has
to happen before the first run, because `deploy.sh` clones as `deepval`.

Create the service account and its ssh directory (`deploy.sh` skips the user if
it already exists, so this is safe):

```bash
sudo useradd --system --create-home --home-dir /opt/deepval --shell /usr/sbin/nologin deepval && sudo install -d -o deepval -g deepval -m 700 /opt/deepval/.ssh
```

Generate a key and register the public half on GitHub under
Settings -> Deploy keys, read-only:

```bash
sudo -u deepval ssh-keygen -t ed25519 -N "" -f /opt/deepval/.ssh/id_ed25519
```

```bash
sudo cat /opt/deepval/.ssh/id_ed25519.pub
```

Then trust the host once, so the first clone does not stall on a prompt:

```bash
sudo -u deepval bash -c 'ssh-keyscan github.com >> ~/.ssh/known_hosts'
```

Pass the SSH URL, not the HTTPS one, on first run.

## First run

```bash
sudo bash ./deploy/deploy.sh git@github.com:SeetharamanM/Stocks-Valuation-Python.git
```

Creates a `deepval` service account, clones into `/opt/deepval/app`, builds a
venv, installs `deepval.service` and starts gunicorn on `127.0.0.1:8010`.

Then publish it on the tailnet — Tailscale terminates TLS itself, so there is
no certificate to obtain and nothing to renew:

```bash
sudo tailscale serve --bg --https=8446 http://127.0.0.1:8010
```

## Updating

```bash
sudo bash ./deploy/deploy.sh
```

Pulls, reinstalls dependencies, restarts the service and fails loudly with the
last 40 journal lines if it does not come back up.

## Things that are easy to get wrong

**The gunicorn target is `app:create_app()`.** `app.py` exposes a factory; there
is no module-level `app` object, so the conventional `app:app` fails.

**The working directory matters.** `UPLOAD_DIR` and `OUT_DIR` are relative
paths, so reports land wherever the process happens to be running.

**`--timeout 180`, not the default 30s.** A full DCF plus a slow Yahoo Finance
response will exceed 30 seconds and the worker gets killed mid-request.

**`uploads/` and `outputs/` are gitignored** and never arrive with the clone.
The script creates them; the systemd unit's `ReadWritePaths` is the only reason
they stay writable under `ProtectSystem=strict`.

**Don't put nginx in front unless you need it.** If you do, set
`client_max_body_size 64M` to match `MAX_CONTENT_LENGTH` in `app.py`, or nginx
rejects large Screener exports before Flask sees them. Tailscale Serve imposes
no such limit.

## Known limitations of a multi-user deployment

The report path is `outputs/<Stock_Name>_Valuation.html`, derived only from the
typed stock name, and uploads are saved to `uploads/<original filename>`.
Neither is namespaced per request, so two people analysing the same stock at
the same time will overwrite each other. Fine single-user; fix before sharing
the URL.

The app has no authentication of its own. Access control is entirely whatever
the tailnet ACLs say.
