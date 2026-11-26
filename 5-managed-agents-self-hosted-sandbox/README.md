# Option 5: Managed Agents with a self-hosted sandbox

**Anthropic runs the agent loop. Your worker runs the tools, next to your data.**

Same agent and sessions API as option 4. The difference is the environment:
`{"type": "self_hosted"}`. A worker you run long-polls Anthropic's work queue
and executes the agent's bash and file tools on your machine. All connections
go out from your network. Nothing dials in.

```
Anthropic                                   your machine / VPC / data center
  sessions API + agent loop + history         worker.py  (or: ant beta:worker poll)
  work queue  <──────── long-poll, outbound ──  runs bash/read/write in ./workspace
                ──── tool results go back ───>  app.log and report.md stay here
```

## Who runs what

| Part | Where it runs |
|---|---|
| Agent loop | Anthropic |
| Tools | Your worker, on your infrastructure |
| Model | Claude API (or Claude Platform on AWS). Not Bedrock |
| State and history | Anthropic stores agents, sessions and history |
| Data that leaves your machine | Tool inputs and outputs, such as grep results. The file itself stays |

## Run it

Three terminals, or two plus the Console.

```bash
# 1. Once: create the self-hosted environment and the agent
export ANTHROPIC_API_KEY=sk-ant-...
python 5-managed-agents-self-hosted-sandbox/setup.py
```

2\. In the Console, open the new environment (`log-triage-self-hosted`) and
choose **Generate environment key**. The key starts with `sk-ant-oat01-`.

```bash
# 3. Start a worker in its own terminal. Don't export ANTHROPIC_API_KEY here.
export ANTHROPIC_ENVIRONMENT_ID=env_...        # from .agent.json
export ANTHROPIC_ENVIRONMENT_KEY=sk-ant-oat01-...
python 5-managed-agents-self-hosted-sandbox/worker.py
#   or the CLI worker with the same tools:
#   ant beta:worker poll --workdir 5-managed-agents-self-hosted-sandbox/workspace

# 4. Run a session from the first terminal
python 5-managed-agents-self-hosted-sandbox/run.py
```

`run.py` checks that a worker is polling before it starts, copies the log into
`workspace/`, and reads `workspace/report.md` when the agent stops. There's no
download step, because the file never left your machine.

## Requirements

- Python 3.10 or newer, `anthropic` (the SDK worker helpers are in the Python,
  TypeScript and Go SDKs), or the `ant` CLI
- `/bin/bash` at that exact path on the worker host
- A Claude Console organization, or Claude Platform on AWS (see below)
- Self-hosted sandboxes are in beta

## Trade-offs

Good:
- Agents work on systems inside your network with no inbound ports and no MCP
  gateway in front of them.
- You pick the image, packages, CPU and egress rules.
- Anthropic still runs the loop, storage and API, so your workers are stateless
  and easy to scale.

Not so good:
- The worker does **not** isolate bash. Run each session's worker in a throwaway
  container or VM, with egress limited to what the job needs. That's on you.
- Self-hosted environments accept only memory store resources. File mounts and
  GitHub repo mounts don't work, so put data where the worker can read it.
- Vault `environment_variable` credentials aren't supported yet. Use MCP
  credentials or a tool your worker serves.
- Web search and web fetch still run on Anthropic's servers. They're off in this agent.
- Anthropic still processes the prompts, tool results and history. Not eligible
  for ZDR or HIPAA, same as option 4.

## What changes for a Bedrock-first shop

- Like option 4, this runs on the Claude API or Claude Platform on AWS, not Bedrock.
  Set `CMA_PLATFORM=aws` (plus `AWS_REGION` and `ANTHROPIC_AWS_WORKSPACE_ID`) for
  `setup.py` and `run.py`.
- On Claude Platform on AWS the worker authenticates with IAM (SigV4) or an
  AWS-issued API key, and its role needs the `AnthropicSelfHostedEnvironmentAccess`
  managed policy. Console-generated environment keys don't work there.
- On Claude Platform on AWS, sessions on self-hosted environments can't attach
  memory stores, and MCP tunnels aren't supported.
- Workers fit well on EKS or ECS, and on-prem hosts can poll over Direct Connect
  and PrivateLink.

Facts checked against
[Self-hosted sandboxes](https://platform.claude.com/docs/en/managed-agents/self-hosted-sandboxes)
on 2026-11-26.
