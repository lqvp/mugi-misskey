#!/usr/bin/env python3
"""Misskey CLI harness (stdlib only). Token: env MISSKEY_MUGI_TOKEN (or MISSKEY_TOKEN)."""
import argparse, json, mimetypes, os, sys, time, uuid, urllib.request, urllib.error

HOST = os.environ.get("MISSKEY_HOST", "https://misskey.example.com").rstrip("/")
# Some Cloudflare-fronted instances (e.g. misskey.vip) return 403 to the default "Python-urllib" User-Agent.
UA = "mugi-misskey-harness/1.0"


def token():
    t = os.environ.get("MISSKEY_MUGI_TOKEN") or os.environ.get("MISSKEY_TOKEN")
    if not t:
        sys.exit("error: set MISSKEY_MUGI_TOKEN (bind the token secret in exec env, never write it to a file)")
    return t


def _send(req, retries=3):
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code == 429 and i < retries - 1:
                time.sleep(2 ** (i + 1))
                continue
            try:
                err = json.loads(body).get("error", body)
            except ValueError:
                err = body[:500]
            raise SystemExit(f"HTTP {e.code} {req.full_url}: {json.dumps(err, ensure_ascii=False)}")


def api(endpoint, params=None, auth=True):
    """POST /api/<endpoint> with JSON params; returns the decoded response."""
    data = dict(params or {})
    headers = {"Content-Type": "application/json", "User-Agent": UA}
    if auth:
        headers["Authorization"] = "Bearer " + token()
    req = urllib.request.Request(f"{HOST}/api/{endpoint.lstrip('/')}",
                                 data=json.dumps(data).encode(), headers=headers, method="POST")
    return _send(req)


def upload(path, name=None, folder_id=None, sensitive=False, comment=None):
    """Upload a local file to the drive (drive/files/create); returns the DriveFile."""
    b = uuid.uuid4().hex
    fields = {"name": name or os.path.basename(path), "isSensitive": str(sensitive).lower()}
    if folder_id:
        fields["folderId"] = folder_id
    if comment:
        fields["comment"] = comment
    parts = []
    for k, v in fields.items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{fields["name"]}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n".encode() + f.read() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"{HOST}/api/drive/files/create", data=b"".join(parts), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}",
                                          "Authorization": "Bearer " + token(), "User-Agent": UA})
    return _send(req)


def resolve_user(acct):
    """'@user' or '@user@host' -> user object."""
    u, _, h = acct.lstrip("@").partition("@")
    p = {"username": u}
    if h:
        p["host"] = h
    return api("users/show", p)


def with_mention(text, author, my_username):
    """Prefix @user or @user@host unless the author is ourselves or already mentioned.

    Misskey only notifies a reply's author when they are mentioned (e.g. when
    replying under our own note)."""
    if text is None or author["username"] == my_username:
        return text
    acct = "@" + author["username"] + ("@" + author["host"] if author.get("host") else "")
    return text if text.startswith(acct) else acct + " " + text


def fmt_note(n):
    u = n.get("user", {})
    acct = "@" + u.get("username", "?") + ("@" + u["host"] if u.get("host") else "")
    text = n.get("text") or ""
    if n.get("renote") and not text:
        text = "RN: " + (n["renote"].get("text") or "")
    files = f" [{len(n['files'])} file(s)]" if n.get("files") else ""
    return f"{n['id']} {n.get('createdAt','')[:19]} {acct}: {text}{files}"


def out(obj, raw):
    if raw or not isinstance(obj, list) or not obj or "createdAt" not in obj[0] or "text" not in obj[0]:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        for n in obj:
            print(fmt_note(n))


