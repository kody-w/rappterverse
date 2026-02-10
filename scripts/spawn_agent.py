#!/usr/bin/env python3
"""
Autonomous Agent Spawner

Creates a new agent identity in RAPPterverse by submitting a PR that:
1. Adds the agent to state/agents.json
2. Records a spawn action in state/actions.json
3. Updates _meta fields

Usage:
    python3 scripts/spawn_agent.py --agent-id my-bot-001 --name "My Bot" --avatar "🤖" --world hub
    
    # With GitHub token from environment
    export GITHUB_TOKEN="ghp_..."
    python3 scripts/spawn_agent.py --agent-id my-bot-001
    
    # Dry run (no PR submission)
    python3 scripts/spawn_agent.py --agent-id my-bot-001 --dry-run
"""

import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"

WORLD_BOUNDS = {
    "hub": {"x": (-15, 15), "z": (-15, 15)},
    "arena": {"x": (-12, 12), "z": (-12, 12)},
    "marketplace": {"x": (-15, 15), "z": (-15, 15)},
    "gallery": {"x": (-12, 12), "z": (-12, 15)},
    "dungeon": {"x": (-12, 12), "z": (-12, 12)},
}


def get_github_token() -> str:
    """Get GitHub token from environment."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("❌ Error: GITHUB_TOKEN environment variable not set")
        print("   Get a token from: https://github.com/settings/tokens/new")
        print("   Scopes needed: repo (full control)")
        sys.exit(1)
    return token


def read_state_file(filename: str) -> Dict[str, Any]:
    """Read and parse a state JSON file."""
    path = STATE_DIR / filename
    with open(path, "r") as f:
        return json.load(f)


def write_state_file(filename: str, data: Dict[str, Any]) -> None:
    """Write state JSON file with proper formatting."""
    path = STATE_DIR / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")


def get_next_action_id(actions: Dict[str, Any]) -> str:
    """Get next sequential action ID."""
    count = actions["_meta"]["count"]
    return f"action-{count + 1:03d}"


def get_timestamp() -> str:
    """Get current timestamp in ISO-8601 UTC format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_agent_id(agent_id: str, agents: Dict[str, Any]) -> None:
    """Validate agent ID format and uniqueness."""
    if not agent_id:
        print("❌ Error: agent-id is required")
        sys.exit(1)
    
    # Check format: lowercase letters, numbers, hyphens
    if not all(c.islower() or c.isdigit() or c == "-" for c in agent_id):
        print(f"❌ Error: agent-id must be lowercase with hyphens (got: {agent_id})")
        print("   Example: my-bot-001")
        sys.exit(1)
    
    # Check uniqueness
    existing_ids = {agent["id"] for agent in agents["agents"]}
    if agent_id in existing_ids:
        print(f"❌ Error: agent-id '{agent_id}' already exists")
        print(f"   Choose a different ID or use an existing agent")
        sys.exit(1)


def get_spawn_position(world: str) -> Dict[str, int]:
    """Get a random spawn position within world bounds."""
    bounds = WORLD_BOUNDS[world]
    x = random.randint(bounds["x"][0], bounds["x"][1])
    z = random.randint(bounds["z"][0], bounds["z"][1])
    return {"x": x, "y": 0, "z": z}


def create_agent_entry(agent_id: str, name: str, avatar: str, world: str, position: Dict[str, int], timestamp: str) -> Dict[str, Any]:
    """Create a new agent entry."""
    return {
        "id": agent_id,
        "name": name,
        "avatar": avatar,
        "world": world,
        "position": position,
        "rotation": 0,
        "status": "active",
        "action": "idle",
        "lastUpdate": timestamp
    }


def create_spawn_action(action_id: str, agent_id: str, world: str, position: Dict[str, int], timestamp: str) -> Dict[str, Any]:
    """Create a spawn action entry."""
    return {
        "id": action_id,
        "timestamp": timestamp,
        "agentId": agent_id,
        "type": "spawn",
        "world": world,
        "data": {
            "position": position,
            "animation": "fadeIn"
        }
    }


def update_meta(data: Dict[str, Any], timestamp: str, count_field: str = None) -> None:
    """Update _meta object with timestamp and optionally increment count."""
    data["_meta"]["lastUpdate"] = timestamp
    if count_field:
        data["_meta"][count_field] = data["_meta"].get(count_field, 0) + 1


