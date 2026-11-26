# Option 2: Messages API agent loop on Bedrock

**Claude decides which tools to call. Your process runs them.**

## Choose this when

**Deciding factor: a few tools you control, inside your own app.**

- The agent needs to call your own APIs with your app's credentials and rules.
  Here `lookup_owner` calls the service catalog in-process. Nothing new is
  exposed, and no shell is involved.
- You want every tool to be narrow and reviewed, and no general file or shell access.
- The loop has to live inside an existing service, with your logging, retries and auth.

## Don't choose this when

- The job is open-ended file and shell work, like fixing code. You'd have to write
  read, search, edit and test tools, plus their guard rails. [`fix.py`](fix.py)
  does exactly that, so you can see the cost: compare its tool code with option 3's.
- Runs get long. The tool runner doesn't compact context, so every file the agent
  reads stays in the conversation.

## How it works

You write a few small Python functions as tools. The SDK's tool runner does the
loop: send the request, run whatever tools Claude asked for, send the results
back, and repeat until Claude stops. Claude chooses the order and how many calls
it needs.

```
your process                                       Claude in Amazon Bedrock
  tool runner ── request + tool list ──────────────>  "call count_by(level=ERROR)"
  runs count_by() <────────────────────────────────
  tool runner ── tool result ──────────────────────>  "call search_log(...)"
  ...repeats until Claude calls write_report and stops
```

The tools here are narrow: `log_overview`, `count_by`,
`search_log` and `error_spikes` only read, and `write_report` saves one file. Claude can't run a shell. That's
a choice you get to make with this option, and it's the main safety lever.

## Who runs what

| Part | Where it runs |
|---|---|
| Agent loop | Your process (SDK tool runner) |
| Tools | Your process, functions you wrote |
| Model | Claude in Amazon Bedrock |
| State and history | In memory for the run. You store it if you need it |
| Data that leaves your machine | Whatever your tools return to Claude |

## Run it

```bash
export AWS_PROFILE=my-profile AWS_REGION=us-east-1
python 2-messages-agent-loop/run.py
```

You'll see each tool call as it happens. The report goes to
`out/2-messages-agent-loop/report.md`.

## The code-fix scenario: what hand-written tools cost

[`fix.py`](fix.py) gives the agent the log plus the source of a small service,
[`sample/payments-svc`](../sample/payments-svc/). The top error says the gateway
timed out "after 30000ms", but the settings say `3s`. The agent has to find the
code behind it, write a failing test, fix the code and get the tests to pass.

```bash
python 2-messages-agent-loop/fix.py                 # works in out/2-messages-agent-loop/fix-workspace/
python 2-messages-agent-loop/fix.py --max-budget 1.50
```

To do that here, you write all of this yourself:

| You write | Why |
|---|---|
| `list_files`, `read_file`, `search_code` | The model can only see what a tool returns |
| `edit_file`, `write_file` | Exact-once replacement, so an edit can't hit the wrong place |
| `run_tests` | Runs the suite with credentials stripped from the environment and a time limit |
| Path checks | Every tool refuses paths outside the workspace |
| A settings guard | `edit_file` refuses `settings.py`, the rule the team writes in CLAUDE.md |
| Budget and turn handling | The loop stops when the estimated cost passes `--max-budget` |

That's about 75 lines of tool code, between the `tool code` markers, before
tests. `run_tests` still runs code on your machine: it isn't a sandbox. Option 3
does the same job with no tool code. `compare.py --scenario fix` prints both
counts.

At the end, `common/codefix.py` checks the result without a model: the suite
passes, `parse_duration_ms("3s")` returns 3000, a test was added, and
`settings.py` is unchanged.

## Requirements

Same as option 1: `anthropic[bedrock]`, Bedrock access to `anthropic.claude-opus-5-5`,
and `bedrock-mantle:CreateInference`.

## Trade-offs

Good:
- Claude adapts. A strange log line can lead it to search for more context.
- You still own every tool, so you decide exactly what it can touch.
- No new service. It's a library call inside your app, on your existing Bedrock setup.

Not so good:
- More tokens and more time than option 1, because each tool result goes back into the conversation.
- Runs vary. The number of calls changes from run to run.
- You own the rest of the harness: retries, long-run state, context limits,
  approvals, logs, and scheduling. `MAX_ITERATIONS` is the only guard rail here.
- The tool runner is a beta helper in the SDK.

Pick this when you want an agent inside your own app, with tools that call your
own systems, and you're fine owning the runtime.

## What changes for a Bedrock-first shop

- Same client and model ID rules as option 1.
- Bedrock runs client tools only. Server tools such as web search and code
  execution aren't on Claude in Amazon Bedrock, so anything like that must be a
  tool you write.
- Claude Opus 5.5 doesn't accept a forced `tool_choice` (`any` or `tool`). Steer
  tool use from the prompt, as this demo does.
- For refusal fallbacks, Bedrock has no server-side `fallbacks` parameter. The
  SDK's client-side `BetaRefusalFallbackMiddleware` is the documented path if you need it.

Facts checked on 2026-11-26.
