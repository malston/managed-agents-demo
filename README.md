# Managed Agents demo: log triage

A small, working example of [Claude Managed Agents](https://platform.claude.com/docs/en/managed-agents/overview).
You give it an application log. A Claude agent reads the log inside an
Anthropic-hosted sandbox, counts errors with `grep`/`awk`, and writes a short
Markdown report that the script downloads for you.

Anthropic runs the agent loop and the sandbox. Your code only creates the
agent once, starts a session per run, and streams events.

## How it works

```
setup_agent.py  (run once)        run.py  (run as often as you like)
  create environment ──┐            upload log  ──> Files API
  create agent ────────┴─> .agent.json ──> create session (pinned agent version, $2 budget)
                                           stream events  <── agent uses bash/read/write in sandbox
                                           download /mnt/session/outputs/report.md -> out/
```

- **Environment**: a cloud sandbox with limited network access (package managers only).
- **Agent**: Claude Opus 5.5 (`claude-opus-5-5`), a short system prompt, and the
  built-in agent toolset. Web search and web fetch are off because the job only
  needs the local file.
- **Session**: one run. The log is mounted read-only at
  `/mnt/session/uploads/app.log`. Anything the agent writes to
  `/mnt/session/outputs/` can be downloaded after the run.

## Prerequisites

- Python 3.10 or newer
- An Anthropic API key with Managed Agents access (the API is in beta)

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

python setup_agent.py          # once: creates the environment and agent, writes .agent.json
python run.py                  # triages sample/app.log
python run.py /path/to/your.log
```

You will see the agent's tool calls and messages as they happen. When it stops,
the report is saved to `out/report.md` and the script prints the session cost.
The script also prints a Console link where you can replay the whole session.

If you used `ant auth login` instead of an API key, skip the `export`; the SDK
picks up the profile.

## Change the agent

Edit `SYSTEM_PROMPT` or `TOOLS` in `setup_agent.py`, then run:

```bash
python setup_agent.py --update
```

This creates a new agent version and records it in `.agent.json`. Sessions
already running keep the version they started with.

## Tool approvals

The toolset uses the `auto` permission policy. The server approves low-risk
calls on its own. When it can't decide, `run.py` asks you `Allow? [y/N]` in the
terminal. With no terminal attached, it denies.

## Cost

- Tokens at Claude Opus 5.5 rates, plus session runtime at $0.08 per hour.
- Each session has a hard budget of $2.00 at list price (`BUDGET_CENTS` in
  `run.py`). If the agent hits it, the session pauses instead of spending more.
- A run on the sample log should cost well under that.

## Cleanup

Sessions, agents and environments stay in your account until you remove them.
List and remove them from the [Console](https://platform.claude.com), or with
`client.beta.sessions.delete(...)`. Archiving is permanent.

## Files

| File | What it does |
|---|---|
| `setup_agent.py` | Creates the environment and agent once, saves IDs to `.agent.json` |
| `run.py` | Uploads a log, runs a session, streams events, downloads the report |
| `sample/app.log` | 400 lines of synthetic logs with a payment timeout spike and a few other faults |
