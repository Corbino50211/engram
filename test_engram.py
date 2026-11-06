"""End-to-end self-check: python3 test_engram.py  (throwaway server on localhost, real hook subprocesses)."""
import json, os, subprocess, sys, tempfile, threading, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ["ENGRAM_DB"] = os.path.join(TMP, "test.db")
sys.path[:0] = [os.path.join(ROOT, "server"), os.path.join(ROOT, "plugin")]
import engram, server  # noqa: E402

server.init()
httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{httpd.server_port}"


def api(method, path, body=None, token=None):
    req = urllib.request.Request(URL + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(req) as r:
            status, raw, ctype = r.status, r.read().decode(), r.headers["Content-Type"]
    except urllib.error.HTTPError as e:
        status, raw, ctype = e.code, e.read().decode(), e.headers["Content-Type"]
    return status, json.loads(raw) if "json" in ctype else raw


def hook(args, payload, **env):
    return subprocess.run([sys.executable, os.path.join(ROOT, "plugin", "engram.py"), *args.split()],
                          input=json.dumps(payload), capture_output=True, text=True, check=True,
                          env={**os.environ, "HOME": TMP, **env}).stdout


# Invite-only signup
with server.db() as c:
    code = server.mint_invites(c, 1)[0]
assert api("POST", "/api/signup", {"code": "nope", "name": "alice"})[0] == 400
status, alice = api("POST", "/api/signup", {"code": code, "name": "alice"})
assert status == 200, alice
assert api("POST", "/api/signup", {"code": code, "name": "mallory"})[0] == 400, "invite reused"
assert api("GET", "/api/me")[0] == 401 and api("GET", "/api/me", token="forged")[0] == 401
A = alice["token"]

# Invite quota; a friend joins through one; names are unique ignoring case and a failed signup leaves the invite unused
codes = [api("POST", "/api/invites", token=A)[1]["code"] for _ in range(server.INVITES_PER_USER)]
assert api("POST", "/api/invites", token=A)[0] == 403
assert api("POST", "/api/signup", {"code": codes[1], "name": "ALICE"})[0] == 400
status, bob = api("POST", "/api/signup", {"code": codes[1], "name": "bob"})
assert status == 200, bob
B = bob["token"]
me = api("GET", "/api/me", token=A)[1]
assert {i["code"]: i["used_by"] for i in me["invites"]} == {codes[0]: None, codes[1]: "bob", codes[2]: None}

# Hooks record activity, with secrets redacted, per project; our own summariser session records nothing
with open(os.path.join(TMP, ".engram.json"), "w") as f:
    json.dump({"url": URL, "token": A}, f)
ev = {"session_id": "s1", "cwd": "/work/rocket"}
hook("prompt", {**ev, "prompt": "deploy with API_KEY=hunter2hunter2, Bearer abc.def and sk-ant-abcdefghijkl"})
hook("tool", {**ev, "tool_name": "Edit", "tool_input": {"file_path": "/work/rocket/main.py"}})
hook("tool", {**ev, "tool_name": "Bash", "tool_input": {"command": "pytest -q", "description": "Run tests"}})
hook("prompt", {**ev, "prompt": "should not be saved"}, ENGRAM_CHILD="1")
ctx = hook("start", ev)
assert "API_KEY=[redacted] Bearer [redacted] and [redacted]" in ctx, ctx
assert "hunter2" not in ctx and "abc.def" not in ctx and "sk-ant" not in ctx
assert "Edit /work/rocket/main.py" in ctx and "$ pytest -q  (Run tests)" in ctx and "should not be saved" not in ctx
assert "search <words>" in ctx
assert hook("start", {**ev, "cwd": "/work/other"}) == "", "projects are separate"
assert engram.redact("fix the token refresh logic") == "fix the token refresh logic"

# A summary replaces raw activity in context; re-summarising the same session keeps only the newest
for text in ("- first draft", "- Added retry to main.py\n- TODO: fix flaky test"):
    assert api("POST", "/api/memories", {"session_id": "s1", "project": "rocket", "kind": "summary", "text": text}, A)[0] == 200
ctx = hook("start", ev)
assert "Added retry" in ctx and "first draft" not in ctx and "pytest" not in ctx, ctx

# Search, isolation between users, delete
assert "Added retry" in hook("search retry", {})
hits = api("GET", "/api/memories?q=pytest", token=A)[1]
assert len(hits) == 1
assert api("GET", "/api/memories?q=pytest", token=B)[1] == []
assert api("DELETE", f"/api/memories/{hits[0]['id']}", token=B)[0] == 404
assert api("DELETE", f"/api/memories/{hits[0]['id']}", token=A)[0] == 200
assert api("GET", "/api/memories?q=pytest", token=A)[1] == []
assert api("GET", "/api/memories?limit=-1", token=A)[0] == 200

# Bad input is rejected, not stored
assert api("POST", "/api/memories", {"kind": "evil", "project": "x", "text": "y"}, A)[0] == 400
assert api("POST", "/api/memories", {"kind": ["prompt"], "project": "x", "text": "y"}, A)[0] == 400
assert api("GET", "/api/memories?limit=abc", token=A)[0] == 400

# Transcript -> summariser input keeps the conversation and drops tool output and meta noise
tp = os.path.join(TMP, "t.jsonl")
with open(tp, "w") as f:
    for e in [{"type": "user", "message": {"role": "user", "content": "add retries"}},
              {"type": "assistant", "message": {"role": "assistant", "content": [
                  {"type": "text", "text": "Adding them."}, {"type": "tool_use", "name": "Edit", "input": {"file_path": "main.py"}}]}},
              {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "SECRET FILE BODY"}]}},
              {"type": "user", "isMeta": True, "message": {"role": "user", "content": "meta noise"}}, 42]:
        f.write(json.dumps(e) + "\n")
    f.write("not json\n")
t = engram.transcript_text(tp)
assert "user: add retries" in t and "assistant: Adding them." in t and "main.py" in t, t
assert "SECRET" not in t and "meta" not in t

assert api("GET", "/")[0] == 200
print("ok")
