# Publication sidecar captured after the original ad-hoc execution.
# Original command: uv run python - <<'PY' ...body below... PY
# Original source: d71a05d35f8c95df930d957ff4ebecc2ef3b0b72.
# This was not a committed collector or a locked experiment at collection time.
# The fixed output path must not exist; this sidecar was not rerun.
import asyncio
import cProfile
import hashlib
import io
import json
import os
import platform
import pstats
import subprocess
import tempfile
import time
from pathlib import Path

from world_engine.environments import ENVIRONMENTS
from world_engine.models import RunConfig, canonical_json, digest, utc_now
from world_engine.rollout import replay, rollout
from world_engine.store import Store

started = time.perf_counter()
out = Path('artifacts/profiling/20261010-v1')
out.mkdir(parents=True, exist_ok=False, mode=0o700)
source_paths = sorted(Path('src/world_engine').glob('*.py')) + [Path('pyproject.toml'), Path('uv.lock')]
source_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}

def dump_profile(name, profile):
    profile.dump_stats(str(out / f'{name}.prof'))
    stream = io.StringIO()
    stats = pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('cumulative')
    stats.print_stats(50)
    with (out / f'{name}.txt').open('x') as handle:
        handle.write(stream.getvalue())
    entries = []
    for (filename, line, function), (primitive, calls, exclusive, cumulative, callers) in pstats.Stats(profile).stats.items():
        entries.append({'file': filename, 'line': line, 'function': function, 'primitive_calls': primitive,
                        'calls': calls, 'exclusive_seconds': exclusive, 'cumulative_seconds': cumulative})
    return {'total_profiled_seconds': stats.total_tt, 'total_calls': stats.total_calls,
            'top_cumulative': sorted(entries, key=lambda row: row['cumulative_seconds'], reverse=True)[:50],
            'top_exclusive': sorted(entries, key=lambda row: row['exclusive_seconds'], reverse=True)[:50]}

async def main():
    worlds = []
    profiled_episodes = {}
    for environment_id in ENVIRONMENTS:
        config = RunConfig(environment_id=environment_id, provider_id='scripted-oracle', episodes=24, seed=0,
                           max_steps=20, timeout_seconds=30, concurrency=1, evaluation_only=True,
                           label='CPU profile: synthetic scripted reference only')
        plain_start = time.perf_counter()
        plain = [await rollout(config, index) for index in range(24)]
        plain_wall = time.perf_counter() - plain_start
        profile = cProfile.Profile()
        measured_start = time.perf_counter()
        profile.enable()
        measured = [await rollout(config, index) for index in range(24)]
        profile.disable()
        wall = time.perf_counter() - measured_start
        profiled_episodes[environment_id] = measured
        assert all(ep['passed'] and ep['status'] == 'completed' and ep['termination'] == 'finished' for ep in plain + measured)
        assert [ep['scenario_id'] for ep in plain] == [ep['scenario_id'] for ep in measured]
        worlds.append({'environment_id': environment_id, 'config': config.model_dump(),
                       'unprofiled': {'episodes': len(plain), 'decisions': sum(ep['steps'] for ep in plain),
                                      'wall_seconds': plain_wall, 'episodes_per_second': len(plain) / plain_wall,
                                      'episode_seconds': [ep['elapsed_seconds'] for ep in plain]},
                       'profiled': {'episodes': len(measured), 'decisions': sum(ep['steps'] for ep in measured),
                                    'wall_seconds': wall, 'episodes_per_second': len(measured) / wall,
                                    'episode_seconds': [ep['elapsed_seconds'] for ep in measured],
                                    **dump_profile(environment_id + '-rollout', profile)},
                       'passed': len(measured), 'invalid_actions': sum(ep['invalid_actions'] for ep in measured),
                       'errors': sum(ep['error'] is not None for ep in measured),
                       'implementation': measured[0]['provenance'],
                       'scenario_ids': [ep['scenario_id'] for ep in measured],
                       'episode_sha256': [digest(ep) for ep in measured]})
        assert time.perf_counter() - started < 240
    phases = []
    profile = cProfile.Profile()
    wall_start = time.perf_counter()
    profile.enable()
    verified = [replay(episode) for episodes in profiled_episodes.values() for episode in episodes]
    profile.disable()
    phases.append({'phase': 'trusted-replay', 'episodes': len(verified), 'verified': sum(row['verified'] for row in verified),
                   'wall_seconds': time.perf_counter() - wall_start, **dump_profile('trusted-replay', profile)})
    with tempfile.TemporaryDirectory(prefix='world-engine-cpu-profile-') as temporary:
        store = Store(Path(temporary) / 'profile.sqlite3')
        for world in worlds:
            store.create_run(world['environment_id'], RunConfig.model_validate(world['config']))
        profile = cProfile.Profile()
        wall_start = time.perf_counter()
        profile.enable()
        for environment_id, episodes in profiled_episodes.items():
            for episode in episodes:
                store.append_episode(environment_id, episode)
        profile.disable()
        phases.append({'phase': 'sqlite-append', 'episodes': 96, 'wall_seconds': time.perf_counter() - wall_start,
                       **dump_profile('sqlite-append', profile)})
        for world in worlds:
            store.update_run(world['environment_id'], 'completed', elapsed=world['unprofiled']['wall_seconds'])
        for phase, count, operation in (
                ('sqlite-list-page', 100, lambda: store.list_runs(limit=100, offset=0)),
                ('sqlite-detail-24', 40, lambda: store.get_run(worlds[0]['environment_id'], detail=True))):
            profile = cProfile.Profile()
            wall_start = time.perf_counter()
            profile.enable()
            results = [operation() for _ in range(count)]
            profile.disable()
            phases.append({'phase': phase, 'operations': count, 'returned_runs_per_operation': 4 if phase == 'sqlite-list-page' else 1,
                           'returned_episodes_per_operation': 24 if phase == 'sqlite-detail-24' else 0,
                           'world': None if phase == 'sqlite-list-page' else worlds[0]['environment_id'],
                           'wall_seconds': time.perf_counter() - wall_start, **dump_profile(phase, profile)})
            del results
    return worlds, phases, profiled_episodes

