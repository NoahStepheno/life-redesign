#!/usr/bin/env python3
"""life-redesign CLI: the single seam for Life Redesign state and data.

Data dir: $LIFE_REDESIGN_HOME, default ~/.life-redesign.
Current time: $LIFE_REDESIGN_NOW (ISO 8601, e.g. 2026-01-15T09:00:00), default real time.
All commands print JSON on stdout; errors go to stderr with a non-zero exit.
"""
import argparse
import copy
import datetime
import json
import os
import re
import sys

INITIAL_STATE = {
    "phase": "new",
    "protocol": {"started_at": None, "part": None, "question": None},
    "streak": {"drift": 0, "unrecorded": 0},
    "dnd_dates": [],
    "notify": {
        "client": "claude -p",
        "times": {
            "morning": "08:30",
            "evening": "21:30",
            "random_window": ["11:00", "17:00"],
        },
    },
    "privacy_ack": False,
}


class CliError(Exception):
    pass


def data_dir():
    override = os.environ.get("LIFE_REDESIGN_HOME")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".life-redesign")


def now():
    raw = os.environ.get("LIFE_REDESIGN_NOW")
    if not raw:
        return datetime.datetime.now().replace(microsecond=0)
    try:
        return datetime.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        raise CliError("invalid LIFE_REDESIGN_NOW: %r (want YYYY-MM-DDTHH:MM:SS)" % raw)


def state_path():
    return os.path.join(data_dir(), "state.json")


def load_state():
    path = state_path()
    if not os.path.isfile(path):
        raise CliError("not initialized: run `init` first")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    os.makedirs(data_dir(), exist_ok=True)
    with open(state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False))


def report(state):
    return {
        "phase": state["phase"],
        "privacy_required": not state.get("privacy_ack", False),
        "data_dir": data_dir(),
        "now": now().isoformat(),
    }


def cmd_init(args):
    now()  # validate injected time
    if os.path.isfile(state_path()):
        state = load_state()
    else:
        state = copy.deepcopy(INITIAL_STATE)
        for sub in ("protocol", "log"):
            os.makedirs(os.path.join(data_dir(), sub), exist_ok=True)
        save_state(state)
    if args.ack_privacy and not state.get("privacy_ack"):
        state["privacy_ack"] = True
        save_state(state)
    emit(report(state))


def cmd_ack_privacy(args):
    state = load_state()
    if not state.get("privacy_ack"):
        state["privacy_ack"] = True
        save_state(state)
    emit(report(state))


def cmd_status(args):
    emit(report(load_state()))


def cmd_now(args):
    emit({"now": now().isoformat()})


APPEND_TARGETS = {
    "anti-vision": "anti-vision.md",
    "vision": "vision.md",
    "goals": "goals.md",
}
GOAL_SECTIONS = (
    ("Year Goal", "year_goal"),
    ("Month Project", "month_project"),
    ("Constraints", "constraints"),
)
# Verbs and flags that ask to rewrite or remove existing content. They are not
# part of the command surface; they are recognised only to be rejected loudly.
FORBIDDEN_WORDS = {
    "overwrite", "replace", "edit", "update", "set", "delete", "remove", "rm",
    "reset", "archive", "amend", "truncate", "clear", "write", "modify",
    "rewrite", "undo", "revert", "force",
}
VERSION_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})[ \t]*$")
SECTION_RE = re.compile(r"^### (.+?)[ \t]*$")


def reject_destructive(argv):
    value_flags = {"--text", "--year-goal", "--month-project", "--constraints"}
    checked = []
    skip = False
    for i, tok in enumerate(argv):
        if skip:
            skip = False
        elif tok in value_flags:
            skip = True
        elif i == 0 or tok.startswith("--"):
            checked.append(tok)
    for tok in checked:
        word = tok.lstrip("-").split("=", 1)[0].lower()
        if word in FORBIDDEN_WORDS:
            raise CliError(
                "%r is not supported: records are append-only (ADR-0001). "
                "Use `append` to add a new dated version; old versions are "
                "never overwritten or deleted. Archive by renaming the file "
                "by hand." % tok)


