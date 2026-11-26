# Option 1: Messages API workflow on Bedrock

**Your code decides every step. Claude writes one thing.**

Python reads the log and computes all the numbers: counts per level and
service, grouped error patterns, error spikes. Claude gets that small JSON
summary in one request and writes the report. Claude has no tools and makes no
choices about what to do next.

```
your code: parse log ─> compute facts ─> one Messages API call ─> save report.md
                                              │
                                   Claude in Amazon Bedrock
```

## Who runs what

| Part | Where it runs |
|---|---|
| Control flow | Your code, fixed order |
| Tools | None |
| Model | Claude in Amazon Bedrock (`bedrock-mantle` endpoint) |
| State and history | Nothing is stored. Each run is one request |
| Data that leaves your machine | The JSON facts, not the raw log |

## Run it

```bash
pip install -r requirements.txt           # from the repo root
aws sso login --profile my-profile        # or any AWS credential source
export AWS_PROFILE=my-profile AWS_REGION=us-east-1

python 1-messages-workflow/run.py         # triages sample/app.log
python 1-messages-workflow/run.py /path/to/your.log
```

The report goes to `out/1-messages-workflow/report.md`, and the script prints
time, tokens and an estimated cost.

## Requirements

- Python 3.10 or newer, `anthropic[bedrock]`
- An AWS account with access to Claude Opus 5.5 (`anthropic.claude-opus-5-5`) in Claude in Amazon Bedrock
- IAM permission `bedrock-mantle:CreateInference` on that model
- Credentials from the normal AWS chain (profile, SSO, role), or a Bedrock API key in `AWS_BEARER_TOKEN_BEDROCK`

## Trade-offs

Good:
- Cheapest and fastest of the six. One request, small input, no loop.
- Same answer shape every run. The numbers come from code, so they're exact and testable.
- Easy to review and to explain to security. Nothing runs that you didn't write.

Not so good:
- It only answers the questions you coded for. A new kind of log needs new parsing code.
- No investigation. Claude can't go back and look at a line it finds odd.
- You own all the logic, so the code grows as the job grows.

Pick this when the steps are known ahead of time: summarize, classify, extract,
draft. Most "AI features" in internal apps fit here.

## What changes for a Bedrock-first shop

- Use `AnthropicBedrockMantle` from the Anthropic SDK. After that, the code is the
  same Messages API as on the Claude API.
- Model IDs carry an `anthropic.` prefix: `anthropic.claude-opus-5-5`.
- Bedrock bills the tokens at AWS's prices, on your AWS bill. The script's cost
  estimate uses Claude API list prices as a yardstick.
- Not on Claude in Amazon Bedrock: the Files API, server tools (web search, web
  fetch, code execution), Agent Skills, the MCP connector, Message Batches, and
  server-side refusal fallbacks. This demo uses none of them.
- Anthropic has no access to the Bedrock inference infrastructure. Data handling
  follows AWS's Bedrock terms.

Facts checked against
[Claude in Amazon Bedrock](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock)
on 2026-11-26.