worlds, phases, episodes = asyncio.run(main())
assert all(hashlib.sha256(path.read_bytes()).hexdigest() == source_hashes[str(path)] for path in source_paths)
revisions = {world['implementation']['git_revision'] for world in worlds}
assert len(revisions) == 1 and next(iter(revisions)).startswith('d71a05d')
machine = {}
for key in ('hw.model', 'hw.memsize', 'machdep.cpu.brand_string'):
    result = subprocess.run(['sysctl', '-n', key], capture_output=True, text=True, timeout=2)
    machine[key] = result.stdout.strip() if result.returncode == 0 else None
receipt = {'schema': 'world-engine.cpu-profile.v1', 'created_at': utc_now(), 'git_revision': next(iter(revisions)),
           'runtime': platform.python_version(), 'platform': platform.platform(), 'machine': platform.machine(),
           'cpu_count': os.cpu_count(), 'machine_metadata': machine, 'source_hashes': source_hashes,
           'source_hashes_unchanged': True, 'worlds': worlds, 'phases': phases,
           'execution_seconds': time.perf_counter() - started,
           'measurement': 'Sequential in-process scripted reference episodes; no model calls. Unprofiled first, cProfile second, same24 seeds perworld; replay/SQLite separately profiled.',
           'limitations': ['cProfile overhead changes timing; cumulative entries are nested and not additive.',
                           'Trial ordering and shared-machine load are uncontrolled, not a comparative speed claim.',
                           'Within-process source/type/schema caches warm during the first trial; first episode includes collection-revision introspection.',
                           'Four24-episode runs and one24-episode CRM detail workload do not establish100-episode or large-history server latency.',
                           'Temporary profiling database was removed on completion; no server or primary database was touched.',
                           'Evaluation-only synthetic operator traces are not training data.']}
with (out / 'episodes.jsonl').open('x') as handle:
    for world_episodes in episodes.values():
        for episode in world_episodes:
            handle.write(canonical_json({'evaluation_only': True, 'training_eligible': False, 'episode': episode}) + '\n')
with (out / 'profile.json').open('x') as handle:
    handle.write(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'output': str(out.resolve()), 'git_revision': receipt['git_revision'], 'execution_seconds': receipt['execution_seconds'],
                  'worlds': [{key: world[key] for key in ('environment_id', 'unprofiled', 'passed', 'invalid_actions', 'errors')} for world in worlds],
                  'phases': [{key: phase[key] for key in ('phase', 'wall_seconds')} for phase in phases],
                  'artifact_bytes': sum(path.stat().st_size for path in out.iterdir())}))