def parse_versions(text):
    versions = []
    for line in text.split("\n"):
        m = VERSION_RE.match(line)
        if m:
            versions.append({"date": m.group(1), "lines": []})
        elif versions:
            versions[-1]["lines"].append(line)
    out = []
    for v in versions:
        out.append({"date": v["date"], "content": "\n".join(v["lines"]).strip()})
    return out


def parse_sections(content):
    sections = {}
    name = None
    for line in content.split("\n"):
        m = SECTION_RE.match(line)
        if m:
            name = m.group(1)
            sections[name] = []
        elif name is not None:
            sections[name].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def read_versions(target):
    path = os.path.join(data_dir(), APPEND_TARGETS[target])
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        versions = parse_versions(f.read())
    if target == "goals":
        for v in versions:
            v["sections"] = parse_sections(v["content"])
    return versions


def check_body(value, label, pattern):
    if not value.strip():
        raise CliError("%s is empty" % label)
    for line in value.split("\n"):
        if re.match(pattern, line):
            raise CliError(
                "%s contains a version/section heading line (%r); "
                "headings are written only by the CLI" % (label, line))
    return value.strip()


def cmd_append(args):
    load_state()
    target = args.target
    path = os.path.join(data_dir(), APPEND_TARGETS[target])
    if target == "goals":
        if args.text is not None:
            raise CliError("goals takes --year-goal/--month-project/--constraints, not --text")
        given = {}
        for title, attr in GOAL_SECTIONS:
            value = getattr(args, attr)
            if value is not None:
                given[title] = check_body(value, "--" + attr.replace("_", "-"), r"^#{1,3} ")
        if not given:
            raise CliError("goals needs at least one of --year-goal, --month-project, --constraints")
        body = goals_body(given)
    else:
        for _, attr in GOAL_SECTIONS:
            if getattr(args, attr) is not None:
                raise CliError("--%s is only valid for goals" % attr.replace("_", "-"))
        if args.text is None:
            raise CliError("--text is required")
        body = check_body(args.text, "--text", r"^## ")
    write_version(path, body)
    versions = read_versions(target)
    emit({"target": target, "date": versions[-1]["date"], "versions": len(versions)})


def write_version(path, body):
    existing = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            existing = f.read()
    entry = "## %s\n%s\n" % (now().date().isoformat(), body)
    if existing.strip():
        # Separator only; existing bytes are never rewritten (mode "a").
        entry = ("\n" if existing.endswith("\n") else "\n\n") + entry
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)


def goals_body(given):
    """Merge given sections into the current goals version; return new body."""
    versions = read_versions("goals")
    merged = dict(versions[-1]["sections"]) if versions else {}
    merged.update(given)
    return "\n\n".join("### %s\n%s" % (t, merged[t])
                       for t, _ in GOAL_SECTIONS if t in merged)


def cmd_show(args):
    versions = read_versions(args.target)
    emit({"target": args.target,
          "current": versions[-1] if versions else None,
          "versions": versions})


# ---- B tier: snapshot and update blocks (PROTOCOL section 9) ----

BLOCK_START = "=== LIFE-REDESIGN UPDATE ==="
BLOCK_END = "=== END ==="
BLOCK_MODES = ("create", "append")
LOG_PATH_RE = re.compile(r"^(log|protocol)/[^/]+\.md$")
VERDICT_RE = re.compile(r"^- 判定[:：]\s*(.+?)\s*$", re.M)
LOG_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


def current_text(target):
    versions = read_versions(target)
    return versions[-1]["content"] if versions else None


