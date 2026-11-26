# Option 6: Self-hosted Managed Agents, with Bedrock as the model

**You run the whole Managed Agents service. Model calls go to Bedrock.**

## Choose this when

**Deciding factor: Bedrock inference, or full control of the data.**

- Model calls must go through Bedrock, under your AWS agreement and billing, and
  you still want the Managed Agents API.
- Session history must stay in your accounts. The server stores agents, sessions
  and history in your PostgreSQL. `run.py --history` reads them back from there.
- Nothing in a run may reach Anthropic. With Bedrock as the provider, the server
  doesn't connect to Anthropic.

## Don't choose this when

- You don't want to run a service: cma-server, PostgreSQL, workers, upgrades.
  Options 4 and 5 run it for you.
- You need it today without a sales conversation. It's a private beta, through
  your Anthropic account team.
- You need features the docs don't confirm for self-hosted yet, such as outcomes.

## How it works

`cma-server` serves the same sessions API as options 4 and 5, runs the agent
loop, and keeps agents, sessions and history in your PostgreSQL. Your workers run
the tools. With `inference.provider: bedrock`, the server calls Claude on
Bedrock's InvokeModel API with your AWS credentials. In that setup, nothing in a
run reaches Anthropic.

```
your network (Compose host, or EKS + RDS)
  run.py ─> cma-server ── agent loop ── InvokeModel ─> Amazon Bedrock (your AWS account)
               │  └─ PostgreSQL 16+ (agents, sessions, history)
               └─ work queue <── sandbox workers (one container per session)
```

> **Status: private beta.** You get the release archive through your Anthropic
> account team, and pricing is by quote. This folder ships the Bedrock settings,
> the agent file and a client script. It can't include the server itself. The
> script is untested against a live server.

## What's in this folder

| File | What it is |
|---|---|
| `config/inference-bedrock.yaml` | The `inference` block to merge into the server's settings file |
| `config/bedrock-iam-policy.json` | IAM permissions the server's AWS identity needs |
| `config/helm-values-bedrock.yaml` | The same settings for the Kubernetes Helm chart |
| `log-triage-agent.md` | The agent, as a file for `ant apply` |
| `run.py` | Starts a session on your server, sends the log, saves the report |

## Walkthrough (Docker Compose)

