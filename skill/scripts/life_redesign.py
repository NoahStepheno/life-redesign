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
import plistlib
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

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
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except ValueError as e:
        raise CliError("state.json is corrupt (%s): %s" % (e, path))


def save_state(state):
    """Write to a temp file in the same dir, then atomically replace."""
    os.makedirs(data_dir(), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=data_dir())
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, state_path())
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


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
# Sections a goals version can hold. Daily Levers is written only by `plan`
# (no append flag) but `append` must carry it forward too.
ALL_GOAL_SECTIONS = GOAL_SECTIONS + (("Daily Levers", "daily_levers"),)
REASON_RE = re.compile(r"^_Reason: (.*)_$")
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
    value_flags = {"--text", "--year-goal", "--month-project", "--constraints",
                   "--why", "--period"}
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
                "never overwritten or deleted. The CLI never deletes anything: "
                "it only marks (renames) one-day-protocol segments, when a "
                "protocol is shelved or a feeling is confirmed faded. "
                "Archiving the whole data directory is done by hand."
                % tok)


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
        content = "\n".join(v["lines"]).strip()
        item = {"date": v["date"]}
        # A trailing `_Reason: ..._` line is a plan-change reason, not content.
        head, _, last = content.rpartition("\n")
        m = REASON_RE.match(last.strip())
        if m:
            content = head.strip()
            item["reason"] = m.group(1)
        item["content"] = content
        out.append(item)
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


def append_entry(path, entry, blank_line=True, sync=False):
    """The one append primitive: add `entry` to the end of `path`.

    Existing bytes are never rewritten (mode "a"); only a separator is added
    in front of the new entry. blank_line=True separates entries with a blank
    line (and adds none when the file is empty or whitespace-only);
    blank_line=False only guarantees the entry starts on a fresh line.
    sync=True fsyncs before returning. Returns the previous file text.
    """
    existing = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            existing = f.read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if blank_line:
        if existing.strip():
            entry = ("\n" if existing.endswith("\n") else "\n\n") + entry
    elif existing and not existing.endswith("\n"):
        entry = "\n" + entry
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)
        if sync:
            f.flush()
            os.fsync(f.fileno())
    return existing


def write_version(path, body):
    append_entry(path, "## %s\n%s\n" % (now().date().isoformat(), body))


def reason_entry(body, reason):
    """Text of a plan version that carries a reason (shared by `plan change`
    and update blocks): `## <date>`, body, final `_Reason: <why>_` line."""
    return "## %s\n%s\n_Reason: %s_\n" % (now().date().isoformat(), body, reason)


def split_reason(body):
    """Split an update-block body into (content, reason): the body must END
    with a non-empty `_Reason: <why>_` line. Returns (None, None) otherwise."""
    content, _, last = body.rstrip().rpartition("\n")
    m = REASON_RE.match(last.strip())
    reason = " ".join(m.group(1).split()) if m else ""
    if not reason:
        return None, None
    return content, reason


def goals_text(sections):
    """Render goals sections (title -> body) in canonical order."""
    return "\n\n".join("### %s\n%s" % (t, sections[t])
                        for t, _ in ALL_GOAL_SECTIONS if t in sections)


def goals_body(given):
    """Merge given sections into the current goals version; return new body."""
    versions = read_versions("goals")
    merged = dict(versions[-1]["sections"]) if versions else {}
    merged.update(given)
    return goals_text(merged)


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


def current_text(target):
    versions = read_versions(target)
    return versions[-1]["content"] if versions else None


def recent_verdicts(days=7):
    today = now().date()
    first = (today - datetime.timedelta(days=days - 1)).isoformat()
    return [{"date": d, "verdict": v} for d, v in log_verdicts()
            if v is not None and first <= d <= today.isoformat()]


