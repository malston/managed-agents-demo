# Option 2: Messages API agent loop on Bedrock

**Claude decides which tools to call. Your process runs them.**

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
