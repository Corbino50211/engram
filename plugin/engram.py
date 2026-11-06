#!/usr/bin/env python3
"""Engram client for Claude Code. Python stdlib only.

Hooks run:   engram.py start | prompt | tool | end     (hook JSON on stdin)
Claude runs: engram.py search <words>                  (search all past memory)
Config:      ~/.engram.json  {"url": "https://your-server", "token": "..."}  (copy it from the dashboard)

A hook must never break a session, so failures are only printed to stderr.
"""
import json, os, re, shutil, ssl, subprocess, sys, tempfile, time, urllib.parse, urllib.request

CONFIG = os.path.expanduser("~/.engram.json")
LOG = os.path.expanduser("~/.engram.log")
TLS = ssl.create_default_context()
if os.path.exists("/etc/ssl/cert.pem"):  # python.org macOS builds ship without CA roots; use the system's
    TLS.load_verify_locations("/etc/ssl/cert.pem")
SECRET = re.compile(r"""(?ix)
    ((?:key|token|secret|passw(?:or)?d)\w*["']?\s*[=:]\s*["']?)[^\s"']+   # API_KEY=..., password: "..."
  | (bearer\s+)\S+                                                       # Authorization: Bearer ...
  | \b(?:sk-|ghp_|gho_|github_pat_|xox[abp]-|AKIA)[\w-]{8,}             # well-known key prefixes
""")
SUMMARY_PROMPT = (
    "The input is a Claude Code session transcript. Write a memory note for future sessions in this project: "
    "3-8 terse plain-text bullets, each starting with '- ', covering what was done, decisions and why, files changed, "
    "and open TODOs. No bold, headings or other formatting. Never include secrets, keys or passwords. "
    "Output only the bullets."
)


def redact(text):
    return SECRET.sub(lambda m: (m[1] or m[2] or "") + "[redacted]", text)


def load_config():
    try:
        with open(CONFIG) as f:
            cfg = json.load(f)
        return cfg if cfg.get("url") and cfg.get("token") else None
    except (OSError, ValueError, AttributeError):
        return None


def call(cfg, method, path, body=None, timeout=4):
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {cfg['token']}", "Content-Type": "application/json",
                 "User-Agent": "engram-plugin/0.1"})
    with urllib.request.urlopen(req, timeout=timeout, context=TLS) as r:
        return r.read().decode()


def project(cwd):
    # ponytail: memory is keyed by folder name, so two repos both called "app" share it; key on git remote if that bites
    return os.path.basename(os.path.normpath(cwd or os.getcwd())) or "/"


def describe(tool, inp):
    if tool == "Bash":
        desc = inp.get("description")
        return f"$ {inp.get('command', '')[:300]}" + (f"  ({desc})" if desc else "")
    return f"{tool} {inp.get('file_path') or inp.get('notebook_path') or ''}".strip()


def save(cfg, ev, proj, kind, text):
    if text.strip():
        call(cfg, "POST", "/api/memories",
             {"session_id": ev.get("session_id"), "project": proj, "kind": kind, "text": redact(text)[:2000]})


def transcript_text(path, limit=60_000):
    """The conversation without tool output: what was asked, said and touched. Keeps the most recent `limit` chars."""
    lines = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(e, dict) or e.get("type") not in ("user", "assistant") or e.get("isMeta") or e.get("isSidechain"):
                continue
            content = (e.get("message") or {}).get("content")
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content if isinstance(content, list) else []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and str(b.get("text", "")).strip():
                    lines.append(f"{e['type']}: {str(b['text']).strip()}")
                elif b.get("type") == "tool_use":
                    lines.append(f"  ({b.get('name')} {json.dumps(b.get('input'))[:200]})")
    return "\n".join(lines)[-limit:]


def summarize(cfg, transcript_path, session_id, proj):
    text = transcript_text(transcript_path)
    if not cfg or len(text) < 400:
        return  # trivial session, nothing worth remembering
    # Runs on the user's own Claude plan. ENGRAM_CHILD stops this session's hooks from recording or summarising itself.
    r = subprocess.run([shutil.which("claude") or "claude", "-p", SUMMARY_PROMPT, "--model", "haiku", "--no-session-persistence", "--tools", ""],
                       input=text, capture_output=True, text=True, timeout=300,
                       cwd=tempfile.gettempdir(), env={**os.environ, "ENGRAM_CHILD": "1"})
    if r.returncode or not r.stdout.strip():
        raise RuntimeError(f"claude -p exited {r.returncode}: {r.stderr.strip()[:500]}")
    call(cfg, "POST", "/api/memories",
         {"session_id": session_id, "project": proj, "kind": "summary", "text": redact(r.stdout.strip())}, timeout=15)


def search(cfg, words):
    if not cfg:
        return print(f"Engram isn't set up: {CONFIG} is missing. Copy the setup command from your Engram dashboard.")
    rows = json.loads(call(cfg, "GET", "/api/memories?" + urllib.parse.urlencode({"q": words, "limit": 40})))
    for m in reversed(rows):
        print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(m['created']))} [{m['project']}] {m['kind']}: {m['text']}")
    print(f"({len(rows)} matches)" if rows else "No matching memories.")


def main(cmd, args):
    if os.environ.get("ENGRAM_CHILD"):
        return  # inside our own summariser session
    cfg = load_config()
    if cmd == "search":
        return search(cfg, " ".join(args))
    if cmd == "summarize":
        return summarize(cfg, *args)
    if not cfg:
        return
    ev = json.load(sys.stdin)
    proj = project(ev.get("cwd"))
    if cmd == "start":
        ctx = call(cfg, "GET", "/api/context?" + urllib.parse.urlencode({"project": proj}))
        if ctx:
            print(f'{ctx}\n\nTo search older memory across all projects, run: "{sys.executable}" "{os.path.abspath(__file__)}" search <words>')
    elif cmd == "prompt":
        save(cfg, ev, proj, "prompt", ev.get("prompt") or "")
    elif cmd == "tool":
        save(cfg, ev, proj, "tool", describe(ev.get("tool_name", ""), ev.get("tool_input") or {}))
    elif cmd == "end" and ev.get("transcript_path") and shutil.which("claude"):
        # Summarising takes a while: detach so Claude Code can exit now. Failures land in ~/.engram.log.
        with open(LOG, "a") as log:
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "summarize", ev["transcript_path"],
                              ev.get("session_id", ""), proj],
                             start_new_session=True, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             creationflags=0x00000008 | 0x00000200 if os.name == "nt" else 0)  # Windows: DETACHED_PROCESS | NEW_PROCESS_GROUP


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2:])
    except Exception as e:
        print(f"engram {time.strftime('%Y-%m-%d %H:%M')}: {e}", file=sys.stderr)
