# Running on a real Slack workspace

This is the checklist for one real run: a free Slack workspace, the real bot, and a live drift alert in a real thread. It takes about 20 minutes. Discord and GitHub are optional: any source without credentials is read from the scenario files, and the build log says which source came from where.

## 1. Create the workspace and the app

1. **Workspace.** Create a free workspace at <https://slack.com/get-started>.
2. **Channels.** Create three public channels: `#product`, `#engineering` and `#support-escalations`. These are the scenario's Slack channels.
3. **App.** Go to <https://api.slack.com/apps> → **Create New App** → **From scratch**. Give it a name (for example "Drift Monitor") and pick the workspace.
4. **Socket Mode.** Open **Socket Mode** and enable it. When asked for an app-level token, name it, add the scope **`connections:write`**, and generate it. This is the `xapp-…` token.
5. **Bot Token Scopes.** Open **OAuth & Permissions** → **Bot Token Scopes** and add all six. `python -m scripts.check_setup` checks every one of them:

   | Scope | Used for |
   |---|---|
   | `channels:read` | listing channels and looking up channel names |
   | `channels:history` | reading history and thread replies; receiving message events |
   | `users:read` | mapping Slack users to people |
   | `chat:write` | posting drift alerts |
   | `chat:write.customize` | seeding: posting as each fictional author |
   | `app_mentions:read` | answering @mentions |

6. **Event Subscriptions.** Open **Event Subscriptions**, enable it, and under **Subscribe to bot events** add **`message.channels`** and **`app_mention`**.
7. **Install.** Open **OAuth & Permissions** → **Install to Workspace**, and copy the **Bot User OAuth Token** (`xoxb-…`).
8. **Invite the bot.** In each of the three channels, type `/invite @Drift Monitor`.

## 2. Put the tokens in `.env`

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_TEST_CHANNEL_ID=C0...      # right-click #engineering -> View channel details -> the ID at the bottom
```

Then check them:

```bash
python -m scripts.check_setup
```

The Slack line must read `[PASS] Slack  bot '…' in workspace '…', all 6 scopes granted; read N message(s) from the test channel`. On a FAIL it names the missing scope or step. The Discord, GitHub and LLM lines may fail; they are optional for this run.

## 3. Seed, build from the live API, start the bot

```bash
python -m scripts.seed_slack                       # posts the scenario's Slack messages, as their authors, in order
python -m pipeline.build --live --extractor heuristic
uvicorn api.main:app --port 8000                   # dashboard on http://localhost:8000
python -m bots.slack_bot                           # in a second terminal
```

- **Seeding.** Slack can't backdate messages, so the seeder writes `data/seed_maps/slack.json`. The connector uses it to restore each message's original author and time. Re-running the seeder skips messages already posted.
- **Building.** `build --live` must print `sources: slack: live API; …`. If it prints `slack: scenario files`, the token wasn't picked up.
- **Expected result.** The dashboard shows the same two open drifts as the offline demo. The CSV-export drift now comes from your real `#support-escalations` channel.

## 4. Trigger a live alert

In `#engineering`, post this **as the ticket owner** (BD-102 is owned by `maya` in the scenario):

> Decision: the export button must also offer a JSON download, BD-102.

**How the bot knows who you are.** The bot maps a Slack user to a scenario person through the **username** that `users.info` returns, matched against the `slack` field in `data/scenario/people.json` (maya's is `maya.chen`). That username is often your email's local part, not your display name. Any other user becomes `slack:<username>`. That person owns no ticket and so has no decision rights: the bot will **not** alert, by design.

To post as maya, put your own username in her entry **before** step 3. To find your username:

```bash
python -c "from connectors.slack import client; c=client(); print([(u['name'], u.get('real_name')) for u in c.users_list()['members'] if not u.get('is_bot')])"
```

Then set `"slack": "<your username>"` for `maya` in `data/scenario/people.json`. That file is the cast list, not the answer key. Re-run step 3's build afterwards, and don't commit the change (the tests expect `maya.chen`).

**What to expect.** Within a second or two the bot replies **in the thread** with "Requirement drift on Ticket export to CSV …". The reply carries the graph path, and every open dashboard shows the new-drift toast.

## 5. Screenshots for the README

1. The Slack thread: your message and the bot's reply underneath (the important one).
2. The dashboard's Open drift section with the new card, on <http://localhost:8000>.

Save them as `docs/real-slack-thread.png` and `docs/real-slack-dashboard.png`; the README's "Run on a real Slack workspace" section shows them. Crop out browser tabs and bookmarks first.

## Afterwards

```bash
python -m scripts.demo_reset --api http://localhost:8000   # back to the starting state (also clears the alert cooldown)
```

Remove the app from the workspace when you're done, or rotate both tokens.
