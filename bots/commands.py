"""Chat commands shared by the Slack and Discord bots.

    ask <question>       cited answer from the graph agent
    retro <sprint id>    sprint retro report
    drift                open drift across all features
    spec <feature id>    agent-ready spec for a drifted feature
"""
from agent import retro as retro_mod
from agent.tools import drift_for_feature

HELP = "Commands: `ask <question>`, `retro s1|s2`, `drift`, `spec <feature id>`"


def handle(text: str) -> str | None:
    """Returns a reply for a command, or None if the text isn't a command."""
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
        return "\n".join(f"• *{d['feature_name']}* / {d['ticket']}: \"{d['requirement_text']}\" (by {d['changed_by']}, {d['changed_at'][:10]})"
                         for d in r["rows"])
    if cmd == "spec" and arg:
        from agent.spec import generate_spec
        return generate_spec(arg)["markdown"]
    if cmd in ("help", "?"):
        return HELP
    return None
