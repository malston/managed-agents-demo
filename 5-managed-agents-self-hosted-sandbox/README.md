# Option 5: Managed Agents with a self-hosted sandbox

**Anthropic runs the agent loop. Your worker runs the tools, next to your data.**

## Choose this when

**Deciding factor: tools that need your private network, with Anthropic running the rest.**

- The agent has to reach internal systems: a database, an internal API, a file
  share. Your worker runs the tools inside your network, so it can. This demo's
  agent curls a deploy history API that listens on 127.0.0.1 only
  ([`private_api.py`](private_api.py)). Option 4's container can't reach it.
- Files should stay on your hosts. Only tool inputs and outputs go to Anthropic.
- You still want Anthropic to run the loop, store history and give you the session viewer.

## Don't choose this when

- Model calls must go through Bedrock, or session history must stay in your
  accounts. That's option 6.
- You don't want to run and isolate worker hosts. Option 4 needs none.

## How it works

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

## Reaching a private service

`run.py` starts [`private_api.py`](private_api.py), a deploy history API that
listens on `127.0.0.1:8765` only. The task asks the agent to curl it for the top
issue's service and say whether a deploy lines up with the first errors. It
does: payments-svc 2.14.0 shipped at 09:30:40, and the timeouts start at 09:31:38.

The call works because the agent's bash tool runs in your worker. The docs say
it is "a real shell with the worker process's permissions and network access".
Option 4's container is on Anthropic's network, and this API isn't reachable
from there.

The demo assumes the worker runs on the same machine as `run.py`. In real use,
the API is an internal service, and the worker runs where its network can reach
it. Don't give the worker more network than the job needs.

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
