# One job, six ways to build it with Claude

Every folder here solves the same task: read an application log, find the
errors and spikes, and write a one-page triage report. Only the way it's built
changes. Run them side by side and the trade-offs stop being abstract.

Log triage is too small to show what a full agent harness buys you, so options
2 and 3 also do a second job: **fix the bug behind the top error** in a small
service ([`sample/payments-svc`](sample/payments-svc/)). Each option's README
opens with "Choose this when" and names the one factor that decides it.

The examples target a team that **runs all Claude models through Amazon
Bedrock**, has a Claude Enterprise plan for people and a Claude Platform (Console)
organization for developers, and wants to know what it takes to run agents
unattended on Claude Managed Agents (CMA).

All facts were checked against Anthropic's and AWS's docs on **2026-11-26**.
Managed Agents is in beta, and self-hosted Managed Agents is a private beta, so
check the linked pages before you rely on a detail.

## The six options

| # | Folder | You write | Agent loop runs in | Tools run on | Model calls go to | Session history lives in |
|---|---|---|---|---|---|---|
| 1 | [`1-messages-workflow`](1-messages-workflow/) | Every step. Claude writes the text | Your code (no loop) | No tools | Bedrock (Mantle) | Nowhere |
| 2 | [`2-messages-agent-loop`](2-messages-agent-loop/) | The tools | Your process (SDK tool runner) | Your process | Bedrock (Mantle) | Your process memory |
| 3 | [`3-agent-sdk`](3-agent-sdk/) | A prompt and a permission policy | Your machine (Agent SDK) | Your machine | Bedrock (Mantle) | Files on your machine |
| 4 | [`4-managed-agents-cloud`](4-managed-agents-cloud/) | Agent config, then sessions | Anthropic | Anthropic's container | Claude API or Claude Platform on AWS | Anthropic |
| 5 | [`5-managed-agents-self-hosted-sandbox`](5-managed-agents-self-hosted-sandbox/) | Agent config, sessions, a worker | Anthropic | Your worker | Claude API or Claude Platform on AWS | Anthropic |
| 6 | [`6-self-hosted-cma-bedrock`](6-self-hosted-cma-bedrock/) | Agent config, sessions, plus you run the service | Your `cma-server` | Your workers | Bedrock (InvokeModel) | Your PostgreSQL |

| # | Runs on Bedrock? | Anthropic processes the data? | ZDR eligible | You operate | Unattended runs | Status |
|---|---|---|---|---|---|---|
| 1 | Yes | No, AWS does | Bedrock terms | Your app | Your scheduler | GA |
| 2 | Yes | No, AWS does | Bedrock terms | Your app and the loop | Your scheduler | Tool runner is beta |
| 3 | Yes | No, AWS does | Bedrock terms | The harness host and its isolation | Your scheduler | Released, 0.x versions |
| 4 | **No** | Yes, and stores history | No | Nothing | Scheduled deployments, webhooks | Beta |
| 5 | **No** | Yes, and stores history | No | Worker hosts | Scheduled deployments, webhooks | Beta |
| 6 | Yes | No, with Bedrock as provider | Follows provider terms | Everything | Your scheduler | Private beta |

## What to remember

- **Hosted Managed Agents isn't on Bedrock.** Options 4 and 5 run on the Claude
  API or on Claude Platform on AWS (Anthropic-operated, IAM, PrivateLink, AWS
  Marketplace billing). Claude Platform on AWS is a separate product from Bedrock,
  with its own Anthropic organization and pricing.
- **The only way to keep Managed Agents on Bedrock is option 6**, self-hosted,
  which you get through your Anthropic account team.
- **Options 4, 5 and 6 share one API.** Agent definitions and session code move
  between them by changing the base URL and credentials. See [`common/cma.py`](common/cma.py).
- **The further down the list, the less code you write and the more you hand
  over or operate.** Options 1 and 2 keep everything in your app. Option 4 hands
  the whole runtime to Anthropic. Option 6 hands nothing over and makes you run all of it.
- **Bash is the risk line.** Options 1 and 2 have no shell. Options 3, 5 and 6
  run a real shell on your infrastructure, so isolation is your job. Option 4
  runs it in Anthropic's container.
- **Bedrock has two endpoints.** Options 1 to 3 use `bedrock-mantle` (Messages API
  shape, `anthropic.` model IDs, `bedrock-mantle:*` IAM). Option 6's server uses
  InvokeModel (`us.anthropic.` profiles, `bedrock:*` IAM).
- **On Bedrock, web search and web fetch aren't available** in any option. Give
  agents an internal search tool if they need one.

## Which demo shows which reason

Each demo is built so its output shows the factor that sets its option apart.

