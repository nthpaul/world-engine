"""Run a deterministic custom SDK policy: no model, network, credentials, or files."""

import argparse
import asyncio
import json

from world_engine import Action, RunConfig
from world_engine.models import JsonObject
from world_engine.providers import Decision, ProviderError
from world_engine.rollout import replay, rollout


class MockObservationProvider:
    model = "deterministic-observation-mock-v1"

    def __init__(self):
        self.prepared = False
        self.closed = False

    async def prepare(self) -> None:
        self.prepared = True

    async def decide(self, observation: JsonObject, history: list[JsonObject]) -> Decision:
        if not self.prepared or self.closed:
            raise ProviderError("prepare the mock provider before deciding")
        available = {tool["name"] for tool in observation["tools"]}
        tool = "inspect" if not history else "finish"
        if tool not in available:
            raise ProviderError("mock policy requires inspect and finish tools")
        # This mock reads only the supplied public observation and episode-local history.
        return Decision(Action(tool=tool), usage={})

    async def close(self) -> None:
        self.closed = True
        self.prepared = False


async def run_example(environment_id: str = "access-provisioning", seed: int = 0) -> JsonObject:
    config = RunConfig(environment_id=environment_id, provider_id="scripted-baseline",
                       episodes=1, seed=seed, concurrency=1, max_steps=2,
                       timeout_seconds=5, evaluation_only=True, allow_paid=False)
    provider = MockObservationProvider()
    try:
        # A supplied provider is caller-owned: rollout does not prepare or close it.
        await provider.prepare()
        episode = await rollout(config, 0, provider)
        verification = replay(episode)
    finally:
        await provider.close()
    return {"config": config.model_dump(), "episode": episode, "replay": verification,
            "provider_closed": provider.closed, "model_calls": 0, "paid_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="access-provisioning")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    result = asyncio.run(run_example(args.environment, args.seed))
    episode = result["episode"]
    print(json.dumps({"provider_class": episode["provenance"]["provider_class"],
                      "provider_id": episode["provenance"]["provider_id"], "model": episode["provenance"]["model"],
                      "environment": result["config"]["environment_id"], "steps": episode["steps"],
                      "status": episode["status"], "termination": episode["termination"], "passed": episode["passed"],
                      "replay_verified": result["replay"]["verified"], "provider_closed": result["provider_closed"],
                      "evaluation_only": True, "model_calls": 0, "paid_calls": 0}))


if __name__ == "__main__":
    main()