These steps follow the self-hosted
[quickstart](https://platform.claude.com/docs/en/managed-agents/self-hosted/quickstart)
and [Inference provider](https://platform.claude.com/docs/en/managed-agents/self-hosted/inference-provider)
pages. Your release's `operator-guide.md` is the final word on keys and values.

1. **Enable the model in Bedrock.** In the AWS account the server will use, turn
   on access to Claude Opus 5.5 and its `us.anthropic.` cross-region inference
   profile. Attach `config/bedrock-iam-policy.json` to the server's role or user.

2. **Extract the archive and create `.env`** as the quickstart shows
   (`CMA_PG_PASSWORD`, `CMA_SERVER__API_KEY`, `CMA_STORE__CREDENTIALS_ENCRYPTION_KEY`).
   With Bedrock as the provider, the server ignores `ANTHROPIC_API_KEY`.

3. **Point inference at Bedrock.** Merge `config/inference-bedrock.yaml` into
   `compose/compose.config.yaml`. The same keys work as environment variables:
   `CMA_INFERENCE__PROVIDER=bedrock`, `CMA_INFERENCE__REGION=us-east-1`.

4. **Give the server AWS credentials.** It signs calls with the AWS SDK's
   default chain. On an EC2 host with an instance role, you need nothing else.
   On a workstation, add the AWS variable names (for example `AWS_PROFILE`, or
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_SESSION_TOKEN`) to the
   `environment:` list of the `cma-server` service in `docker-compose.yml`, and
   set their values in `.env`. To use a profile, mount `~/.aws` read-only through
   the `x-server-mounts` list. An upgrade replaces `docker-compose.yml`, so redo
   these edits after each one.

5. **Start it**: `docker compose up --build -d`, then
   `curl -s http://127.0.0.1:8400/cma-server/readyz` until it says `ready`. A log
   line `upstream credential resolved provider=bedrock` means credentials work. It
   doesn't prove the model is enabled. A missing model shows up as a
   `session.error` on the first turn.

6. **Create the agent**, in a second terminal (not the one you run Compose in):

   ```bash
   export ANTHROPIC_BASE_URL=http://127.0.0.1:8400
   export ANTHROPIC_API_KEY=$(grep '^CMA_SERVER__API_KEY=' .env | cut -d= -f2)
   ant apply --yes 6-self-hosted-cma-bedrock/log-triage-agent.md
   ```

   A warning that it "could not determine the organization and workspace" is expected.

7. **Run the demo:**

   ```bash
   export CMA_SELF_HOSTED_URL=$ANTHROPIC_BASE_URL CMA_SELF_HOSTED_API_KEY=$ANTHROPIC_API_KEY
   python 6-self-hosted-cma-bedrock/run.py
   ```

   It uses the stack's `compose-sandbox` environment, whose workers start a
   container per session. `run.py` reads its own variable names so it can't send
   your server key to Anthropic by mistake.

On Kubernetes, put the settings under `server.config` in the Helm values, and
give the server a workload identity (IRSA or EKS Pod Identity) through
`server.serviceAccountName`. See `config/helm-values-bedrock.yaml` and the
[Kubernetes guide](https://platform.claude.com/docs/en/managed-agents/self-hosted/kubernetes).

## How the log gets in

Your server has no Files API and rejects `file` session resources. `run.py`
sends the log inside the message as a text document, and the agent saves it to
`app.log` in its sandbox before it counts anything. The agent replies with the
report as its last message. For large inputs, put the data where the worker can
read it instead.

## Where the history lives

After the run, `run.py` reads the session's events back from your server:

```
History for sesn_..., read from http://127.0.0.1:8400 (stored in your server's PostgreSQL):
  41 events: 14 agent.tool_use, 14 agent.tool_result, 6 agent.message, ...
```

(Example output.) `python 6-self-hosted-cma-bedrock/run.py --history sesn_...`
prints a stored session again later. The
[data and access page](https://platform.claude.com/docs/en/managed-agents/self-hosted-data-and-access)
says the server stores agents, sessions and session history in your database,
and "connects to Anthropic only when that provider is the Claude API". Tokens go
to Bedrock and show up on your AWS bill.

## Who runs what

| Part | Where it runs |
|---|---|
| Agent loop and API | Your `cma-server` |
| Tools | Your workers (Compose containers or Kubernetes pods) |
| Model | Amazon Bedrock, InvokeModel, in your AWS account |
| State and history | Your PostgreSQL |
| Data that leaves your network | Model calls to Bedrock only |

## Trade-offs

Good:
- History, agents and secrets live in your database and your secret stores.
- With Bedrock, AWS is the only outside processor in the run. Bedrock spend lands on your AWS bill.
- Zero Data Retention eligibility follows your model provider's terms. It's the
  only Managed Agents mode that's ZDR eligible.
- Same sessions API and SDK code as the hosted options. Moving a workload
  between tiers is a base URL and key change.
- SSO through your own OIDC identity provider, with group-to-role mapping.

Not so good:
- You operate everything: the server, PostgreSQL, TLS, backups, upgrades, worker
  isolation, and log retention.
- Fewer features than hosted: no cloud environments, Files API, scheduled
  deployments, webhooks, dynamic workflows, advisor, `mcp_oauth` vault
  credentials, or prebuilt document skills. Bring your own scheduler (cron,
  EventBridge, a Kubernetes CronJob) and poll the event stream in place of webhooks.
- Private beta, with no published release cadence or support terms in the docs.
- HIPAA isn't addressed in the self-hosted docs. Confirm scope with AWS and your
  Anthropic account team.

## What changes for a Bedrock-first shop

- One setting moves every model call to Bedrock. Agents keep plain Claude IDs
  like `claude-opus-5-5`, and the server adds `us.anthropic.` for the inference profile.
- On Bedrock, the model never gets `web_search` or `web_fetch`, even if an agent
  lists them. Give agents an internal search tool or MCP server instead.
- `inference_geo` isn't allowed. Use the Bedrock region and inference profile to
  control where inference runs.
- Server-side refusal fallback works only with the `anthropic` provider. On
  Bedrock, a refused request ends the turn.
- This path uses Bedrock's InvokeModel API and `bedrock:*` IAM actions, unlike
  options 1 to 3, which use the Mantle endpoint and `bedrock-mantle:*` actions.

Facts checked on 2026-11-26 against the
[self-hosted overview](https://platform.claude.com/docs/en/managed-agents/self-hosted),
[configuration reference](https://platform.claude.com/docs/en/managed-agents/self-hosted/configuration-reference),
and [differences from hosted](https://platform.claude.com/docs/en/managed-agents/self-hosted/differences).
