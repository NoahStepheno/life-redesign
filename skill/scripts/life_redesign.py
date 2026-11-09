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


def main(argv=None):
    parser = argparse.ArgumentParser(prog="life_redesign")
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    p = sub.add_parser("init", help="create data dir and initial state (idempotent)")
    p.add_argument("--ack-privacy", action="store_true")
    p.set_defaults(func=cmd_init)
    sub.add_parser("ack-privacy", help="record privacy acknowledgement").set_defaults(func=cmd_ack_privacy)
    sub.add_parser("status", help="show phase and privacy status").set_defaults(func=cmd_status)
    sub.add_parser("now", help="show the effective current time").set_defaults(func=cmd_now)
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except CliError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
