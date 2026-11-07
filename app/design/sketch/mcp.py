import json, os, urllib.request, urllib.error
def _d(): return json.load(open(os.path.join(os.environ['LOCALAPPDATA'], 'OpenPencil', 'mcp.json')))
def call(name, **args):
    D = _d()
    body = {"command": "tool", "args": {"name": name, "args": args, "agent": {"name": "claude-code"}}}
    req = urllib.request.Request(f"http://127.0.0.1:{D['httpPort']}/rpc", json.dumps(body).encode(),
        {"Authorization": f"Bearer {D['authToken']}", "Content-Type": "application/json"})
    try: r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    except urllib.error.HTTPError as e: raise RuntimeError(e.read().decode())
    if r.get("ok") is False: raise RuntimeError(r.get("error"))
    return r.get("result")
