# Option 3: Claude Agent SDK on Bedrock

**A ready-made agent harness that you host.**

## Choose this when

**Deciding factor: open-ended file and shell work, or reusing a Claude Code setup.**

- The agent has to explore a codebase or a folder, edit files and run commands.
  Read, Grep, Glob, Edit, Write and Bash come built in. [`fix.py`](fix.py) fixes a
  real bug with no tool code at all.
- Your team already uses Claude Code. The SDK loads the repo's `CLAUDE.md` and
  `.claude/skills/` the same way, so the agent follows the same house rules.
- You need guard rails without writing tools: permission rules, hooks,
  `max_turns`, `max_budget_usd`, and automatic compaction for long runs.
- Model calls must stay on Bedrock.

## Don't choose this when

- The job is a fixed pipeline. Option 1 is simpler and cheaper.
- You don't want to host and isolate a process that runs a real shell. Option 4
  hosts it for you, off Bedrock.
- You need many long-running sessions with stored history and a session viewer.
  That's what Managed Agents adds (options 4 to 6).

## How it works

The Agent SDK is the Claude Code engine as a library. You give it a prompt, a
working folder and a permission policy. It brings the agent loop, context
management, and built-in tools: Read, Grep, Glob, Bash, Write and more. The tools
run on your machine, in the folder you choose. Model calls go to Bedrock.

```
your app ─> query(prompt, options) ─> Agent SDK harness (your machine)
                                        ├─ Read / Grep / Bash / Write in out/3-agent-sdk/workspace
                                        └─ model calls ─> Claude in Amazon Bedrock
```

## Who runs what

| Part | Where it runs |
|---|---|
| Agent loop and context management | Agent SDK, in your process |
| Tools | Built-in tools, on your machine or container |
| Model | Claude in Amazon Bedrock (`CLAUDE_CODE_USE_MANTLE=1`) |
| State and history | Session files on your machine |
| Data that leaves your machine | Prompts and tool results sent to Bedrock |

## Run it

```bash
export AWS_PROFILE=my-profile AWS_REGION=us-east-1
python 3-agent-sdk/run.py
```

The script copies the log into `out/3-agent-sdk/workspace/` and the agent writes
`report.md` there. The `claude-agent-sdk` package bundles the Claude Code CLI it
drives, so there's nothing else to install.

## The permission setup

This run is built to work with nobody watching:

- `permission_mode="dontAsk"`: any call that would ask a person is denied instead.
- `allowed_tools`: Read, Grep, Glob, `Bash(awk *)`, and `Edit(/report.md)`, which
  also covers Write, for that one file in the working folder. Read-only shell
  commands such as `grep`, `sort` and `wc` need no rule.
- `disallowed_tools`: WebSearch and WebFetch.
- `max_turns=30` and `max_budget_usd=2.00` stop a run that goes long.
- `setting_sources=[]` ignores any `CLAUDE.md` or settings on the host, so runs repeat.

Read [Configure permissions](https://code.claude.com/docs/en/agent-sdk/permissions)
before you change these. In `bypassPermissions` mode, `allowed_tools` no longer
limits anything.

## The code-fix scenario: built-in tools plus policy

[`fix.py`](fix.py) runs the same job as option 2's `fix.py`. The agent gets the
log and the source of [`sample/payments-svc`](../sample/payments-svc/), finds the
code behind the top error, writes a failing test, fixes the bug and runs the
tests until they pass.

```bash
python 3-agent-sdk/fix.py                 # works in out/3-agent-sdk/fix-workspace/
python 3-agent-sdk/fix.py --max-budget 1.50
```

There's no tool code. What you write is policy:

| Setting | What it does here |
|---|---|
| `allowed_tools` | Read, Grep, Glob, `Edit(/**)` for the workspace, and `Bash(python -m unittest *)`, so the shell can run the tests and nothing else |
| `permission_mode="dontAsk"` | Anything not allowed is denied, with nobody watching |
| PreToolUse hook | Denies edits to `settings.py`, which CLAUDE.md asks the agent to leave alone |
| PostToolUse hook | Records every file the agent changed, printed at the end |
| PreCompact hook | Prints when the SDK summarizes a long context and carries on |
| `max_turns=40`, `max_budget_usd` | Hard stops |
| `setting_sources=["project"]` | Loads the service's own [`CLAUDE.md`](../sample/payments-svc/CLAUDE.md) |
| `skills=["fix-regression"]` | Loads the team's [skill](../sample/payments-svc/.claude/skills/fix-regression/SKILL.md) from `.claude/skills/` |
| `system_prompt` preset `claude_code` | The same system prompt your developers get in Claude Code |

The CLAUDE.md and the skill are files a team already keeps in its repo for
Claude Code. The SDK picks them up as they are. Option 2 would need code to
read and apply them.

One caution: the Bash tool runs with this process's environment, which holds
your AWS credentials for Bedrock. The permission rule limits what can run, but
for code you don't trust, run the SDK in a container with its own short-lived
credentials.

At the end, `common/codefix.py` checks the result the same way as option 2.

## Requirements

- Python 3.10 or newer, `claude-agent-sdk`
- Bedrock access to `anthropic.claude-opus-5-5` and `bedrock-mantle:CreateInference`
- For the InvokeModel endpoint instead of Mantle: set `CLAUDE_CODE_USE_BEDROCK=1`,
  use a model such as `us.anthropic.claude-opus-5-5`, and grant
  `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`

## Trade-offs

Good:
- Least code for a capable agent. File, search and shell tools work out of the box.
- The same harness your knowledge workers use in Claude Code. A prompt and
  folder that work there usually work here.
- Hooks, subagents, MCP servers, skills and sessions are built in.

Not so good:
- Bash is a real shell with your process's rights. Isolation is your job: run
  it in a throwaway container or VM with tight egress.
- You host and scale it: a container per job, a queue, a scheduler, logs, secrets.
- Heavier than options 1 and 2. It starts a CLI process for each query.
- The reported cost is the harness's estimate at list price, not your Bedrock bill.

Pick this when engineers want a coding or file-heavy agent on their own
infrastructure, with Bedrock as the only model provider.

## What changes for a Bedrock-first shop

- Two settings route it: `CLAUDE_CODE_USE_MANTLE=1` (or `CLAUDE_CODE_USE_BEDROCK=1`)
  and `AWS_REGION`. Credentials come from the AWS chain or `AWS_BEARER_TOKEN_BEDROCK`.
- Pin the model. Without a pin, aliases follow Claude Code's built-in default for
  Bedrock, which can change between releases.
- The WebSearch tool isn't available on Bedrock.
- Mantle needs `bedrock-mantle:*` IAM actions. The `bedrock:*` actions only cover InvokeModel.

Facts checked against
[Claude Code on Amazon Bedrock](https://code.claude.com/docs/en/amazon-bedrock) on 2026-11-26.