def main():
    p = argparse.ArgumentParser(description="Misskey harness")
    p.add_argument("--raw", action="store_true", help="print raw JSON")
    s = p.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("api", help="call any endpoint: api <endpoint> [json|@file]")
    a.add_argument("endpoint"); a.add_argument("params", nargs="?", default="{}")
    a.add_argument("--noauth", action="store_true")
    s.add_parser("me")
    n = s.add_parser("note", help="post a note")
    n.add_argument("text", nargs="?")
    n.add_argument("--cw"); n.add_argument("--visibility", default="public",
                                           choices=["public", "home", "followers", "specified"])
    n.add_argument("--reply"); n.add_argument("--renote"); n.add_argument("--file", action="append", default=[],
                                                                          help="local path or drive file id")
    n.add_argument("--to", action="append", default=[], help="@user for visibility=specified")
    n.add_argument("--local-only", action="store_true")
    s.add_parser("delete").add_argument("note_id")
    r = s.add_parser("react"); r.add_argument("note_id"); r.add_argument("reaction")
    t = s.add_parser("tl", help="timeline"); t.add_argument("kind", nargs="?", default="home",
                                                            choices=["home", "local", "hybrid", "global"])
    t.add_argument("-n", type=int, default=20)
    nt = s.add_parser("notifs"); nt.add_argument("-n", type=int, default=20)
    us = s.add_parser("user", help="show user + recent notes"); us.add_argument("acct"); us.add_argument("-n", type=int, default=10)
    for c in ("follow", "unfollow"):
        s.add_parser(c).add_argument("acct")
    up = s.add_parser("upload"); up.add_argument("path"); up.add_argument("--sensitive", action="store_true")
    pr = s.add_parser("profile", help="update profile (i/update)")
    pr.add_argument("--name"); pr.add_argument("--bio"); pr.add_argument("--avatar", help="local path or drive file id")
    pr.add_argument("--banner", help="local path or drive file id"); pr.add_argument("--location")
    pr.add_argument("--field", action="append", default=[], help="name=value (repeatable, replaces all fields)")
    pr.add_argument("--bot", choices=["true", "false"])
    pr.add_argument("--pin", help="note id to pin")
    o = p.parse_args()

    def fid(x):
        return upload(x)["id"] if os.path.exists(x) else x

    if o.cmd == "api":
        prm = o.params
        if prm.startswith("@"):
            prm = open(prm[1:], encoding="utf-8").read()
        res = api(o.endpoint, json.loads(prm), auth=not o.noauth)
    elif o.cmd == "me":
        res = api("i")
        if not o.raw:
            res = {k: res.get(k) for k in ("id", "username", "name", "description", "avatarUrl", "bannerUrl",
                                           "fields", "isBot", "notesCount", "followersCount", "followingCount")}
    elif o.cmd == "note":
        prm = {"visibility": o.visibility}
        if o.text is not None:
            prm["text"] = sys.stdin.read() if o.text == "-" else o.text
        if o.cw: prm["cw"] = o.cw
        if o.reply:
            prm["replyId"] = o.reply
            author = api("notes/show", {"noteId": o.reply})["user"]
            if prm.get("text") is not None:
                prm["text"] = with_mention(prm["text"], author, api("i")["username"])
        if o.renote: prm["renoteId"] = o.renote
        if o.file: prm["fileIds"] = [fid(f) for f in o.file]
        if o.to: prm["visibleUserIds"] = [resolve_user(x)["id"] for x in o.to]
        if o.local_only: prm["localOnly"] = True
        res = api("notes/create", prm)["createdNote"]
        if not o.raw:
            res = {"id": res["id"], "url": f"{HOST}/notes/{res['id']}"}
    elif o.cmd == "delete":
        res = api("notes/delete", {"noteId": o.note_id}) or {"ok": True}
    elif o.cmd == "react":
        res = api("notes/reactions/create", {"noteId": o.note_id, "reaction": o.reaction}) or {"ok": True}
    elif o.cmd == "tl":
        ep = {"home": "notes/timeline", "local": "notes/local-timeline", "hybrid": "notes/hybrid-timeline",
              "global": "notes/global-timeline"}[o.kind]
        res = api(ep, {"limit": o.n})
    elif o.cmd == "notifs":
        res = api("i/notifications", {"limit": o.n})
        if not o.raw:
            for x in res:
                who = "@" + x["user"]["username"] if x.get("user") else ""
                txt = (x.get("note") or {}).get("text") or ""
                print(f"{x['createdAt'][:19]} {x['type']} {who} {x.get('reaction') or ''} {txt[:80]}")
            return
    elif o.cmd == "user":
        u = resolve_user(o.acct)
        print(json.dumps({k: u.get(k) for k in ("id", "username", "host", "name", "description",
                                                  "followersCount", "notesCount")}, ensure_ascii=False, indent=2))
        res = api("users/notes", {"userId": u["id"], "limit": o.n})
    elif o.cmd in ("follow", "unfollow"):
        uid = resolve_user(o.acct)["id"]
        res = api("following/create" if o.cmd == "follow" else "following/delete", {"userId": uid})
        if not o.raw:
            res = {"ok": True, "user": o.acct}
    elif o.cmd == "upload":
        res = upload(o.path, sensitive=o.sensitive)
        if not o.raw:
            res = {"id": res["id"], "url": res["url"]}
    elif o.cmd == "profile":
        prm = {}
        if o.name is not None: prm["name"] = o.name
        if o.bio is not None: prm["description"] = o.bio
        if o.location is not None: prm["location"] = o.location
        if o.avatar: prm["avatarId"] = fid(o.avatar)
        if o.banner: prm["bannerId"] = fid(o.banner)
        if o.field: prm["fields"] = [dict(zip(("name", "value"), f.split("=", 1))) for f in o.field]
        if o.bot: prm["isBot"] = o.bot == "true"
        if prm:
            res = api("i/update", prm)
        if o.pin:
            res = api("i/pin", {"noteId": o.pin})
        if not prm and not o.pin:
            sys.exit("nothing to update")
        if not o.raw:
            res = {k: res.get(k) for k in ("username", "name", "description", "avatarUrl", "fields", "isBot")}
    out(res, o.raw)


if __name__ == "__main__":
    main()