def recent_verdicts(days=7):
    log_dir = os.path.join(data_dir(), "log")
    if not os.path.isdir(log_dir):
        return []
    today = now().date()
    first = today - datetime.timedelta(days=days - 1)
    out = []
    for name in sorted(os.listdir(log_dir)):
        m = LOG_NAME_RE.match(name)
        if not m:
            continue
        try:
            d = datetime.datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if not first <= d <= today:
            continue
        with open(os.path.join(log_dir, name), encoding="utf-8") as f:
            found = VERDICT_RE.findall(f.read())
        if found:
            out.append({"date": m.group(1), "verdict": found[-1]})
    return out


def cmd_snapshot(args):
    state = load_state()
    goals = read_versions("goals")
    streak = state.get("streak") or {}
    emit({
        "generated": now().isoformat(),
        "vision": current_text("vision"),
        "anti_vision": current_text("anti-vision"),
        "goals": dict(goals[-1]["sections"]) if goals else {},
        "verdicts": recent_verdicts(),
        "streak": {"drift": streak.get("drift", 0),
                   "unrecorded": streak.get("unrecorded", 0)},
    })


def parse_blocks(text):
    lines = text.replace("\r\n", "\n").split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        if lines[i].strip() != BLOCK_START:
            i += 1
            continue
        n = len(blocks) + 1
        i += 1
        header = {}
        while True:
            if i >= len(lines) or lines[i].strip() in (BLOCK_END, BLOCK_START):
                raise CliError("block %d: missing '---' separator after header" % n)
            line = lines[i]
            i += 1
            if line.strip() == "---":
                break
            if not line.strip():
                continue
            key, sep, value = line.partition(":")
            if not sep or key.strip() not in ("file", "mode"):
                raise CliError("block %d: unrecognised header line %r "
                                   "(headers are 'file:' and 'mode:', then a '---' line)" % (n, line))
            header[key.strip()] = value.strip()
        body = []
        while True:
            if i >= len(lines) or lines[i].strip() == BLOCK_START:
                raise CliError("block %d: missing %r terminator" % (n, BLOCK_END))
            line = lines[i]
            i += 1
            if line.strip() == BLOCK_END:
                break
            body.append(line)
        blocks.append({"n": n, "file": header.get("file"),
                       "mode": header.get("mode"), "body": "\n".join(body)})
    if not blocks:
        raise CliError("no update block found (expected %r ... %r)" % (BLOCK_START, BLOCK_END))
    return blocks


def resolve_target(n, rel):
    root = os.path.realpath(data_dir())
    parts = rel.split("/")
    if (os.path.isabs(rel) or "\\" in rel or "\x00" in rel
            or any(p in ("", ".", "..") for p in parts)):
        raise CliError("block %d: path %r is outside the data dir or malformed" % (n, rel))
    full = os.path.join(root, *parts)
    real = os.path.realpath(full)  # follows symlinks, including the file itself
    if os.path.commonpath([root, real]) != root:
        raise CliError("block %d: path %r escapes the data dir" % (n, rel))
    if rel not in ("vision.md", "anti-vision.md", "goals.md") and not LOG_PATH_RE.match(rel):
        raise CliError(
            "block %d: file %r is not an allowed target (vision.md, anti-vision.md, "
            "goals.md, log/*.md, protocol/*.md)" % (n, rel))
    return full


