# Option 3: Claude Agent SDK on Bedrock

**A ready-made agent harness that you host.**

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