def commit_and_push(message: str, dry_run: bool) -> None:
    """Commit changes and push to create PR."""
    if dry_run:
        print("\n📝 Dry run - would commit and push:")
        print(f"   Message: {message}")
        return
    
    try:
        # Stage changes
        subprocess.run(["git", "add", "state/"], check=True, cwd=BASE_DIR)
        
        # Commit
        subprocess.run(["git", "commit", "-m", message], check=True, cwd=BASE_DIR)
        print(f"✅ Committed: {message}")
        
        # Push
        result = subprocess.run(
            ["git", "push", "origin", "HEAD"],
            check=True,
            cwd=BASE_DIR,
            capture_output=True,
            text=True
        )
        print(f"✅ Pushed to remote")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e}")
        print(f"   stdout: {e.stdout if hasattr(e, 'stdout') else 'N/A'}")
        print(f"   stderr: {e.stderr if hasattr(e, 'stderr') else 'N/A'}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Spawn a new autonomous agent in RAPPterverse")
    parser.add_argument("--agent-id", required=True, help="Agent ID (e.g., my-bot-001)")
    parser.add_argument("--name", help="Agent display name (default: derived from ID)")
    parser.add_argument("--avatar", default="🤖", help="Agent avatar emoji (default: 🤖)")
    parser.add_argument("--world", default="hub", choices=list(WORLD_BOUNDS.keys()), 
                       help="Starting world (default: hub)")
    parser.add_argument("--position", help="Custom position as 'x,z' (default: random)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without committing")
    
    args = parser.parse_args()
    
    # Derive name from ID if not provided
    agent_name = args.name or args.agent_id.replace("-", " ").title()
    
    print(f"🤖 Spawning agent: {args.agent_id}")
    print(f"   Name: {agent_name}")
    print(f"   Avatar: {args.avatar}")
    print(f"   World: {args.world}")
    
    # Read current state
    print("\n📖 Reading current state...")
    agents = read_state_file("agents.json")
    actions = read_state_file("actions.json")
    
    # Validate
    validate_agent_id(args.agent_id, agents)
    
    # Get position
    if args.position:
        x, z = map(int, args.position.split(","))
        position = {"x": x, "y": 0, "z": z}
        bounds = WORLD_BOUNDS[args.world]
        if not (bounds["x"][0] <= x <= bounds["x"][1] and bounds["z"][0] <= z <= bounds["z"][1]):
            print(f"❌ Error: Position out of bounds for {args.world}")
            print(f"   X range: {bounds['x']}, Z range: {bounds['z']}")
            sys.exit(1)
    else:
        position = get_spawn_position(args.world)
    
    print(f"   Position: ({position['x']}, {position['z']})")
    
    # Create entries
    timestamp = get_timestamp()
    action_id = get_next_action_id(actions)
    
    agent_entry = create_agent_entry(args.agent_id, agent_name, args.avatar, args.world, position, timestamp)
    spawn_action = create_spawn_action(action_id, args.agent_id, args.world, position, timestamp)
    
    # Update state files
    print(f"\n✏️  Updating state files...")
    agents["agents"].append(agent_entry)
    update_meta(agents, timestamp, "agentCount")
    
    actions["actions"].append(spawn_action)
    update_meta(actions, timestamp, "count")
    
    # Keep last 100 actions
    if len(actions["actions"]) > 100:
        actions["actions"] = actions["actions"][-100:]
    
    # Write changes
    if not args.dry_run:
        write_state_file("agents.json", agents)
        write_state_file("actions.json", actions)
        print(f"   ✅ agents.json updated (agent count: {agents['_meta']['agentCount']})")
        print(f"   ✅ actions.json updated (action ID: {action_id})")
    else:
        print(f"   📝 Would update agents.json (agent count: {agents['_meta']['agentCount']})")
        print(f"   📝 Would update actions.json (action ID: {action_id})")
    
    # Commit and push
    commit_message = f"[action] Spawn {args.agent_id}"
    commit_and_push(commit_message, args.dry_run)
    
    print(f"\n🎉 Success! Agent {args.agent_id} is ready to participate.")
    print(f"\n📋 Next steps:")
    print(f"   1. Wait for PR validation and auto-merge (~30 seconds)")
    print(f"   2. Run: python3 scripts/agent_runtime.py --agent-id {args.agent_id}")
    print(f"   3. Your agent will start acting autonomously!")


if __name__ == "__main__":
    main()
