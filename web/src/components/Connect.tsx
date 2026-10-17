import { useEffect, useState } from "react";
import { api, type Integrations, type SlackChannels } from "../lib/api";
import { plural } from "../lib/ui";
import { Reveal } from "./Motion";

/* "Connect your team" on the overview: Add to Slack (Slack's OAuth consent page, then pick channels) and Add to
   Discord (Discord's page for adding the bot to a server). The buttons go through the API (api/integrations.py),
   which redirects to Slack and Discord; nothing here ever sees a token. */

const query = () => new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);

function errorText(service: string, error: string) {
  if (error === "not_configured") {
    return service === "slack"
      ? "This server isn't set up for Add to Slack yet: it needs SLACK_CLIENT_ID and SLACK_CLIENT_SECRET from the Slack app."
      : "This server isn't set up for Add to Discord yet: it needs the Discord bot token (DISCORD_BOT_TOKEN).";
  }
  if (error === "access_denied") return `Cancelled on ${service === "slack" ? "Slack" : "Discord"}'s page. Nothing was connected.`;
  return `${service === "slack" ? "Slack" : "Discord"} said: ${error}`;
}

function ChannelPicker({ team, onSaved }: { team: string; onSaved: () => void }) {
  const [data, setData] = useState<SlackChannels | null>(null);
  const [pick, setPick] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.slackChannels(team).then((d) => { setData(d); setPick(new Set(d.channels.filter((c) => c.watched).map((c) => c.id))); })
      .catch((e) => setErr((e as Error).message));
  }, [team]);
  const toggle = (id: string) => setPick((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.watchSlack(team, [...pick]);
      setMsg(`Watching ${r.joined.map((c) => `#${c.name}`).join(", ") || "no channels"}.${r.failed.length ? ` Couldn't join ${r.failed.length}.` : ""}`);
      onSaved();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  if (err) return <p className="connect__err">{err}</p>;
  if (!data) return <p className="mono muted">Loading channels…</p>;
  return (
    <div className="connect__pick">
      <span className="mono muted">Channels in {data.team} · the bot reads only the ones you pick</span>
      <div className="connect__chans">
        {data.channels.map((c) => (
          <label key={c.id} className={pick.has(c.id) ? "on" : ""}>
            <input type="checkbox" checked={pick.has(c.id)} onChange={() => toggle(c.id)} />
            <span>#{c.name}</span>{c.members != null && <small>{c.members}</small>}
          </label>
        ))}
      </div>
      <div className="connect__row">
        <button className="btn btn--sm" disabled={busy} onClick={() => void save()}>{busy ? "Joining…" : `Watch ${pick.size} ${plural(pick.size, "channel", "channels")}`}</button>
        {msg && <span className="mono">{msg}</span>}
      </div>
    </div>
  );
}

function SlackCard({ st, fresh, reload }: { st: Integrations["slack"] | null; fresh: string | null; reload: () => void }) {
  const [open, setOpen] = useState<string | null>(fresh);
  const n = st?.workspaces.length || 0;
  return (
    <div className="connect__card">
      <div className="connect__top">
        <span className="connect__mark" aria-hidden>#</span>
        <div><h3>Slack</h3><span className="mono muted">Socket Mode bot · in-thread alerts</span></div>
        <span className={`tag ${n ? "tag--inv" : ""}`}>{n ? `${n} ${plural(n, "workspace", "workspaces")} connected` : st?.bot_from_env ? "1 workspace via server settings" : "Not connected"}</span>
      </div>
      <p>Add the bot to your workspace and pick the channels it should watch. Every message is linked into the graph; when an owner's decision never reached the ticket, it replies in the thread with the evidence. In the thread: <span className="mono">@Drift Monitor plan</span>, <span className="mono">fix it</span>, <span className="mono">keep the old scope</span>.</p>
      {st?.ready
        ? <a className="btn" href="/api/connect/slack">Add to Slack →</a>
        : <><button className="btn" disabled>Add to Slack →</button>
          <p className="connect__note mono">Server setup needed: SLACK_CLIENT_ID and SLACK_CLIENT_SECRET (Slack app → Basic Information), and <b>{location.origin}/api/connect/slack/callback</b> under OAuth &amp; Permissions → Redirect URLs (Slack wants HTTPS).</p></>}
      {n > 0 && (
        <ul className="connect__list">
          {st!.workspaces.map((w) => (
            <li key={w.team_id}>
              <div className="connect__row">
                <b>{w.team}</b>
                <span className="mono muted">{w.channels.length ? w.channels.map((c) => `#${c.name}`).join(" ") : "no channels picked yet"}</span>
                <button className="link" onClick={() => setOpen(open === w.team_id ? null : w.team_id)}>{open === w.team_id ? "Close" : "Pick channels"}</button>
              </div>
              {open === w.team_id && <ChannelPicker team={w.team_id} onSaved={reload} />}
            </li>
          ))}
        </ul>
      )}
      {st && <p className="connect__note mono">Asks for: {st.scopes.join(", ")}</p>}
    </div>
  );
}

function DiscordCard({ st }: { st: Integrations["discord"] | null }) {
  const n = st?.servers.length || 0;
  return (
    <div className="connect__card">
      <div className="connect__top">
        <span className="connect__mark" aria-hidden>D</span>
        <div><h3>Discord</h3><span className="mono muted">Gateway bot · replies to the message</span></div>
        <span className={`tag ${n ? "tag--inv" : ""}`}>{n ? `${n} ${plural(n, "server", "servers")} connected` : "Not connected"}</span>
      </div>
      <p>Add the bot to a server you manage. It reads the channels it can see, checks each message against the graph, and replies when a decision never reached the ticket. Commands: <span className="mono">!brain plan</span>, <span className="mono">!brain fix it</span>, <span className="mono">!brain who knows export</span>.</p>
      {st?.ready
        ? <a className="btn" href="/api/connect/discord">Add to Discord →</a>
        : <><button className="btn" disabled>Add to Discord →</button>
          <p className="connect__note mono">Server setup needed: a Discord application with a bot (Developer Portal → Bot): DISCORD_BOT_TOKEN, and the Message Content intent switched on.</p></>}
      {n > 0 && <ul className="connect__list">{st!.servers.map((s) => <li key={s.id}><div className="connect__row"><b>{s.name}</b><span className="mono muted">bot is in this server</span></div></li>)}</ul>}
      {st?.ready && !n && <p className="connect__note mono">Servers show up here once the bot is running (python -m bots.discord_bot) and has been added.</p>}
    </div>
  );
}

export function Connect() {
  const [st, setSt] = useState<Integrations | null>(null);
  const q = query();
  const connected = q.get("connected"), team = q.get("team"), failedFor = q.get("connect"), error = q.get("error");
  const load = () => void api.integrations().then(setSt).catch(() => setSt(null));
  useEffect(load, []);
  // back from Slack's or Discord's page: land on this section
  useEffect(() => { if (connected || failedFor) setTimeout(() => document.getElementById("connect")?.scrollIntoView({ behavior: "smooth" }), 500); }, [connected, failedFor]);
  const fresh = connected === "slack" ? st?.slack.workspaces.find((w) => w.team_id === team) : null;
  return (
    <section className="ch" id="connect">
      <Reveal className="ch__head">
        <div className="hs__idx"><b>07</b><span>—</span><span>Connect</span></div>
        <h2>Bring your own team. <span className="muted">Two clicks.</span></h2>
        <p>Add the bot to your Slack workspace or Discord server. It reads the channels you pick, links each message into your company graph, and speaks up in the thread when a decision never made it into the work.</p>
      </Reveal>
      {fresh && <p className="connect__ok">Connected to <b>{fresh.team}</b>. Pick the channels the bot should watch below.</p>}
      {failedFor && error && <p className="connect__err">{errorText(failedFor, error)}</p>}
      <Reveal delay={0.08}>
        <div className="connect">
          <SlackCard st={st?.slack || null} fresh={connected === "slack" ? team : null} reload={load} />
          <DiscordCard st={st?.discord || null} />
        </div>
        <div className="connect__steps">
          <div><b>1 · Add the bot</b><p>Slack's or Discord's own consent page: you see exactly what it may read and post.</p></div>
          <div><b>2 · Pick channels</b><p>The bot joins only those. New messages flow into the graph as they're posted.</p></div>
          <div><b>3 · Link the work</b><p>Tickets and pull requests come in through webhooks (<span className="mono">/api/ingest/ticket</span>, <span className="mono">/api/ingest/github</span>), docs through Google Drive.</p></div>
        </div>
      </Reveal>
    </section>
  );
}
