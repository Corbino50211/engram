# Engram

Free, invite-only long-term memory for Claude Code. It notes what happens in each project, has Claude summarise
the session when it ends (on your own Claude plan, so nothing to pay for), and hands that back next session.

No dependencies anywhere: Python 3.8+ standard library and SQLite.

- `plugin/`: the Claude Code plugin (4 hooks, `run.sh` launcher, `engram.py`)
- `server/`: API + website (`server.py`, `site/index.html`)
- `test_engram.py`: end-to-end self-check, `python3 test_engram.py`

## Use it

1. Get an invite from someone who's in and sign up on their Engram site. Save the key it shows you.
2. In Claude Code:

       /plugin marketplace add corbino50211/engram
       /plugin install engram@engram

3. Save your key with the command from your dashboard (Mac/Linux terminal or Windows PowerShell). It writes
   `~/.engram.json`.
4. Restart Claude Code.

**Windows:** needs Python 3.8+ ([python.org](https://www.python.org/downloads/), tick "Add to PATH") and Git for
Windows, which Claude Code already requires. The plugin finds `python3`, `python` or `py` on its own.

## Run your own server (forks)

    cd server && python3 server.py        # https on :8443 if origin.pem/origin.key are next to server.py, else http

On first start with no users, the console prints the first invite code. Each new user gets 3 invites.
`python3 server.py invite 5` mints more if you have a shell.

Env (all optional): `PORT` (default 8443), `ENGRAM_DB`, `ENGRAM_INVITES` (default 3), `ENGRAM_REPO` (your
GitHub `owner/repo`, shown in the dashboard's install steps). No env on your host? Edit the defaults at the top of
`server.py`.

Always put HTTPS in front: keys travel in request headers. A setup that works on any Python host (server.pro,
a VPS, etc.) with a Cloudflare domain:

1. DNS: `A` record for your subdomain pointing at the host's IP, proxied (orange cloud).
2. SSL/TLS > Origin Server > Create Certificate. Save as `origin.pem` and `origin.key` next to `server.py`.
3. Configuration Rule for `(http.host eq "your.sub.domain")`: SSL = Full (strict).
4. Origin Rule, same filter: destination port = 8443.

Or use the `Dockerfile` (data lives in `/data`; mount a volume).

## What gets sent

Prompts, edited file paths and shell commands, with anything shaped like `API_KEY=...`, `Bearer ...` or `sk-...`
redacted first. At session end `claude -p --model haiku` writes a summary on your machine and only the summary is
uploaded. Summariser errors go to `~/.engram.log`. Everything can be deleted from the dashboard.

## License

MIT
