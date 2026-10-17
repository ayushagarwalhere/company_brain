"""Chat commands shared by the Slack and Discord bots.

ask <question>       cited answer from the graph agent
retro <sprint id>    sprint retro report
drift                open drift across all features
spec <feature id>    agent-ready spec for a drifted feature

Work on a drift (pipeline.work). In the bot's alert thread they act on that thread's drift; elsewhere name the
ticket ("plan BD-102"):
plan                 what has to change and who owns each part
fix it               an owner approves: the decision goes into the ticket, follow-ups are assigned
keep the old scope   an owner records a dismissal
tasks / my tasks     open follow-ups
done T-3             close a follow-up (its assignee or approver)
"""

import re

from agent import retro as retro_mod
from agent.tools import drift_for_feature

HELP = (
    "Commands: `ask <question>`, `retro s1|s2`, `drift`, `spec <feature id>`.\n"
    "On a drift (in my alert thread, or name the ticket): `plan`, `fix it`, `keep the old scope`, `tasks`, `my tasks`, `done T-1`."
)

PLAN = re.compile(r"\b(plan|what needs to (happen|change)|how (do|should|can) we fix|who (needs|has) to)\b", re.I)
APPLY = re.compile(r"\b(fix it|apply( it| the plan)?|do it|approve|write it (in)?to the ticket|update the ticket)\b", re.I)
KEEP = re.compile(r"\b(keep (the )?old scope|dismiss( it)?)\b", re.I)
TASKS = re.compile(r"\b(my )?(tasks|follow-?ups)\b", re.I)
DONE = re.compile(r"\b(done|close|finished?)\s+T-?(\d+)\b", re.I)
TICKET = re.compile(r"\b([A-Z]{2,6}-\d+)\b")


def _target(g, text: str, requirement: str | None) -> tuple[str | None, str | None]:
    """(requirement id, error): the thread's drift, else the drift on a named ticket, else the only open drift."""
    from graph import queries as Q

    if requirement:
        return requirement, None
    drift = Q.drift(g)
    m = TICKET.search(text)
    if m:
        on = sorted((d for d in drift if d["ticket"] == m.group(1).upper()), key=lambda d: -d["changed_ms"])
        return (on[0]["requirement"], None) if on else (None, f"No open drift on {m.group(1).upper()}.")
    if len(drift) == 1:
        return drift[0]["requirement"], None
    return None, "Which ticket? Reply in my alert thread, or name it, e.g. `plan " + (drift[0]["ticket"] if drift else "BD-101") + "`."


def handle_work(text: str, actor: str | None = None, requirement: str | None = None) -> str | None:
    """Work commands on a drift; None if the text isn't one."""
    from graph.db import get_graph
    from pipeline import work

    g = get_graph()
    m = DONE.search(text)
    if m:
        try:
            return f"✅ {work.complete(g, int(m.group(2)), actor or '')['task']} closed by {actor}."
        except (work.NotAllowed, ValueError) as e:
            return str(e)
    if TASKS.search(text) and not PLAN.search(text):
        mine = bool(re.search(r"\bmy\b", text, re.I))
        rows = work.tasks(g, person=actor if mine else None)
        return ("Your open follow-ups:\n" if mine else "Open follow-ups:\n") + work.format_tasks(rows)
    kind = "keep" if KEEP.search(text) else "apply" if APPLY.search(text) else "plan" if PLAN.search(text) else None
    if not kind:
        return None
    req, err = _target(g, text, requirement)
    if err:
        return err
    try:
        if kind == "plan":
            return work.format_plan(work.plan(g, req))
        if not actor:
            return "I couldn't tell who you are, so I can't act on this."
        if kind == "keep":
            out = work.keep_old_scope(g, req, actor)
            return f"Recorded: {actor} keeps the old scope. The drift is closed and the decision is on record (Decision -[:DISMISSES]-> requirement)."
        out = work.apply(g, req, actor)
        lines = [f"✅ Done. {out['ticket']} now carries the decision ({out['version'].split(':')[-1]}), approved by {actor}."]
        if out["tasks"]:
            lines.append("Follow-ups opened:")
            lines.append(work.format_tasks(out["tasks"]))
        if out["tell"]:
            lines.append("Worth telling: " + ", ".join(out["tell"]) + ".")
        return "\n".join(lines)
    except work.NotAllowed as e:
        return f"🔒 {e}"
    except ValueError as e:
        return str(e)


def handle(text: str, actor: str | None = None, requirement: str | None = None) -> str | None:
    """Returns a reply for a command, or None if the text isn't a command. `actor` is the person speaking (mapped
    from the chat user); `requirement` is the drift whose alert thread the message is in."""
    cmd, _, arg = text.strip().partition(" ")
    cmd, arg = cmd.lower(), arg.strip()
    if cmd == "ask" and arg:
        from agent.agent import ask

        out = ask(arg)
        return out["answer"]
    if cmd == "retro":
        return retro_mod.to_markdown(retro_mod.retro(arg or "s1"))
    if cmd == "drift":
        r = drift_for_feature()
        if not r["rows"]:
            return "No open drift ✅"
        return "\n".join(
            f"• *{d['feature_name']}* / {d['ticket']}: \"{d['requirement_text']}\" (by {d['changed_by']}, {d['changed_at'][:10]})" for d in r["rows"]
        )
    if cmd == "spec" and arg:
        from agent.spec import generate_spec

        return generate_spec(arg)["markdown"]
    if cmd in ("help", "?"):
        return HELP
    return handle_work(text, actor, requirement)