| # | Choose it for | What the demo shows | Where to look |
|---|---|---|---|
| 1 | A fixed, predictable task | The same facts every run, and the cost and time of 1,000 logs | `run.py --repeat 3` |
| 2 | A few tools you control, in your own app | A tool that calls your service catalog in-process. Then the code-fix job, where you write about 75 lines of file, edit and test tools, plus their guard rails | `run.py`, `fix.py` |
| 3 | Open-ended file and shell work, or reusing a Claude Code setup | The same code-fix job with no tool code: built-in tools, permission rules, hooks, budget and turn limits, compaction, and the repo's own CLAUDE.md and skill | `fix.py` |
| 4 | Nothing to host, many long-running sessions | Start a session, close the terminal, reattach later and catch up. A grader checks the report against a rubric | `run.py --detach`, `--attach` |
| 5 | Tools that need your private network | The agent curls a deploy history API that only listens on 127.0.0.1, which option 4's container can't reach | `private_api.py`, `run.py` |
| 6 | Bedrock inference, or full control of the data | Tokens on Bedrock, and the session history read back from your own PostgreSQL | `run.py --history` |

`compare.py` prints a second table with what you host, where the data and
history live, who bills you, and how many lines of tool and hook code each
option needed.

## Which one to pick

- **An AI step inside an app, with known steps** (summarize, classify, draft): option 1.
- **An agent inside your own app, calling your own systems:** option 2.
- **A coding or file-heavy agent on your infrastructure, Bedrock only:** option 3.
- **An unattended agent where Anthropic hosting the data is acceptable:** option 4.
  It has the most features and the least to run.
- **The same, but the agent must touch systems inside your network:** option 5.
- **Agents with history and data that must stay in your accounts, Bedrock only:** option 6.

### From a knowledge worker's prototype to an unattended run

People with Claude Enterprise seats can prototype an agent in Claude Code: a
prompt, a folder, a few tools. That maps well to option 3, since the Agent SDK
is the same harness. When engineering takes it over to run unattended, the
prompt and tool list become a Managed Agents agent definition (option 4, 5 or 6)
kept in git and synced with `ant apply`, and a schedule starts the sessions. The
agent file in [`6-self-hosted-cma-bedrock/log-triage-agent.md`](6-self-hosted-cma-bedrock/log-triage-agent.md)
shows that format.

## Run the comparison

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python compare.py --check        # which options are ready, and why not
python compare.py                # run every ready option on sample/app.log
python compare.py --only 1,2,3   # just the Bedrock ones
python compare.py --scenario fix # the code-fix job, on options 2 and 3
```

Each option runs as its own process, exactly as you'd run it by hand. The script
prints a table of wall time, tokens, model calls, tool calls, estimated cost and
the platform's own reported cost, then saves `out/comparison-<scenario>.json`.
Reports land in `out/<option>/`. A second table shows how each option is built:
lines of tool code and hook code you wrote (counted between `tool code` and
`hook code` markers in each script), what you host, where data and history live,
and the billing path. For the code-fix scenario, the notes under the table say whether
the fix passed the same model-free check for both options.

What each option needs before `compare.py` will run it:

| Option | Needs |
|---|---|
| 1, 2, 3 | AWS credentials with access to `anthropic.claude-opus-5-5` on Claude in Amazon Bedrock |
| 4 | `ANTHROPIC_API_KEY` (or `CMA_PLATFORM=aws`), then `python 4-managed-agents-cloud/setup_agent.py` |
| 5 | Same as 4 with `setup.py`, plus a worker running in another terminal |
| 6 | A running `cma-server`, `CMA_SELF_HOSTED_URL` and `CMA_SELF_HOSTED_API_KEY` |

**About the cost column.** The estimate prices tokens at Claude API list price
for Claude Opus 5.5 ($4 in, $20 out, $5 cache write, $0.20 cache read per million
tokens) and adds $0.08 per running session-hour for options 4 and 5. Bedrock bills
at AWS's prices, and regional Bedrock endpoints cost 10% more than global ones, so
for Bedrock options treat the number as a yardstick. Edit `common/metrics.py` to
use your rates. Self-hosted Managed Agents has a separately quoted license.

Expect the order to be roughly 1, then 2, then the rest, for both time and
tokens. Options 3 to 6 use real shell tools and read more of the log, so they
cost more and vary more between runs.

## Repository layout

```
common/            shared report spec, log parsing, metrics, Managed Agents client code,
                   the code-fix scenario (codefix.py) and a stand-in service catalog
sample/app.log     400 lines of synthetic logs with a payment timeout spike and a few other faults
sample/payments-svc  the service behind that spike, with the bug, its tests, a CLAUDE.md and a skill
1-... to 6-...     one folder per option, each with run.py and a README; 2 and 3 also have fix.py
compare.py         runs the options and prints the comparison
tests/             offline tests: python -m unittest discover tests
```

## Tests

`python -m unittest discover tests` runs without credentials. It checks the log
helpers against the sample, and runs option 2's full agent loop against a fake
Bedrock endpoint to confirm the tools, tool results and usage counting work.
It also replays a fake option 4 event stream with two grader passes to check
the outcome is sent as the kickoff and the grader's tokens are summed, and a
reattach that must not repeat events.

For the code-fix scenario, the tests confirm the service reproduces the log's
"after 30000ms" error, that a known good fix passes the check and the unfixed
code doesn't, that option 2's tools refuse paths outside the workspace and edits
to settings, and that option 3's hook denies settings edits. Option 5's private
API is checked too.
None of the six options has been run against live Bedrock or Managed Agents from
this repo yet.
