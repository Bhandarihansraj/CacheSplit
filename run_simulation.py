"""
run_simulation.py
CacheSplit v4 — Stampede Recovery CLI Demo
Run: python run_simulation.py
No server required.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.simulation_engine import run_full_scenario


COLOURS = {
    "CONVERGED": "\033[92m",
    "SEED": "\033[94m",
    "INVALIDATION": "\033[93m",
    "INCONSISTENT_READ": "\033[91m",
    "OVERLAP": "\033[95m",
    "RECOVERY_CYCLE": "\033[96m",
    "REPAIRED": "\033[92m",
    "INVALIDATION_DROPPED": "\033[91m",
    "ORIGIN_OVERLOAD": "\033[91m",
    "QUEUED_REPAIR": "\033[93m",
}
RESET = "\033[0m"


def colour(evt_type: str, text: str) -> str:
    c = COLOURS.get(evt_type, "")
    return f"{c}{text}{RESET}" if c else text


async def main():
    print("=" * 60)
    print("  CacheSplit v4 — Partial Cache Invalidation Recovery Demo")
    print("=" * 60)

    config = {
        "node_count": 4,
        "key_count": 5,
        "drop_prob": 0.4,
        "max_rps": 6,
        "burst": 3,
        "max_cycles": 12,
    }

    print(f"\nConfig:")
    for k, v in config.items():
        print(f"  {k:12s} = {v}")
    print()

    result = await run_full_scenario(config)

    print("\n--- Event Log ---")
    for evt in result["event_log"]:
        evt_type = evt.get("type", "INFO")
        detail = evt.get("detail", str(evt))
        print("  " + colour(evt_type, f"[{evt_type:22s}] {detail}"))

    print("\n--- Final Node Versions ---")
    for node_id, snap in result["node_snapshots"].items():
        entries = snap.get("entries", {})
        states = {k: f"v{e['version']}({e['state'][0]})" for k, e in entries.items()}
        print(f"  {node_id}: {states}")

    print("\n--- Origin Versions ---")
    for key, ver in result["origin_version"].items():
        print(f"  {key}: v{ver}")

    print("\n--- Summary ---")
    print(f"  Converged    : {colour('CONVERGED' if result['converged'] else 'INCONSISTENT_READ', str(result['converged']))}")
    print(f"  Cycles taken : {result['cycles_taken']}")
    print(f"  Origin hits  : {result['origin_hits']}")
    print(f"  Origin reject: {result['origin_rejects']}")
    print(f"  Dedup savings: {result['dedup_savings']} extra origin requests avoided")
    print()


if __name__ == "__main__":
    asyncio.run(main())
