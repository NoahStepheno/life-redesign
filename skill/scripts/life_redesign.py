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
                   "--why"}
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
        versions = read_versions("goals")
        merged = dict(versions[-1]["sections"]) if versions else {}
        merged.update(given)
        body = "\n\n".join("### %s\n%s" % (t, merged[t])
                           for t, _ in ALL_GOAL_SECTIONS if t in merged)
    else:
        for _, attr in GOAL_SECTIONS:
            if getattr(args, attr) is not None:
                raise CliError("--%s is only valid for goals" % attr.replace("_", "-"))
        if args.text is None:
            raise CliError("--text is required")
        body = check_body(args.text, "--text", r"^## ")
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
    versions = read_versions(target)
    emit({"target": target, "date": versions[-1]["date"], "versions": len(versions)})


def cmd_show(args):
    versions = read_versions(args.target)
    emit({"target": args.target,
          "current": versions[-1] if versions else None,
          "versions": versions})


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
        body = "\n\n".join("### %s\n%s" % (t, merged[t])
                           for t, _ in ALL_GOAL_SECTIONS if t in merged)
    else:
        old = current["content"] if current else None
        body = text
    path = os.path.join(data_dir(), APPEND_TARGETS[target])
    existing = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            existing = f.read()
    date = now().date().isoformat()
    entry = "## %s\n%s\n_Reason: %s_\n" % (date, body, why)
    if existing.strip():
        entry = ("\n" if existing.endswith("\n") else "\n\n") + entry
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)
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
    name = segment_file(state)
    os.makedirs(protocol_dir(), exist_ok=True)
    path = os.path.join(protocol_dir(), name)
    existing = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            existing = f.read()
    entry = "## %s\n%s\n" % (qid, body)
    if existing.strip():
        entry = ("\n" if existing.endswith("\n") else "\n\n") + entry
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)
        f.flush()
        os.fsync(f.fileno())
    i = QUESTIONS.index(qid)
    p["last_activity"] = now().isoformat()
    if i + 1 < len(QUESTIONS):
        p["question"] = QUESTIONS[i + 1]
        p["part"] = question_part(p["question"])
    else:
        p["question"] = None
        p["part"] = None
        p["redo"] = False
        state["phase"] = "active"
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
    path = log_path(date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            existing = f.read()
    if existing:
        block = ("\n" if existing.endswith("\n") else "\n\n") + block
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)
        f.flush()
        os.fsync(f.fileno())


def yes_no(value):
    return "是" if value == "yes" else "否"


def check_verdict(value):
    verdict = one_line(value, "--verdict")
    if verdict not in VERDICTS:
        raise CliError("--verdict must be one of: %s" % " / ".join(VERDICTS))
    return verdict


def cmd_checkin_record(args):
    require_active()
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
    path = log_path(date)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        head = "## %s 再次打卡" % t.strftime("%H:%M:%S")
    else:
        head = "# %s" % date
    append_log(date, head + "\n" + "\n".join(lines) + "\n")
    tomorrow_date = (t.date() + datetime.timedelta(days=1)).isoformat()
    with open(levers_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": tomorrow_date, "levers": tomorrow,
                            "set_at": t.isoformat()}, ensure_ascii=False) + "\n")
    emit({"date": date, "file": "log/%s.md" % date, "verdict": verdict,
          "tomorrow_date": tomorrow_date, "tomorrow_levers": tomorrow})


def cmd_checkin_revise(args):
    require_active()
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
    emit({"date": date, "previous": previous, "verdict": verdict})


def cmd_checkin_levers(args):
    load_state()
    date = args.date or now().date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise CliError("--date must be YYYY-MM-DD")
    emit({"date": date, "levers": saved_levers(date)})


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
    q.set_defaults(func=cmd_checkin_record)
    q = csub.add_parser("revise-verdict")
    q.add_argument("--new-fact")
    q.add_argument("--verdict")
    q.set_defaults(func=cmd_checkin_revise)
    q = csub.add_parser("levers")
    q.add_argument("--date")
    q.set_defaults(func=cmd_checkin_levers)
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except CliError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