def validate_block(b, seen):
    n = b["n"]
    if not b["file"]:
        raise CliError("block %d: missing 'file' header" % n)
    if not b["mode"]:
        raise CliError("block %d: missing 'mode' header" % n)
    if b["mode"] not in BLOCK_MODES:
        raise CliError("block %d: mode %r not allowed; only create or append "
                       "(records are append-only, ADR-0001)" % (n, b["mode"]))
    full = resolve_target(n, b["file"])
    body = b["body"].strip("\n")
    if not body.strip():
        raise CliError("block %d: body is empty" % n)
    exists = os.path.exists(full) or full in seen
    if b["mode"] == "create" and exists:
        raise CliError("block %d: cannot create %s: file already exists "
                       "(use mode: append)" % (n, b["file"]))
    kind = b["file"] if b["file"] in APPEND_TARGETS.values() else "log"
    if kind == "log":
        if b["mode"] == "append" and not exists:
            raise CliError("block %d: cannot append to %s: file does not exist "
                           "(use mode: create)" % (n, b["file"]))
        return {"full": full, "kind": kind, "mode": b["mode"], "body": body}
    if kind == "goals.md":
        sections = {}
        name = None
        for line in body.split("\n"):
            m = SECTION_RE.match(line)
            if m:
                name = m.group(1)
                if name not in dict(GOAL_SECTIONS):
                    raise CliError("block %d: unknown goals section %r" % (n, name))
                sections[name] = []
            elif name is None:
                if line.strip():
                    raise CliError("block %d: goals content must be under a "
                                   "'### Year Goal|Month Project|Constraints' section" % n)
            else:
                sections[name].append(line)
        if not sections:
            raise CliError("block %d: goals block needs at least one '### ' section" % n)
        given = {}
        for name, v in sections.items():
            given[name] = check_body("\n".join(v), "block %d section %r" % (n, name),
                                     r"^#{1,3} ")
        return {"full": full, "kind": kind, "mode": b["mode"], "given": given}
    body = check_body(body, "block %d body" % n, r"^## ")
    return {"full": full, "kind": kind, "mode": b["mode"], "body": body}


def cmd_apply_block(args):
    load_state()
    if args.file:
        try:
            with open(args.file, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            raise CliError("cannot read %s: %s" % (args.file, e))
    else:
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    blocks = parse_blocks(text)
    seen = set()
    plan = []
    for b in blocks:  # validate everything before writing anything
        item = validate_block(b, seen)
        seen.add(item["full"])
        plan.append(item)
    for b, item in zip(blocks, plan):
        full = item["full"]
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if item["kind"] == "goals.md":
            write_version(full, goals_body(item["given"]))
        elif item["kind"] != "log":
            write_version(full, item["body"])
        else:
            existing = ""
            if os.path.isfile(full):
                with open(full, encoding="utf-8") as f:
                    existing = f.read()
            sep = "\n" if existing and not existing.endswith("\n") else ""
            with open(full, "a", encoding="utf-8") as f:
                f.write(sep + item["body"] + "\n")
    emit({"applied": [{"file": b["file"], "mode": b["mode"]} for b in blocks]})


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    try:
        reject_destructive(argv)
    except CliError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(prog="life_redesign")
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    p = sub.add_parser("init", help="create data dir and initial state (idempotent)")
    p.add_argument("--ack-privacy", action="store_true")
    p.set_defaults(func=cmd_init)
    sub.add_parser("ack-privacy", help="record privacy acknowledgement").set_defaults(func=cmd_ack_privacy)
    sub.add_parser("status", help="show phase and privacy status").set_defaults(func=cmd_status)
    sub.add_parser("now", help="show the effective current time").set_defaults(func=cmd_now)
    p = sub.add_parser("append", help="append a new dated version (never overwrites)")
    p.add_argument("target", choices=sorted(APPEND_TARGETS))
    p.add_argument("--text")
    p.add_argument("--year-goal", dest="year_goal")
    p.add_argument("--month-project", dest="month_project")
    p.add_argument("--constraints")
    p.set_defaults(func=cmd_append)
    p = sub.add_parser("show", help="show all versions; current is the last")
    p.add_argument("target", choices=sorted(APPEND_TARGETS))
    p.set_defaults(func=cmd_show)
    sub.add_parser("snapshot", help="export state snapshot for pasting into a chat app").set_defaults(func=cmd_snapshot)
    p = sub.add_parser("apply-block", help="apply update block(s) from stdin or --file (create/append only)")
    p.add_argument("--file")
    p.set_defaults(func=cmd_apply_block)
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except CliError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
