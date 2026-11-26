# Option 4: Managed Agents, hosted, with a cloud sandbox

**Anthropic runs the agent loop and the container. You start sessions.**

You create an agent (model, prompt, tools) and an environment once. Each run is
a session: upload the log, send one message, and follow the event stream. The
agent uses bash and file tools inside an Anthropic-hosted container, writes
`report.md`, and the script downloads it.

```
setup_agent.py  (run once)        run.py  (run as often as you like)
  create environment ──┐            upload log  ──> Files API
  create agent ────────┴─> .agent.json ──> create session (pinned agent version, $2 budget)
                                           stream events  <── agent uses bash/read/write in sandbox
                                           download /mnt/session/outputs/report.md -> out/
```

## Who runs what

| Part | Where it runs |
|---|---|
| Agent loop | Anthropic |
| Tools | Anthropic's container, one per session, limited network |
| Model | Claude API (or Claude Platform on AWS). Not Bedrock |
| State and history | Anthropic stores agents, sessions and history until you delete them |
| Data that leaves your machine | The log file and everything the agent does with it |

## Run it

```bash
export ANTHROPIC_API_KEY=sk-ant-...       # or: ant auth login

python 4-managed-agents-cloud/setup_agent.py     # once: writes 4-managed-agents-cloud/.agent.json
python 4-managed-agents-cloud/run.py             # triages sample/app.log
python 4-managed-agents-cloud/run.py /path/to/your.log
```

To run on **Claude Platform on AWS** instead (AWS IAM and AWS Marketplace billing):

```bash
export CMA_PLATFORM=aws AWS_REGION=us-east-1 ANTHROPIC_AWS_WORKSPACE_ID=...
python 4-managed-agents-cloud/setup_agent.py
python 4-managed-agents-cloud/run.py
```

You'll see the agent's tool calls as they happen. The report lands in
`out/4-managed-agents-cloud/report.md`. The script prints a Console link where
you can replay the session, and the session's own token counts and list cost.

If you ran the first version of this demo, move `.agent.json` from the repo root
into this folder.

## Setup details

- **Environment**: cloud sandbox with limited networking (package managers only).
- **Agent**: Claude Opus 5.5, a short prompt, and the built-in agent toolset.
  Web search and web fetch are off because the job only needs the local file.
- **Session**: one run, pinned to an agent version, with a $2.00 budget at list
  price. If the agent hits it, the session pauses instead of spending more.
- **Approvals**: the toolset uses the `auto` permission policy. The server
  approves low-risk calls itself. When it can't decide, `run.py` asks you
  `Allow? [y/N]`. With no terminal attached, it denies.
- **Change the agent**: edit `SYSTEM_PROMPT` or `TOOLS` in `setup_agent.py`, then
  run `python 4-managed-agents-cloud/setup_agent.py --update`. Running sessions
  keep the version they started with.

## Requirements

- Python 3.10 or newer, `anthropic`
- A Claude Console organization (your Claude Platform subscription) with an API
  key, or a Claude Platform on AWS workspace
- Managed Agents is in beta. The SDK sends the beta header for you.

## Trade-offs

Good:
- Nothing to host. No harness, no container fleet, no scheduler.
- Long-running sessions with history, versioned agents, budgets, and a session viewer.
- The full feature set: scheduled deployments, webhooks, outcomes, multiagent
  workflows, memory stores, vaults, skills, and web tools.
- The cleanest hand-off for "run this unattended": a schedule plus a pinned agent version.

Not so good:
- Anthropic processes and stores the data, including session history, until you delete it.
- Not eligible for Zero Data Retention or HIPAA.
- The sandbox can't reach your private systems. They need an internet-reachable
  MCP server or API.
- Costs $0.08 per running session-hour on top of tokens.

## What changes for a Bedrock-first shop

- **Managed Agents doesn't run on Amazon Bedrock.** Hosted Managed Agents runs on
  the Claude API, Claude Platform on AWS, and Claude Models on Google Cloud
  (Anthropic managed). This is the biggest surprise for a Bedrock-only team.
- **Claude Platform on AWS** keeps the AWS relationship: SigV4 and IAM, PrivateLink,
  and AWS Marketplace billing in CCUs. It's a separate product from Bedrock with
  its own Anthropic organization, and Bedrock private pricing doesn't carry over.
  Confirm with your AWS team how it counts against your commitment.
- On Claude Platform on AWS, a session runs on its own for at most 6 hours
  before it needs a user event.
- The code doesn't change between the two. `common/cma.py` swaps the client.

Facts checked on 2026-11-26 against the Managed Agents and Claude Platform on AWS docs.
