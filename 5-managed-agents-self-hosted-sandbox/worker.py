"""A self-hosted sandbox worker for option 5, built on the SDK's EnvironmentWorker.

It long-polls Anthropic's work queue (outbound HTTPS only, no open ports) and
runs the agent's bash and file tools in ./workspace on this machine.

    export ANTHROPIC_ENVIRONMENT_ID=env_...
    export ANTHROPIC_ENVIRONMENT_KEY=sk-ant-oat01-...   # from the Console, not your API key
    python 5-managed-agents-self-hosted-sandbox/worker.py

The `ant` CLI does the same with one command:
    ant beta:worker poll --workdir 5-managed-agents-self-hosted-sandbox/workspace

Don't set ANTHROPIC_API_KEY in the worker's shell. The agent's bash tool runs
with this process's environment, so it could read an organization-wide key.
The worker does not isolate bash. Run it in a throwaway container or VM for
anything beyond a demo.
"""

import asyncio
import contextlib
import os
import signal
from pathlib import Path

from anthropic import AsyncAnthropic
from anthropic.lib.environments import EnvironmentWorker

WORKDIR = Path(__file__).resolve().parent / "workspace"


async def main() -> None:
    environment_key = os.environ["ANTHROPIC_ENVIRONMENT_KEY"]
    environment_id = os.environ["ANTHROPIC_ENVIRONMENT_ID"]
    WORKDIR.mkdir(exist_ok=True)
    async with AsyncAnthropic(auth_token=environment_key) as client:
        worker = EnvironmentWorker(
            client,
            environment_id=environment_id,
            environment_key=environment_key,
            workdir=WORKDIR,
        )
        print(f"Worker polling environment {environment_id}, tools run in {WORKDIR}")
        task = asyncio.create_task(worker.run())
        # Cancel the task on Ctrl+C or SIGTERM so the worker stops its work item cleanly.
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, task.cancel)
        with contextlib.suppress(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    asyncio.run(main())
