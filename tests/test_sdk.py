import importlib.util
import sys

import pytest

from world_engine import ENVIRONMENTS, RunConfig
from world_engine.models import Action
from world_engine.providers import Decision
from world_engine.rollout import replay, rollout


async def test_custom_world_module_changes_invalidate_replay(tmp_path):
    path = tmp_path / "custom_world.py"
    source = '''from world_engine.environments import Environment, COMMON_TOOLS
from world_engine.models import grade

def trusted_helper():
    return "original"

class CustomWorld(Environment):
    id = "custom-world"
    tools = COMMON_TOOLS
    def build(self):
        return {"role":"example", "value":trusted_helper(), "audit":[]}, "Finish"
    def evaluate(self):
        return grade([("correct", self.state["value"] == trusted_helper(), "Correct value")])
'''
    path.write_text(source)
    spec = importlib.util.spec_from_file_location("test_custom_world_module", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    ENVIRONMENTS[module.CustomWorld.id] = module.CustomWorld

    class CustomPolicy:
        async def decide(self, observation, history):
            return Decision(Action(tool="finish"))

    try:
        episode = await rollout(RunConfig(environment_id="custom-world"), 0, CustomPolicy())
        assert episode["passed"] and replay(episode)["verified"]
        assert episode["provenance"]["provider_id"] == "custom"
        path.write_text(source.replace('return "original"', 'return "revised"'))
        with pytest.raises(ValueError, match="fingerprint"):
            replay(episode)
    finally:
        ENVIRONMENTS.pop("custom-world")
        sys.modules.pop(spec.name)