def cmd_snapshot(args):
    state = load_state()
    if state.get("streak_cursor") is not None:
        # Same as `streak status`: finalize missed days so counters are current.
        state = backfill_unrecorded(state)
    goals = read_versions("goals")
    streak = state.get("streak") or {}
    emit({
        "generated": now().isoformat(),
        "vision": current_text("vision"),
        "anti_vision": current_text("anti-vision"),
        "goals": dict(goals[-1]["sections"]) if goals else {},
        "verdicts": recent_verdicts(),
        "streak": {"drift": streak.get("drift", 0),
                   "unrecorded": streak.get("unrecorded", 0),
                   "escalation": bool(state.get("escalation"))},
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


def check_block_log_date(n, rel, state):
    """log/<name>.md written through an update block: the name must be a real
    date, not after today, not before the protocol-completion day (which is
    itself allowed: it is the baseline)."""
    day = rel[len("log/"):-len(".md")]
    try:
        if not DATE_RE.match(day):
            raise ValueError(day)
        datetime.datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise CliError("block %d: %s is not a valid date: log files are named "
                       "log/YYYY-MM-DD.md" % (n, rel))
    if day > now().date().isoformat():
        raise CliError("block %d: %s is in the future (today is %s): a log "
                       "cannot be written ahead of its day"
                       % (n, rel, now().date().isoformat()))
    start = state.get("activated_on") or state.get("streak_cursor")
    if start and day < start:
        raise CliError("block %d: %s is before the protocol was completed (%s): "
                       "there is no log for days before that" % (n, rel, start))


def validate_block(b, seen, ctx):
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
    reason = None
    if b["file"] in APPEND_TARGETS.values():
        # plan files: a change needs a why, exactly as `plan change` (issue #22)
        body, reason = split_reason(body)
        if reason is None:
            raise CliError(
                "block %d: %s needs a reason: end the block with a non-empty "
                "line '_Reason: <why this is changing>_'" % (n, b["file"]))
        if not body.strip():
            raise CliError("block %d: body is empty" % n)
        if os.path.isfile(full) and full not in seen:
            with open(full, encoding="utf-8") as f:
                if not f.read().strip():
                    exists = False  # an empty plan file takes a first version
    if b["mode"] == "create" and exists:
        raise CliError("block %d: cannot create %s: file already exists "
                       "(use mode: append)" % (n, b["file"]))
    kind = b["file"] if b["file"] in APPEND_TARGETS.values() else "log"
    if kind == "log":
        if b["mode"] == "append" and not exists:
            raise CliError("block %d: cannot append to %s: file does not exist "
                           "(use mode: create)" % (n, b["file"]))
        verdict = None
        if b["file"].startswith("log/"):
            # same rules as `checkin`; seen[full] is the day's verdict after
            # earlier blocks of this batch
            if full in seen:
                verdict = seen[full]
            elif os.path.isfile(full):
                with open(full, encoding="utf-8") as f:
                    verdict = current_verdict(f.read())
            check_block_log_date(n, b["file"], ctx)
            verdict = check_block_verdicts(n, b["file"], body, verdict)
        lines = body.split("\n")
        away = [m.group(1) for m in (AWAY_RE.match(x) for x in lines) if m]
        return {"full": full, "kind": kind, "mode": b["mode"], "body": body,
                "verdict": verdict, "n": n,
                "new_verdict": any(VERDICT_RE.match(x) for x in lines),
                "away": away}
    if kind == "goals.md":
        sections = {}
        name = None
        for line in body.split("\n"):
            m = SECTION_RE.match(line)
            if m:
                name = m.group(1)
                if name not in dict(ALL_GOAL_SECTIONS):
                    raise CliError("block %d: unknown goals section %r" % (n, name))
                sections[name] = []
            elif name is None:
                if line.strip():
                    raise CliError("block %d: goals content must be under a "
                                   "'### Year Goal|Month Project|Daily Levers|Constraints' section" % n)
            else:
                sections[name].append(line)
        if not sections:
            raise CliError("block %d: goals block needs at least one '### ' section" % n)
        given = {}
        for name, v in sections.items():
            given[name] = check_body("\n".join(v), "block %d section %r" % (n, name),
                                     r"^#{1,3} ")
        return {"full": full, "kind": kind, "mode": b["mode"], "given": given,
                "reason": reason}
    body = check_body(body, "block %d body" % n, r"^## ")
    return {"full": full, "kind": kind, "mode": b["mode"], "body": body,
            "reason": reason}


def check_block_silence_note(plan):
    """After silence (unrecorded days > 0, DND days excluded), a batch that
    writes a new verdict must also carry the 这几天发生了什么 line, exactly as
    `checkin record` demands --while-away. Silence is read without
    back-filling, so a rejected batch writes nothing."""
    writes = [p for p in plan if p.get("new_verdict")]
    if not writes:
        return
    away = [a for p in plan for a in p.get("away", [])]
    if any(a.strip() for a in away):
        return
    raise CliError(
        "block %d: you were silent: a block that writes a verdict must also "
        "say what happened in the missing days: add a non-empty line '%s <what "
        "happened>' to the block" % (writes[0]["n"], AWAY_PREFIX))


def cmd_apply_block(args):
    try:
        state = require_active(load_state())
    except CliError as e:
        raise CliError("update blocks are refused until the one-day protocol "
                       "is complete: %s" % e)
    silent = with_pending_unrecorded(state)["streak"]["unrecorded"] > 0
    if args.file:
        try:
            with open(args.file, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            raise CliError("cannot read %s: %s" % (args.file, e))
    else:
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    blocks = parse_blocks(text)
    seen = {}
    plan = []
    for b in blocks:  # validate everything before writing anything
        item = validate_block(b, seen, state)
        seen[item["full"]] = item.get("verdict")
        plan.append(item)
    if silent:
        check_block_silence_note(plan)
    for b, item in zip(blocks, plan):
        full = item["full"]
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if item["kind"] == "goals.md":
            append_entry(full, reason_entry(goals_body(item["given"]), item["reason"]))
        elif item["kind"] != "log":
            append_entry(full, reason_entry(item["body"], item["reason"]))
        else:
            append_entry(full, item["body"] + "\n", blank_line=False)
    out = {"applied": [{"file": b["file"], "mode": b["mode"]} for b in blocks]}
    if any(b["file"].startswith("log/") for b in blocks):
        # verdicts may have changed: back-fill and recompute exactly as checkin does
        state = backfill_unrecorded(load_state())
        recount_unrecorded(state)
        recompute_drift(state)
        save_state(state)
        out["streak"] = streak_view(state)
    emit(out)
# ---- plan: change vision / anti-vision / goals sections (PROTOCOL.md s.6) ----
# object -> (append target, goals section title or None)
PLAN_OBJECTS = {
    "vision": ("vision", None),
    "anti-vision": ("anti-vision", None),
    "year-goal": ("goals", "Year Goal"),
    "month-project": ("goals", "Month Project"),
    "daily-levers": ("goals", "Daily Levers"),
    "constraints": ("goals", "Constraints"),
}


def cmd_plan_change(args):
    state = load_state()
    require_active(state)
    target, section = PLAN_OBJECTS[args.object]
    why = " ".join((args.why or "").split())
    if not why:
        raise CliError("--why is required: say why this is changing")
    if args.text is None:
        raise CliError("--text is required")
    text = check_body(args.text, "--text", r"^#{1,3} " if section else r"^## ")
    versions = read_versions(target)
    current = versions[-1] if versions else None
    if section:
        merged = dict(current["sections"]) if current else {}
        old = merged.get(section)
        merged[section] = text
        body = goals_text(merged)
    else:
        old = current["content"] if current else None
        body = text
    path = os.path.join(data_dir(), APPEND_TARGETS[target])
    date = now().date().isoformat()
    append_entry(path, reason_entry(body, why))
    emit({"object": args.object, "date": date, "old": old, "new": text,
          "why": why, "versions": len(read_versions(target))})


# ---- one-day protocol: progress and resume (PROTOCOL.md section 4) ----------
# Question ids follow PROTOCOL.md numbering. Part 2 interrupts are not
# answered through this path: they are timed pushes, not sequential gates.
QUESTIONS = (["1.%d" % i for i in range(1, 15)]
             + ["3.%d" % i for i in range(1, 8)] + ["3.constraints"])
SHELVE_AFTER = datetime.timedelta(days=7)


def question_part(qid):
    return int(qid.split(".")[0])


def parse_ts(raw):
    return datetime.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")


def protocol_dir():
    return os.path.join(data_dir(), "protocol")


def empty_protocol():
    return {"started_at": None, "part": None, "question": None,
            "last_activity": None, "files": [], "redo": False}


def proto_of(state):
    p = state.setdefault("protocol", {})
    for k, v in empty_protocol().items():
        p.setdefault(k, v)
    return p


def move_marked(state, marker):
    """Rename the current segment's files to <name>.<marker>.md (never delete)."""
    p = proto_of(state)
    for name in p["files"]:
        src = os.path.join(protocol_dir(), name)
        if not os.path.isfile(src):
            continue
        stem = name[:-3]
        n = 1
        dst = "%s.%s.md" % (stem, marker)
        while os.path.exists(os.path.join(protocol_dir(), dst)):
            n += 1
            dst = "%s.%s.%d.md" % (stem, marker, n)
        os.rename(src, os.path.join(protocol_dir(), dst))
    p["files"] = []


def begin_segment(state):
    p = proto_of(state)
    t = now().isoformat()
    p.update({"started_at": t, "last_activity": t, "files": [],
              "part": 1, "question": QUESTIONS[0]})


def in_flight(state):
    """A segment is running: first run in progress, or a redo over active."""
    return state["phase"] == "protocol_in_progress" or (
        state["phase"] == "active" and proto_of(state)["redo"])


def feeling_check_required(state):
    p = proto_of(state)
    return (in_flight(state) and p["question"] != QUESTIONS[0]
            and p["last_activity"] is not None
            and parse_ts(p["last_activity"]).date() < now().date())


def refresh(state):
    """Apply the 7-day shelving rule lazily; persists when it changes state."""
    p = proto_of(state)
    if in_flight(state) and p["last_activity"] is not None \
            and now() - parse_ts(p["last_activity"]) > SHELVE_AFTER:
        move_marked(state, "archived")
        was_redo = p["redo"]
        state["protocol"] = empty_protocol()
        if not was_redo:
            state["phase"] = "protocol_shelved"
        save_state(state)
    return state


def require_active(state=None):
    """Gate for checkin/review/plan: return state, or refuse unless phase is active."""
    if state is None:
        state = load_state()
    state = refresh(state)
    if state["phase"] != "active":
        raise CliError(
            "the protocol is not complete (phase: %s): finish the protocol first "
            "(`protocol resume`, then answer every question)" % state["phase"])
    return state


def protocol_report(state):
    p = proto_of(state)
    q = p["question"]
    return {
        "phase": state["phase"],
        "redo": p["redo"],
        "part": p["part"],
        "question": q,
        "answered": QUESTIONS.index(q) if q in QUESTIONS else
        (len(QUESTIONS) if state["phase"] == "active" and not p["redo"] else 0),
        "total": len(QUESTIONS),
        "feeling_check_required": feeling_check_required(state),
    }


def cmd_protocol_status(args):
    emit(protocol_report(refresh(load_state())))


def cmd_protocol_gate(args):
    require_active()
    emit({"active": True})


def cmd_protocol_resume(args):
    state = refresh(load_state())
    if state["phase"] == "active" and not proto_of(state)["redo"]:
        raise CliError("protocol already complete; use `protocol redo` to redo it explicitly")
    if state["phase"] in ("new", "protocol_shelved"):
        state["phase"] = "protocol_in_progress"
        begin_segment(state)
        save_state(state)
    emit(protocol_report(state))


def cmd_protocol_confirm(args):
    state = refresh(load_state())
    if not feeling_check_required(state):
        raise CliError("no feeling check pending")
    p = proto_of(state)
    if args.feeling == "fresh":
        p["last_activity"] = now().isoformat()
    else:
        move_marked(state, "discarded")
        begin_segment(state)
    save_state(state)
    emit(protocol_report(state))


def cmd_protocol_redo(args):
    state = refresh(load_state())
    if state["phase"] != "active":
        raise CliError("redo needs a completed protocol (phase active); use `protocol resume`")
    if proto_of(state)["redo"]:
        raise CliError("a redo is already in progress; use `protocol resume`")
    begin_segment(state)
    proto_of(state)["redo"] = True
    save_state(state)
    emit(protocol_report(state))


def segment_file(state):
    p = proto_of(state)
    today = now().date().isoformat()
    for name in p["files"]:
        if name.startswith(today):
            return name
    n = 1
    name = today + ".md"
    while os.path.exists(os.path.join(protocol_dir(), name)):
        n += 1
        name = "%s.%d.md" % (today, n)
    p["files"].append(name)
    return name


FIRST_VERSION_REASON = "来自一天协议"
REDO_VERSION_REASON = "来自重做的一天协议"


def segment_answers(state):
    """Latest answer per question id in the running segment (verbatim)."""
    answers = {}
    for name in proto_of(state)["files"]:
        path = os.path.join(protocol_dir(), name)
        if not os.path.isfile(path):
            continue
        qid = None
        with open(path, encoding="utf-8") as f:
            for line in f.read().split("\n"):
                m = re.match(r"^## (\S+)[ \t]*$", line)
                if m:
                    qid = m.group(1)
                    answers[qid] = []
                elif qid is not None:
                    answers[qid].append(line)
    return {k: "\n".join(v).strip() for k, v in answers.items()}


def first_version_entries(answers, redo):
    """(append target, entry text) pairs built only from the user's answers."""
    for qid in ("1.13", "3.3", "3.4", "3.5", "3.6", "3.7", "3.constraints"):
        if not answers.get(qid):
            raise CliError("cannot write the plan files: no answer recorded for %s" % qid)
    reason = REDO_VERSION_REASON if redo else FIRST_VERSION_REASON
    date = now().date().isoformat()
    goals = {"Year Goal": answers["3.5"], "Month Project": answers["3.6"],
             "Daily Levers": answers["3.7"], "Constraints": answers["3.constraints"]}
    bodies = [
        ("anti-vision", answers["3.3"]),
        ("vision", "%s\n\nIdentity Statement: %s" % (answers["3.4"], answers["1.13"])),
        ("goals", goals_text(goals)),
    ]
    return [(t, "## %s\n%s\n_Reason: %s_\n" % (date, b, reason)) for t, b in bodies]


def write_group(entries):
    """Append every (path, entry) or none: undo the appends already done on failure."""
    undo = []
    try:
        for path, entry in entries:
            size = os.path.getsize(path) if os.path.isfile(path) else None
            undo.append((path, size))
            append_entry(path, entry, sync=True)
    except (OSError, UnicodeError) as e:
        rollback_group(undo)
        raise CliError("could not write the plan files (nothing was written): %s" % e)
    return undo


def rollback_group(undo):
    for path, size in reversed(undo):
        try:
            if size is None:
                if os.path.isfile(path):
                    os.remove(path)
            else:
                os.truncate(path, size)
        except OSError:
            pass


def cmd_protocol_answer(args):
    state = refresh(load_state())
    p = proto_of(state)
    qid = args.question_id
    if qid not in QUESTIONS:
        raise CliError("unknown question id %r (valid: %s)" % (qid, ", ".join(QUESTIONS)))
    if state["phase"] == "active" and not p["redo"]:
        raise CliError("protocol already complete; use `protocol redo` to redo it explicitly")
    if not in_flight(state):
        raise CliError("protocol not started: run `protocol resume` first")
    if feeling_check_required(state):
        raise CliError("overnight return: run `protocol confirm-feeling fresh|faded` first")
    if qid != p["question"]:
        raise CliError("answer questions in order: current question is %s" % p["question"])
    if args.text is None:
        raise CliError("--text is required")
    body = check_body(args.text, "--text", r"^## ")
    i = QUESTIONS.index(qid)
    last = i + 1 >= len(QUESTIONS)
    undo = []
    if last:
        # Final answer: write the first plan version from the user's own words,
        # all files or none, before the answer is recorded and phase flips.
        answers = segment_answers(state)
        answers[qid] = body
        entries = first_version_entries(answers, p["redo"])
        undo = write_group([(os.path.join(data_dir(), APPEND_TARGETS[t]), e)
                            for t, e in entries])
    name = segment_file(state)
    try:
        os.makedirs(protocol_dir(), exist_ok=True)
        path = os.path.join(protocol_dir(), name)
        append_entry(path, "## %s\n%s\n" % (qid, body), sync=True)
    except OSError as e:
        rollback_group(undo)
        raise CliError("could not record the answer (nothing was written): %s" % e)
    p["last_activity"] = now().isoformat()
    if i + 1 < len(QUESTIONS):
        p["question"] = QUESTIONS[i + 1]
        p["part"] = question_part(p["question"])
    else:
        p["question"] = None
        p["part"] = None
        p["redo"] = False
        state["phase"] = "active"
        # the completion day is the baseline: it can never become Unrecorded
        state.setdefault("streak_cursor", now().date().isoformat())
        state.setdefault("activated_on", now().date().isoformat())
    save_state(state)
    emit({"answered": qid, "next": p["question"], "file": name,
          "phase": state["phase"]})


# ---- daily check-in and verdicts (PROTOCOL.md section 5.1, 5.3) --------------
# Self-contained section. Log: log/YYYY-MM-DD.md, append-only (ADR-0001).
# Tomorrow's levers: levers.jsonl, one appended line per check-in; the last
# line for a date wins. Streaks/escalation are not handled here.
VERDICTS = ("在轨", "轻微偏离", "走偏")
VERDICT_RE = re.compile(r"^- 判定: (.+?)[ \t]*$")
REVISION_RE = re.compile(r"^- 改判: .+? → (.+?) — 因 ")
AWAY_PREFIX = "- 这几天发生了什么:"  # written by `checkin record --while-away`
AWAY_RE = re.compile(r"^" + re.escape(AWAY_PREFIX) + r"[ \t]*(.*)$")


def log_path(date):
    return os.path.join(data_dir(), "log", date + ".md")


def levers_path():
    return os.path.join(data_dir(), "levers.jsonl")


def saved_levers(date):
    path = levers_path()
    found = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    if rec["date"] == date:
                        found = rec["levers"]
    return found


def one_line(value, label):
    value = (value or "").strip()
    if not value:
        raise CliError("%s is required and must not be empty" % label)
    if "\n" in value:
        raise CliError("%s must be a single line" % label)
    return value


def current_verdict(text):
    verdict = None
    for line in text.split("\n"):
        m = VERDICT_RE.match(line) or REVISION_RE.match(line)
        if m:
            verdict = m.group(1)
    return verdict


def append_log(date, block):
    append_entry(log_path(date), block, sync=True)


def yes_no(value):
    return "是" if value == "yes" else "否"


def check_verdict(value, label="--verdict"):
    verdict = one_line(value, label)
    if verdict not in VERDICTS:
        raise CliError("%s must be one of: %s" % (label, " / ".join(VERDICTS)))
    return verdict


def check_verdict_change(current, verdict, day="today", block_hint=False):
    """The same-day rule shared by `checkin record` and update blocks: an
    existing verdict can only change through a 改判 with a new fact."""
    if current is not None and current != verdict:
        msg = ("a check-in with verdict %s is already recorded %s; changing "
               "the verdict needs a new fact: use `checkin revise-verdict "
               "--new-fact \"...\" --verdict ...`" % (current, day))
        if block_hint:
            msg += (" (in an update block: a '- 改判: %s → %s — 因 <new fact> "
                    "事实改判' line)" % (current, verdict))
        raise CliError(msg)


# Full 改判 line as `checkin revise-verdict` writes it (time suffix optional).
REVISION_FULL_RE = re.compile(
    r"^- 改判: (.+?) → (.+?) — 因 (\S.*?) 事实改判(?: \(\d\d:\d\d:\d\d\))?\s*$")
VERDICT_LIKE_RE = re.compile(r"^\s*- (判定|改判)\s*[:：]")


def check_block_verdicts(n, rel, body, current):
    """Validate the verdict lines of a block bound for log/YYYY-MM-DD.md with
    the check-in rules. `current` is the day's verdict before the block;
    returns the day's verdict after it."""
    label = "block %d (%s)" % (n, rel)
    lines = body.split("\n")
    for i, line in enumerate(lines):
        m = VERDICT_RE.match(line)
        if m:
            verdict = check_verdict(m.group(1), label + ": 判定")
            check_verdict_change(current, verdict, "for this day", True)
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            rm = re.match(r"^- 判定理由: (.*)$", nxt)
            if not rm:
                raise CliError("%s: '- 判定: %s' must be followed directly by a "
                               "'- 判定理由: <reason>' line" % (label, verdict))
            one_line(rm.group(1), label + ": 判定理由")
            current = verdict
            continue
        m = REVISION_FULL_RE.match(line)
        if m:
            previous = check_verdict(m.group(1), label + ": 改判 old verdict")
            verdict = check_verdict(m.group(2), label + ": 改判 new verdict")
            if current is None:
                raise CliError("%s: no check-in recorded that day: nothing to revise" % label)
            if previous != current:
                raise CliError("%s: 改判 says the old verdict was %s but the day's "
                               "current verdict is %s" % (label, previous, current))
            current = verdict
            continue
        if VERDICT_LIKE_RE.match(line) and not line.startswith("- 判定理由:"):
            raise CliError(
                "%s: malformed verdict line %r (expected '- 判定: 在轨|轻微偏离|走偏' "
                "followed by '- 判定理由: ...', or '- 改判: <old> → <new> — 因 "
                "<new fact> 事实改判')" % (label, line))
    return current


def cmd_checkin_record(args):
    state = backfill_unrecorded(require_active())
    away = None
    if state["streak"]["unrecorded"] > 0 or args.while_away is not None:
        away = (args.while_away or "").strip()
        if not away and state["streak"]["unrecorded"] > 0:
            raise CliError(
                "you were silent: first say what happened in the missing days "
                "(--while-away \"...\") before checking in")
    t = now()
    date = t.date().isoformat()
    verdict = check_verdict(args.verdict)
    verdict_reason = one_line(args.verdict_reason, "--verdict-reason")
    levers = [one_line(x, "--lever") for x in (args.lever or [])]
    if not levers:
        levers = saved_levers(date)
    if not levers:
        raise CliError("--lever is required (no levers saved for today)")
    tomorrow = [one_line(x, "--tomorrow-lever") for x in (args.tomorrow_lever or [])]
    if not tomorrow:
        raise CliError("--tomorrow-lever is required (set tomorrow's Daily Levers)")
    if os.path.isfile(log_path(date)):
        with open(log_path(date), encoding="utf-8") as f:
            current = current_verdict(f.read())
        check_verdict_change(current, verdict)
    done = one_line(args.levers_done, "--levers-done")
    action_reason = one_line(args.action_reason, "--action-reason")
    identity_reason = one_line(args.identity_reason, "--identity-reason")
    toward_reason = one_line(args.toward_reason, "--toward-reason")
    lines = [
        "- Daily Levers: %s" % "; ".join(levers),
        "- 完成情况: %s" % done,
        "- 行动偏离: %s — %s" % (yes_no(args.action_drift), action_reason),
        "- 身份保护: %s — %s" % (yes_no(args.identity_protection), identity_reason),
        "- 靠近反愿景: %s — %s" % (
            "靠近反愿景" if args.toward == "anti-vision" else "靠近愿景", toward_reason),
        "- 判定: %s" % verdict,
        "- 判定理由: %s" % verdict_reason,
    ]
    if away:
        lines.append("%s %s" % (AWAY_PREFIX, one_line(away, "--while-away")))
    path = log_path(date)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        head = "## %s 再次打卡" % t.strftime("%H:%M:%S")
    else:
        head = "# %s" % date
    append_log(date, head + "\n" + "\n".join(lines) + "\n")
    state["streak"]["unrecorded"] = 0
    recompute_drift(state)
    save_state(state)
    tomorrow_date = (t.date() + datetime.timedelta(days=1)).isoformat()
    with open(levers_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": tomorrow_date, "levers": tomorrow,
                            "set_at": t.isoformat()}, ensure_ascii=False) + "\n")
    emit({"date": date, "file": "log/%s.md" % date, "verdict": verdict,
          "tomorrow_date": tomorrow_date, "tomorrow_levers": tomorrow})


def cmd_checkin_revise(args):
    state = backfill_unrecorded(require_active())
    t = now()
    date = t.date().isoformat()
    fact = one_line(args.new_fact, "--new-fact (a new fact is required to revise a verdict)")
    verdict = check_verdict(args.verdict)
    path = log_path(date)
    previous = None
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            previous = current_verdict(f.read())
    if previous is None:
        raise CliError("no check-in recorded today: nothing to revise")
    append_log(date, "- 改判: %s → %s — 因 %s 事实改判 (%s)\n"
               % (previous, verdict, fact, t.strftime("%H:%M:%S")))
    recompute_drift(state)
    save_state(state)
    emit({"date": date, "previous": previous, "verdict": verdict,
          "streak": streak_view(state)})


def cmd_checkin_levers(args):
    load_state()
    date = args.date or now().date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise CliError("--date must be YYYY-MM-DD")
    emit({"date": date, "levers": saved_levers(date)})


# ---- streaks, Unrecorded back-fill, escalation, DND (PROTOCOL.md section 5.2) --
# state.streak_cursor = last day already finalized (set when the protocol
# completes). Each interaction back-fills the days after the cursor and before
# today: a non-DND day with no check-in log gets an appended "- 未记录" log
# (ADR-0001: appended, existing logs untouched) and unrecorded += 1. Drift is
# recomputed from the logs (see recompute_drift), never touched by Unrecorded.
ESCALATION_AT = 3
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNRECORDED_LINE = "- 未记录"


def check_date(value):
    value = (value or "").strip()
    try:
        if not DATE_RE.match(value):
            raise ValueError(value)
        datetime.datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise CliError("date must be YYYY-MM-DD")
    return value


def log_verdicts():
    """Sorted [(date, current verdict or None)] over all daily logs."""
    folder = os.path.join(data_dir(), "log")
    out = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if re.match(r"^\d{4}-\d{2}-\d{2}\.md$", name):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    out.append((name[:-3], current_verdict(f.read())))
    return out


def recount_unrecorded(state):
    """Unrecorded = the trailing run of days whose log holds only the
    '- 未记录' placeholder. Any verdict (from `checkin record` or an update
    block) ends the run, which is what `checkin record` does by resetting the
    counter to 0. DND days are skipped."""
    folder = os.path.join(data_dir(), "log")
    run = 0
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if not re.match(r"^\d{4}-\d{2}-\d{2}\.md$", name):
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                text = f.read()
            if current_verdict(text) is not None:
                run = 0
            elif (name[:-3] not in state["dnd_dates"]
                  and UNRECORDED_LINE in text.split("\n")):
                run += 1
    state["streak"]["unrecorded"] = run
    update_escalation(state)


def recompute_drift(state):
    """Consecutive trailing 走偏 days; Unrecorded and DND days are skipped
    (they neither count nor break the run); any other verdict resets to 0."""
    drift = 0
    for _date, verdict in log_verdicts():
        if verdict is None:
            continue
        drift = drift + 1 if verdict == "走偏" else 0
    state["streak"]["drift"] = drift
    update_escalation(state)


def update_escalation(state):
    st = state["streak"]
    state["escalation"] = (st["drift"] >= ESCALATION_AT
                           or st["unrecorded"] >= ESCALATION_AT)


def pending_unrecorded(state):
    """Read-only: (days that back-fill would mark unrecorded, new cursor), or
    ([], None) when there is no cursor. The single source of the back-fill
    rules: backfill_unrecorded writes exactly these days, and push planning
    counts them in memory."""
    today = now().date()
    cursor = state.get("streak_cursor")
    if cursor is None:
        return [], None
    day = datetime.datetime.strptime(cursor, "%Y-%m-%d").date() + datetime.timedelta(days=1)
    verdicts = dict(log_verdicts())
    days = []
    while day < today:
        d = day.isoformat()
        if d not in state["dnd_dates"] and verdicts.get(d) is None:
            days.append(d)
        day += datetime.timedelta(days=1)
    return days, max(cursor, (today - datetime.timedelta(days=1)).isoformat())


def backfill_unrecorded(state):
    days, new_cursor = pending_unrecorded(state)
    if new_cursor is None:
        return state
    for d in days:
        header = "# %s\n" % d
        existing = ""
        if os.path.isfile(log_path(d)):
            with open(log_path(d), encoding="utf-8") as f:
                existing = f.read()
        if re.search(r"(?m)^# %s[ \t]*$" % re.escape(d), existing):
            header = ""
        append_log(d, "%s%s\n" % (header, UNRECORDED_LINE))
        state["streak"]["unrecorded"] += 1
    state["streak_cursor"] = new_cursor
    update_escalation(state)
    save_state(state)
    return state


def with_pending_unrecorded(state):
    """A copy of `state` whose unrecorded count includes the days a back-fill
    would add. Writes nothing; never save the copy."""
    view = copy.deepcopy(state)
    days, _cursor = pending_unrecorded(view)
    view["streak"]["unrecorded"] += len(days)
    update_escalation(view)
    return view


def streak_view(state):
    st = state["streak"]
    return {"drift": st["drift"], "unrecorded": st["unrecorded"],
            "escalation": bool(state.get("escalation")),
            "threshold": ESCALATION_AT, "dnd_dates": state["dnd_dates"]}


def cmd_streak_status(args):
    state = backfill_unrecorded(require_active())
    emit(streak_view(state))


def cmd_dnd(args):
    state = load_state()
    dates = state["dnd_dates"]
    if args.dnd_command in ("add", "remove"):
        d = check_date(args.date)
        if args.dnd_command == "add" and d not in dates:
            dates.append(d)
            dates.sort()
        if args.dnd_command == "remove" and d in dates:
            dates.remove(d)
        save_state(state)
    emit({"dnd_dates": dates})


# ---- review: monthly / yearly data (PROTOCOL.md section 7) ------------------
# Read-only day classification for a period (nothing is back-filled):
#   A day with a verdict (last 判定/改判 line) counts by that verdict, always.
#   Otherwise, in order:
#     day <= activation day      -> excluded "before_activation"
#     DND date                   -> excluded "dnd" (listed in dnd_days; never unrecorded)
#     day >= today               -> excluded "future_or_today_pending"
#     else                       -> unrecorded (missing log or `- 未记录`)
#   So counts sum to days_in_scope, and scope + excluded == days_in_period.
REVIEW_KINDS = {"month": "月复盘", "year": "年复盘"}
NO_CHANGE_MONTH = "本月计划未改动"
VERDICT_KEYS = {"在轨": "on_track", "轻微偏离": "minor_drift", "走偏": "drifted"}


def activation_day(state):
    raw = state.get("activated_on") or state.get("streak_cursor")
    logs = log_verdicts()
    days = [d for d in (raw, logs[0][0] if logs else None) if d]
    return min(days) if days else now().date().isoformat()


def period_distribution(state, first, last):
    today = now().date()
    act = datetime.datetime.strptime(activation_day(state), "%Y-%m-%d").date()
    verdicts = dict(log_verdicts())
    counts = {"on_track": 0, "minor_drift": 0, "drifted": 0, "unrecorded": 0}
    dnd, before, pending = [], 0, 0
    day = first
    while day <= last:
        d = day.isoformat()
        v = verdicts.get(d)
        if v in VERDICT_KEYS:
            counts[VERDICT_KEYS[v]] += 1
        elif day <= act:
            before += 1
        elif d in state["dnd_dates"]:
            dnd.append(d)
        elif day >= today:
            pending += 1
        else:
            counts["unrecorded"] += 1
        day += datetime.timedelta(days=1)
    return {
        "days_in_period": (last - first).days + 1,
        "days_in_scope": sum(counts.values()),
        "counts": counts,
        "dnd_days": dnd,
        "excluded": {"before_activation": before,
                     "future_or_today_pending": pending, "dnd": len(dnd)},
    }


def plan_changes(first, last):
    """Plan changes (see is_change below) dated within [first, last]."""
    out = []
    for target in ("vision", "anti-vision", "goals"):
        prev = None
        for v in read_versions(target):
            # a file's first version is the initial plan unless it carries a
            # plan-change reason; every later version is a change. The
            # protocol's own first version is the initial plan, not a change.
            is_change = prev is not None or (
                "reason" in v and v["reason"] != FIRST_VERSION_REASON)
            if is_change and first.isoformat() <= v["date"] <= last.isoformat():
                item = {"object": target, "date": v["date"],
                        "reason": v.get("reason")}
                if target == "goals":
                    item["sections"] = [
                        t for t, _ in ALL_GOAL_SECTIONS
                        if v["sections"].get(t) is not None
                        and v["sections"].get(t) != (
                            prev["sections"].get(t) if prev else None)]
                out.append(item)
            prev = v
    out.sort(key=lambda c: (c["date"], c["object"]))
    return out


def year_goal_history():
    out, last = [], None
    for v in read_versions("goals"):
        text = v["sections"].get("Year Goal")
        if text is not None and text != last:
            out.append({"date": v["date"], "text": text,
                        "reason": v.get("reason")})
            last = text
    return out


def cmd_review_month(args):
    state = require_active()
    if args.month:
        try:
            first = datetime.datetime.strptime(args.month, "%Y-%m").date()
        except ValueError:
            raise CliError("--month must be YYYY-MM")
    else:
        first = now().date().replace(day=1)
    nxt = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    last = nxt - datetime.timedelta(days=1)
    changes = plan_changes(first, last)
    out = {"kind": "month", "month": first.strftime("%Y-%m")}
    out.update(period_distribution(state, first, last))
    out["plan_changes"] = changes
    out["plan_unchanged"] = not changes
    out["plan_message"] = NO_CHANGE_MONTH if not changes else None
    emit(out)


def cmd_review_year(args):
    state = require_active()
    year = args.year if args.year else now().year
    if not 1 <= year <= 9999:
        raise CliError("--year must be YYYY")
    first, last = datetime.date(year, 1, 1), datetime.date(year, 12, 31)
    out = {"kind": "year", "year": year}
    out.update(period_distribution(state, first, last))
    out["year_goal_history"] = year_goal_history()
    out["plan_changes"] = plan_changes(first, last)
    out["offer_redo_protocol"] = True
    emit(out)


def cmd_review_save(args):
    require_active()
    if args.text is None:
        raise CliError("--text is required")
    text = check_body(args.text, "--text", r"^## ")
    today = now().date()
    period = args.period or (today.strftime("%Y-%m") if args.kind == "month"
                             else str(today.year))
    pattern = r"^\d{4}-\d{2}$" if args.kind == "month" else r"^\d{4}$"
    if not re.match(pattern, period):
        raise CliError("--period must be %s"
                       % ("YYYY-MM" if args.kind == "month" else "YYYY"))
    path = os.path.join(data_dir(), "reviews.md")
    entry = "## %s %s %s\n%s\n" % (today.isoformat(), REVIEW_KINDS[args.kind],
                                   period, text)
    existing = append_entry(path, entry)
    emit({"kind": args.kind, "period": period, "date": today.isoformat(),
          "file": "reviews.md",
          "reviews": len(re.findall(r"(?m)^## ", existing + entry))})


# ---- notify: push scheduling, text, launchd (PROTOCOL.md section 8) ----------
# The plan is a pure function of (date, config, state): the random push is
# drawn from random.Random("life-redesign-notify:" + date), so the same date
# always gives the same plan. Text is pre-written only; user text (Year Goal,
# Daily Levers) appears only when notify.show_user_text is on (default off).
SLOTS = ("morning", "random", "evening")
SILENCE_AT = 3
TICK_SECONDS = 900
LAUNCHD_PREFIX = "com.life-redesign.notify."
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
NOTIFY_TITLE = "Life Redesign"
MORNING_DEFAULT_TEXT = "打开查看今日杠杆"
EVENING_TEXT = "该打卡了:花几分钟记录今天。"
# Pre-written random-push pool: exactly the six interrupt questions
# (PROTOCOL.md 4.2).
INTERRUPT_QUESTIONS = [
    "我现在做的事,是在逃避什么?",
    "如果有人把我过去两小时拍下来,会得出我想要什么样的人生?",
    "我正在走向我讨厌的生活,还是我想要的生活?",
    "我正假装不重要的、最重要的事是什么?",
    "今天有哪些事是出于身份保护,而不是真实欲望?",
    "今天我什么时候感到最有活力?什么时候最麻木?",
]
# Alternates: kept as data, deliberately NOT in the random pool (PROTOCOL 8.1
# draws one of the six interrupt questions only).
ALTERNATE_QUESTIONS = [
    "如果我不再需要别人把我看作那个身份,会有什么不同?",
    "我生活中哪里在用\"活力\"换\"安全\"?",
    "明天我能成为的、想成为的那个人的最小版本是什么?",
]
READ_ONLY_CLAUDE_FLAGS = ["--tools", "",
                          "--disallowedTools",
                          "Bash,Edit,Write,MultiEdit,NotebookEdit"]


def notify_config(state):
    cfg = state.setdefault("notify", {})
    cfg.setdefault("client", "claude -p")
    times = cfg.setdefault("times", {})
    times.setdefault("morning", "08:30")
    times.setdefault("evening", "21:30")
    times.setdefault("random_window", ["11:00", "17:00"])
    cfg.setdefault("show_user_text", False)
    cfg.setdefault("ai", False)
    return cfg


def check_hhmm(value, label):
    if not TIME_RE.match(value or ""):
        raise CliError("%s must be HH:MM (24h)" % label)
    return value


def to_minutes(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def fmt_minutes(m):
    return "%02d:%02d" % (m // 60, m % 60)


def on_off(value):
    if value not in ("on", "off"):
        raise CliError("expected on or off")
    return value == "on"


def reinstall_required(cfg):
    """Installed plists carry the times they were installed with."""
    installed = cfg.get("installed")
    if not installed:
        return False
    return any(installed.get(k) != cfg["times"][k] for k in ("morning", "evening"))


def cmd_notify_config(args):
    state = load_state()
    cfg = notify_config(state)
    times = cfg["times"]
    if args.show_user_text is not None:
        cfg["show_user_text"] = on_off(args.show_user_text)
    if args.ai is not None:
        cfg["ai"] = on_off(args.ai)
    if args.morning is not None:
        times["morning"] = check_hhmm(args.morning, "--morning")
    if args.evening is not None:
        times["evening"] = check_hhmm(args.evening, "--evening")
    if args.window is not None:
        start = check_hhmm(args.window[0], "--window start")
        end = check_hhmm(args.window[1], "--window end")
        if to_minutes(start) >= to_minutes(end):
            raise CliError("--window start must be before end")
        times["random_window"] = [start, end]
    if args.client is not None:
        if not args.client.strip():
            raise CliError("--client must not be empty")
        try:
            shlex.split(args.client)
        except ValueError as e:
            raise CliError("--client is not a valid command line (%s)" % e)
        cfg["client"] = args.client
    save_state(state)
    emit({"notify": cfg, "reinstall_required": reinstall_required(cfg)})


def goals_section(name):
    versions = read_versions("goals")
    if not versions:
        return ""
    return versions[-1].get("sections", {}).get(name, "")


LIST_MARKER_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+")


def day_levers(date):
    levers = saved_levers(date)
    if levers:
        return list(levers)
    text = goals_section("Daily Levers")
    return [LIST_MARKER_RE.sub("", ln).strip()
            for ln in text.split("\n") if ln.strip()]


def push_text(slot, date, state, question):
    cfg = notify_config(state)
    if slot == "morning":
        if not cfg["show_user_text"]:
            return MORNING_DEFAULT_TEXT
        parts = []
        levers = day_levers(date)
        if levers:
            parts.append("今日杠杆: " + "; ".join(levers))
        goal = " ".join(goals_section("Year Goal").split())
        if goal:
            parts.append("Year Goal: " + goal)
        return " | ".join(parts) or MORNING_DEFAULT_TEXT
    if slot == "random":
        return question
    return EVENING_TEXT


def build_plan(state, date):
    """The day's pushes, without text. Empty for DND days / inactive phase."""
    cfg = notify_config(state)
    if state["phase"] != "active":
        return [], "protocol not complete"
    if date in state["dnd_dates"]:
        return [], "do-not-disturb date"
    times = cfg["times"]
    evening = {"slot": "evening", "time": times["evening"]}
    if state["streak"]["unrecorded"] >= SILENCE_AT:
        return [evening], "silence: unrecorded streak"
    rng = random.Random("life-redesign-notify:" + date)
    lo, hi = (to_minutes(t) for t in times["random_window"])
    rnd = {"slot": "random", "time": fmt_minutes(rng.randint(lo, hi)),
           "question": rng.choice(INTERRUPT_QUESTIONS)}
    pushes = [{"slot": "morning", "time": times["morning"]}, rnd, evening]
    pushes.sort(key=lambda p: p["time"])
    return pushes, None


def notify_state():
    """Persisted state for pushes. Read-only with respect to log/ and the
    streak counters: pushes never back-fill (see with_pending_unrecorded)."""
    return refresh(load_state())


def push_view(state):
    """State as the planner sees it: unrecorded days counted in memory."""
    if state["phase"] == "active":
        return with_pending_unrecorded(state)
    return state


PUSH_LOG_NAME = "push.log"
PUSH_LOG_MAX_BYTES = 64 * 1024
PUSH_LOG_KEEP_LINES = 500


def push_log_path():
    return os.path.join(data_dir(), PUSH_LOG_NAME)


def trim_push_log(path, max_bytes=PUSH_LOG_MAX_BYTES, keep=PUSH_LOG_KEEP_LINES):
    """Size cap: over max_bytes, keep only the last `keep` lines."""
    try:
        if os.path.getsize(path) <= max_bytes:
            return
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines(True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(lines[-keep:])
        os.replace(tmp, path)
    except OSError:
        pass


def log_push(slot, outcome):
    """One line per fire attempt: timestamp, slot, outcome. Only fixed words
    and error text from this program; never user-authored text. Logging must
    not break a push."""
    line = "%s %s %s\n" % (now().strftime("%Y-%m-%dT%H:%M:%S"), slot, outcome)
    try:
        append_entry(push_log_path(), line, blank_line=False)
        trim_push_log(push_log_path())
    except OSError:
        pass


def cmd_notify_plan(args):
    state = notify_state()
    view = push_view(state)
    date = check_date(args.date) if args.date else now().date().isoformat()
    pushes, why = build_plan(view, date)
    for p in pushes:
        p["text"] = push_text(p["slot"], date, state, p.get("question"))
    out = {"date": date, "pushes": pushes}
    if why:
        out["reason"] = why
    emit(out)


def recent_logs(date, days=7):
    """Text of the logs for `date` and the 6 days before it (7 days max)."""
    end = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    chunks = []
    for back in range(days - 1, -1, -1):
        d = (end - datetime.timedelta(days=back)).isoformat()
        if os.path.isfile(log_path(d)):
            with open(log_path(d), encoding="utf-8") as f:
                chunks.append(f.read().strip())
    return "\n\n".join(chunks)


def ai_prompt(state, date):
    st = state["streak"]
    return (
        "你是一个只读的提醒助手。下面是用户最近 7 天的日志和 streak "
        "(drift=%d, unrecorded=%d)。请只输出一句中文打卡提醒(不超过 40 字)。"
        "不要给出判定(Verdict),不要引用日志原文。\n\n---日志---\n%s\n"
        % (st["drift"], st["unrecorded"], recent_logs(date)))


def client_command(client, prompt):
    """Headless client invocation, restricted to read-only.

    Enforcement: (1) this CLI reads at most the last 7 days of logs and
    inlines them in the prompt, so the client needs no file access at all;
    (2) for `claude` every tool is disabled (`--tools ""`) and file-writing /
    shell tools are explicitly disallowed; (3) the client runs in an empty
    temp cwd with stdin closed. Other clients are run as configured with the
    same prompt and must be read-only by their own configuration.
    """
    argv = shlex.split(client)
    if not argv:
        raise CliError("notify.client is empty")
    cmd = argv + [prompt]
    if os.path.basename(argv[0]) == "claude":
        cmd += READ_ONLY_CLAUDE_FLAGS
    return cmd


def run_client(cmd):
    """One-line text from the client, or None when unavailable/failed."""
    try:
        with tempfile.TemporaryDirectory(prefix="life-redesign-ai-") as cwd:
            done = subprocess.run(
                cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, universal_newlines=True, timeout=30)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return " ".join(done.stdout.split())[:120] or None


def display_command(title, text):
    tn = shutil.which("terminal-notifier")
    if tn:
        return [tn, "-title", title, "-message", text]
    script = "display notification %s with title %s" % (
        json.dumps(text, ensure_ascii=False), json.dumps(title, ensure_ascii=False))
    return ["osascript", "-e", script]


def cfg_sent(state):
    """{slot: date} of the last push actually sent (idempotency for --tick)."""
    return notify_config(state).setdefault("sent", {})


def cmd_notify_fire(args):
    state = notify_state()
    view = push_view(state)  # in-memory unrecorded count; `state` is what is saved
    now_dt = now()
    date = now_dt.date().isoformat()
    pushes, why = build_plan(view, date)
    entry = next((p for p in pushes if p["slot"] == args.slot), None)
    result = {"slot": args.slot, "date": date, "dry_run": bool(args.dry_run),
              "fired": False}
    if entry is None:
        result["skipped"] = why or "not in today's plan"
        log_push(args.slot, "skipped: " + result["skipped"])
        emit(result)
        return
    sent = cfg_sent(state)
    if args.tick and sent.get(args.slot) == date:
        result["skipped"] = "already sent today"
        log_push(args.slot, "skipped: " + result["skipped"])
        emit(result)
        return
    if args.tick:
        at = datetime.datetime.strptime(
            date + " " + entry["time"], "%Y-%m-%d %H:%M")
        if not (0 <= (now_dt - at).total_seconds() < TICK_SECONDS):
            result["skipped"] = "not due yet"
            log_push(args.slot, "skipped: " + result["skipped"])
            emit(result)
            return
    cfg = notify_config(state)
    text = push_text(args.slot, date, state, entry.get("question"))
    source = "template"
    # AI only for the evening reminder, and only when notify.ai is on.
    if args.slot == "evening" and cfg["ai"]:
        prompt = ai_prompt(view, date)
        try:
            cmd = client_command(cfg["client"], prompt)
        except (CliError, ValueError):
            cmd = None  # unusable client config: keep the template text
        if cmd:
            result["client_command"] = ["<prompt>" if c == prompt else c for c in cmd]
            ai_text = run_client(cmd)
            if ai_text:
                text, source = ai_text, "ai"
    cmd = display_command(NOTIFY_TITLE, text)
    result.update({"title": NOTIFY_TITLE, "text": text, "source": source,
                   "display_command": cmd})
    if not args.dry_run:
        try:
            subprocess.run(cmd, stdin=subprocess.DEVNULL, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            result["fired"] = True
            sent[args.slot] = date
            save_state(state)
        except (OSError, subprocess.SubprocessError):
            result["error"] = "display command failed"
    if result.get("error"):
        log_push(args.slot, "failed: " + result["error"])
    elif args.dry_run:
        log_push(args.slot, "dry-run")
    else:
        log_push(args.slot, "sent")
    emit(result)


def launchd_dir():
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")


def launchd_path(cfg):
    """PATH for scheduled jobs: launchd's own is minimal (/usr/bin:/bin:...)."""
    home = os.path.expanduser("~")
    dirs = ["/opt/homebrew/bin", "/usr/local/bin",
            os.path.join(home, ".local", "bin"),
            "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    try:
        argv = shlex.split(cfg["client"])
    except ValueError:
        argv = []
    if argv and os.path.isabs(argv[0]):
        dirs.insert(0, os.path.dirname(argv[0]))
    out = []
    for d in dirs:
        if d not in out:
            out.append(d)
    return ":".join(out)


def launchd_jobs(state):
    cfg = notify_config(state)
    times = cfg["times"]
    env = {"LIFE_REDESIGN_HOME": data_dir(), "HOME": os.path.expanduser("~"),
           "PATH": launchd_path(cfg)}
    script = os.path.abspath(__file__)
    jobs = []
    for slot in SLOTS:
        argv = [sys.executable, script, "notify", "fire", slot]
        job = {"Label": LAUNCHD_PREFIX + slot,
               "EnvironmentVariables": env,
               "StandardOutPath": push_log_path(),
               "StandardErrorPath": push_log_path(),
               "RunAtLoad": False}
        if slot == "random":
            # launchd cannot fire at a random time: tick through the day and
            # let `fire --tick` decide whether the planned minute is due.
            job["ProgramArguments"] = argv + ["--tick"]
            job["StartInterval"] = TICK_SECONDS
        else:
            hh, mm = times[slot].split(":")
            job["ProgramArguments"] = argv
            job["StartCalendarInterval"] = {"Hour": int(hh), "Minute": int(mm)}
        path = os.path.join(launchd_dir(), job["Label"] + ".plist")
        jobs.append({"label": job["Label"], "path": path, "job": job})
    return jobs


def cmd_notify_launchd(args):
    state = load_state()
    action = args.notify_command
    jobs = launchd_jobs(state)
    domain = "gui/%d" % os.getuid()
    cmds = []
    for j in jobs:
        if action == "install":
            cmds.append(["launchctl", "bootstrap", domain, j["path"]])
        else:
            cmds.append(["launchctl", "bootout", domain + "/" + j["label"]])
    if action == "install":
        shown = [{"label": j["label"], "path": j["path"],
                  "plist": plistlib.dumps(j["job"]).decode("utf-8")}
                 for j in jobs]
    else:
        shown = [{"label": j["label"], "path": j["path"]} for j in jobs]
    out = {"dry_run": bool(args.dry_run), "jobs": shown, "commands": cmds,
           "log_path": push_log_path()}
    if action == "uninstall":
        out["remove_files"] = [j["path"] for j in jobs]
    if args.dry_run:
        emit(out)
        return
    if sys.platform != "darwin":
        raise CliError("launchd install/uninstall is macOS only")
    if action == "install":
        os.makedirs(launchd_dir(), exist_ok=True)
        for j in jobs:
            if os.path.isfile(j["path"]):  # re-install: unload the old job first
                subprocess.run(["launchctl", "bootout", domain + "/" + j["label"]],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            with open(j["path"], "wb") as f:
                f.write(plistlib.dumps(j["job"]))
    results = []
    for c in cmds:
        try:
            done = subprocess.run(
                c, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, universal_newlines=True)
            results.append({"command": c, "returncode": done.returncode,
                            "stderr": done.stderr.strip()})
        except OSError as e:
            results.append({"command": c, "returncode": -1, "stderr": str(e)})
    out["results"] = results
    out["failed"] = [r["command"] for r in results if r["returncode"] != 0]
    if action == "uninstall":
        for j in jobs:
            if os.path.isfile(j["path"]):
                os.remove(j["path"])
    if not out["failed"]:
        cfg = notify_config(state)
        if action == "install":
            cfg["installed"] = {k: cfg["times"][k] for k in ("morning", "evening")}
        else:
            cfg.pop("installed", None)
        save_state(state)
    emit(out)
    if out["failed"]:
        print("error: %d launchctl command(s) failed (see results)"
              % len(out["failed"]), file=sys.stderr)
        return 1


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
    p = sub.add_parser("plan", help="change vision/goals/levers/constraints with a reason")
    plsub = p.add_subparsers(dest="plan_command")
    plsub.required = True
    q = plsub.add_parser("change")
    q.add_argument("object", choices=sorted(PLAN_OBJECTS))
    q.add_argument("--text")
    q.add_argument("--why")
    q.set_defaults(func=cmd_plan_change)
    p = sub.add_parser("protocol", help="one-day protocol progress and resume")
    psub = p.add_subparsers(dest="protocol_command")
    psub.required = True
    psub.add_parser("status").set_defaults(func=cmd_protocol_status)
    psub.add_parser("resume").set_defaults(func=cmd_protocol_resume)
    psub.add_parser("redo").set_defaults(func=cmd_protocol_redo)
    psub.add_parser("gate").set_defaults(func=cmd_protocol_gate)
    q = psub.add_parser("answer")
    q.add_argument("question_id")
    q.add_argument("--text")
    q.set_defaults(func=cmd_protocol_answer)
    q = psub.add_parser("confirm-feeling")
    q.add_argument("feeling", choices=["fresh", "faded"])
    q.set_defaults(func=cmd_protocol_confirm)
    p = sub.add_parser("checkin", help="nightly check-in, verdict revision, levers")
    csub = p.add_subparsers(dest="checkin_command")
    csub.required = True
    q = csub.add_parser("record")
    q.add_argument("--lever", action="append")
    q.add_argument("--levers-done")
    q.add_argument("--action-drift", choices=["yes", "no"], required=True)
    q.add_argument("--action-reason")
    q.add_argument("--identity-protection", choices=["yes", "no"], required=True)
    q.add_argument("--identity-reason")
    q.add_argument("--toward", choices=["anti-vision", "vision"], required=True)
    q.add_argument("--toward-reason")
    q.add_argument("--verdict")
    q.add_argument("--verdict-reason")
    q.add_argument("--tomorrow-lever", action="append")
    q.add_argument("--while-away", dest="while_away")
    q.set_defaults(func=cmd_checkin_record)
    q = csub.add_parser("revise-verdict")
    q.add_argument("--new-fact")
    q.add_argument("--verdict")
    q.set_defaults(func=cmd_checkin_revise)
    q = csub.add_parser("levers")
    q.add_argument("--date")
    q.set_defaults(func=cmd_checkin_levers)
    p = sub.add_parser("streak", help="drift/unrecorded counters and escalation flag")
    ssub = p.add_subparsers(dest="streak_command")
    ssub.required = True
    ssub.add_parser("status").set_defaults(func=cmd_streak_status)
    p = sub.add_parser("dnd", help="manage do-not-disturb dates")
    dsub = p.add_subparsers(dest="dnd_command")
    dsub.required = True
    dsub.add_parser("list")
    for name in ("add", "remove"):
        q = dsub.add_parser(name)
        q.add_argument("date")
    p.set_defaults(func=cmd_dnd)
    p = sub.add_parser("review", help="monthly/yearly review data and saved conclusions")
    rsub = p.add_subparsers(dest="review_command")
    rsub.required = True
    q = rsub.add_parser("month")
    q.add_argument("--month")
    q.set_defaults(func=cmd_review_month)
    q = rsub.add_parser("year")
    q.add_argument("--year", type=int)
    q.set_defaults(func=cmd_review_year)
    q = rsub.add_parser("save")
    q.add_argument("--kind", required=True, choices=sorted(REVIEW_KINDS))
    q.add_argument("--period")
    q.add_argument("--text")
    q.set_defaults(func=cmd_review_save)
    p = sub.add_parser("notify", help="push schedule, text and launchd install")
    nsub = p.add_subparsers(dest="notify_command")
    nsub.required = True
    q = nsub.add_parser("config")
    q.add_argument("--show-user-text")
    q.add_argument("--ai")
    q.add_argument("--morning")
    q.add_argument("--evening")
    q.add_argument("--window", nargs=2, metavar=("START", "END"))
    q.add_argument("--client")
    q.set_defaults(func=cmd_notify_config)
    q = nsub.add_parser("plan")
    q.add_argument("--date")
    q.set_defaults(func=cmd_notify_plan)
    q = nsub.add_parser("fire")
    q.add_argument("slot", choices=SLOTS)
    q.add_argument("--dry-run", action="store_true")
    q.add_argument("--tick", action="store_true")
    q.set_defaults(func=cmd_notify_fire)
    for name in ("install", "uninstall"):
        q = nsub.add_parser(name)
        q.add_argument("--dry-run", action="store_true")
        q.set_defaults(func=cmd_notify_launchd)
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except CliError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
