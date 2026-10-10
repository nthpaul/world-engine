"""Run: uv run python examples/sdk_world.py. No model endpoint or API key required."""

import asyncio
import tempfile
from pathlib import Path

from world_engine import ENVIRONMENTS, Action, RunConfig
from world_engine.environments import COMMON_TOOLS, Empty, Environment, Tool
from world_engine.models import grade
from world_engine.providers import Decision
from world_engine.rollout import RunManager, replay
from world_engine.store import Store


class WarehouseRelease(Environment):
    id = "warehouse-release"
    name = "Warehouse Release"
    description = "Release a shipment after the trusted inventory check."
    tools = COMMON_TOOLS + (
        Tool("check_inventory", "Check the allocated inventory before release.", Empty),
        Tool("release", "Release the checked shipment once.", Empty),
    )

    def build(self):
        return {"role": "warehouse-agent", "shipment_id": self.rng.randrange(1000, 9999),
                "checked": False, "status": "held", "audit": []}, "Check inventory, release the shipment, and finish."

    def apply(self, tool, args):
        from world_engine.environments import OperationDenied
        if tool == "check_inventory":
            self.state["checked"] = True
        elif tool == "release":
            if not self.state["checked"]:
                raise OperationDenied("inventory must be checked before release")
            self.state["status"] = "released"
        return {"message": "operation applied"}

    def evaluate(self):
        return grade([("shipment-release", self.state["checked"] and self.state["status"] == "released",
                       "Checked shipment was released.")])


class WarehousePolicy:
    model = "warehouse-script-v1"

    async def decide(self, observation, history):
        state = observation["state"]
        tool = "check_inventory" if not state["checked"] else "release" if state["status"] == "held" else "finish"
        return Decision(Action(tool=tool))


async def main():
    # Registration executes trusted Python code. HTTP/model clients cannot add environments.
    ENVIRONMENTS[WarehouseRelease.id] = WarehouseRelease
    config = RunConfig(environment_id=WarehouseRelease.id, episodes=1)
    with tempfile.TemporaryDirectory() as directory:
        manager = RunManager(Store(Path(directory) / "engine.sqlite3"))
        try:
            run = manager.submit(config, WarehousePolicy())
            result = await manager.wait(run["id"])
            episode = result["episodes"][0]
            assert episode["passed"] and replay(episode)["verified"]
            assert episode["provenance"]["provider_id"] == "custom"
            print(manager.store.get_run(run["id"]))
        finally:
            await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
