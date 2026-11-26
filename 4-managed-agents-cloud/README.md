# Option 4: Managed Agents, hosted, with a cloud sandbox

**Anthropic runs the agent loop and the container. You start sessions.**

You create an agent (model, prompt, tools) and an environment once. Each run is
a session: upload the log, define an outcome, and follow the event stream. The
agent uses bash and file tools inside an Anthropic-hosted container, writes
`report.md`, and a separate grader checks it against `rubric.md`. The agent
revises until the grader is satisfied or runs out of tries. Then the script
downloads the report.

```
setup_agent.py  (run once)        run.py  (run as often as you like)
  create environment ──┐            upload log  ──> Files API
  create agent ────────┴─> .agent.json ──> create session (pinned agent version, $5 budget)
                                           send user.define_outcome (task + rubric.md)
                                           stream events  <── agent uses bash/read/write in sandbox
                                                          <── grader passes: needs_revision ... satisfied
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
python 4-managed-agents-cloud/run.py --max-iterations 5   # allow more grader passes (1 to 20)
python 4-managed-agents-cloud/run.py --no-outcome         # plain message, no grader, $2 budget
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

## Outcomes: a grader checks the report

By default `run.py` doesn't send a plain message. It sends one
`user.define_outcome` event, and the agent starts work as soon as it arrives:

```python
{
    "type": "user.define_outcome",
    "description": OUTCOME_TASK,                       # the task, plus what the grader checks
    "rubric": {"type": "text", "content": RUBRIC.read_text()},
    "max_iterations": 3,                               # --max-iterations, default 3, max 20
}
```

A separate grader reads the report in `/mnt/session/outputs/`, scores it against
[`rubric.md`](rubric.md), and either passes it or sends back what's missing.
The rubric checks that the report names a root cause, cites log lines by
timestamp or `req_id`, gives each issue a severity, and gives a next action for
each high-severity issue. It also checks the counts against the log. Edit the
rubric to fit your own reports.

The stream shows each grader pass (example output):

```
[grader] iteration 0: evaluation started .....
[grader] iteration 0: needs_revision (2,000 in / 300 out tokens)
         No severity on issues.
[grader] iteration 1: evaluation started ...
[grader] iteration 1: satisfied (2,500 in / 200 out tokens)
```

Those lines come from `span.outcome_evaluation_start`, `_ongoing` (a heartbeat)
and `_end`. The end event carries the result (`satisfied`, `needs_revision`,
`max_iterations_reached`, `failed` or `interrupted`), the grader's explanation
and its token usage. The summary at the end prints the last result, the number
of revisions, and the grader's tokens. `compare.py` shows the same in its
outcome column.

The report is fetched the same way as before, through the Files API with
`scope_id` set to the session ID.

Things to know:

- **Outcomes are in beta.** The API and events may change.
- **Not HIPAA eligible, and not ZDR eligible** on hosted Managed Agents.
- **Self-hosted Managed Agents (option 6) isn't confirmed.** The outcomes docs
  list the Claude API, Claude Platform on AWS and Claude Models on Google Cloud.
  They don't mention self-hosted, so option 6 doesn't use outcomes.
- **Grader billing isn't documented.** The docs don't say whether the session's
  usage already counts the grader's tokens. The demo shows them apart and
  leaves them out of the estimated cost, so the real cost may be higher.
- Each revision is another round of agent work, so the budget goes up to $5.
  Use `--no-outcome` to see the plain run and compare the two.

## Setup details

- **Environment**: cloud sandbox with limited networking (package managers only).
- **Agent**: Claude Opus 5.5, a short prompt, and the built-in agent toolset.
  Web search and web fetch are off because the job only needs the local file.
- **Session**: one run, pinned to an agent version, with a $5.00 budget at list
  price ($2.00 with `--no-outcome`). If the agent hits it, the session pauses instead of spending more.
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

Facts checked on 2026-11-26 against the Managed Agents and Claude Platform on AWS docs,
including https://platform.claude.com/docs/en/managed-agents/define-outcomes.md.
