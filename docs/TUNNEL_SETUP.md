# Public Tunnel Setup

The relay host currently may not be reachable from your other computers because it is behind a private network. A public tunnel fixes that.

## Recommended Shape

Use a single public tunnel to relay port `8765`.

The relay can also serve:

- `/ainet-bootstrap.py`
- `/idea-ainet-latest.tar.gz`
- `/health`
- `/relay`

That means ngrok only has to expose one local port.

## Security

Do not expose the relay without a token. Start it with:

```bash
export AINET_RELAY_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"
```

## Generate Bootstrap For The Public URL

After ngrok gives a public URL, for example:

```text
https://abc-123.ngrok-free.app
```

generate a bootstrap script that points to that URL:

```bash
python3 scripts/make_lan_bootstrap.py \
  --relay-url https://abc-123.ngrok-free.app \
  --package-url https://abc-123.ngrok-free.app/idea-ainet-latest.tar.gz \
  --relay-token "$AINET_RELAY_TOKEN" \
  --output /tmp/ainet-bootstrap.py
```

## Start Relay With Static Bootstrap Files

```bash
ainet --home ~/.ainet-relay relay serve \
  --host 0.0.0.0 \
  --port 8765 \
  --auth-token "$AINET_RELAY_TOKEN" \
  --bootstrap-path /tmp/ainet-bootstrap.py \
  --package-path /tmp/idea-ainet-latest.tar.gz
```

## Start Ngrok

This machine does not currently have `ngrok` installed. Once `ngrok` is installed and authenticated:

```bash
ngrok http 8765
```

If ngrok asks for auth:

```bash
ngrok config add-authtoken YOUR_NGROK_TOKEN
```

## One-Step Client Install

On another computer:

```bash
curl -fsSL https://abc-123.ngrok-free.app/ainet-bootstrap.py | python3
```

If you do not embed the relay token in the bootstrap script, pass it as an environment variable:

```bash
AINET_RELAY_TOKEN=... \
curl -fsSL https://abc-123.ngrok-free.app/ainet-bootstrap.py | python3
```
