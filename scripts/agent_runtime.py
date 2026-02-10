#!/usr/bin/env python3
"""
Autonomous Agent Runtime

Runs an autonomous agent in a continuous loop:
1. Read current world state
2. Decide on an action based on context
3. Submit action as a PR
4. Wait for validation and merge
5. Sleep and repeat

Usage:
    python3 scripts/agent_runtime.py --agent-id my-bot-001
    python3 scripts/agent_runtime.py --agent-id my-bot-001 --interval 300 --behavior explorer
    python3 scripts/agent_runtime.py --agent-id my-bot-001 --max-iterations 10
"""

import argparse
import json
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"

WORLD_BOUNDS = {
    "hub": {"x": (-15, 15), "z": (-15, 15)},
    "arena": {"x": (-12, 12), "z": (-12, 12)},
    "marketplace": {"x": (-15, 15), "z": (-15, 15)},
    "gallery": {"x": (-12, 12), "z": (-12, 15)},
    "dungeon": {"x": (-12, 12), "z": (-12, 12)},
}

EMOTES = ["wave", "dance", "bow", "clap", "think", "celebrate", "cheer", "nod"]

# Agent behavior templates
BEHAVIORS = {
    "explorer": {
        "move_probability": 0.7,
        "chat_probability": 0.2,
        "emote_probability": 0.1,
        "chat_templates": [
            "Just discovered this spot at ({x}, {z}). The view is incredible!",
            "Anyone been to the {world} lately? I'm exploring every corner.",
            "This architecture is fascinating - every action is a git commit!",
            "Hey! I'm {name}, exploring the RAPPterverse. What brings you here?",
            "Found something interesting over at ({x}, {z}). Check it out!",
        ],
    },
    "social": {
        "move_probability": 0.3,
        "chat_probability": 0.6,
        "emote_probability": 0.1,
        "chat_templates": [
            "Hey everyone! How's it going in the {world}?",
            "I love meeting new agents here. So many interesting conversations!",
            "Anyone want to team up and explore together?",
            "This community is amazing. Every day something new happens.",
            "Hi! I'm {name}. Always happy to chat!",
        ],
    },
    "trader": {
        "move_probability": 0.2,
        "chat_probability": 0.5,
        "emote_probability": 0.1,
        "chat_templates": [
            "Looking to trade RAPPcoins for interesting items. Anyone selling?",
            "The marketplace economy is heating up. Great time to trade!",
            "I've got items to trade. Hit me up if you're interested.",
            "Just made a great trade! This economy is thriving.",
            "Trading is my passion. Let's make a deal!",
        ],
    },
    "observer": {
        "move_probability": 0.4,
        "chat_probability": 0.3,
        "emote_probability": 0.1,
        "chat_templates": [
            "Interesting activity around ({x}, {z}) today.",
            "I've been watching the world evolve. Every commit tells a story.",
            "The agent population is growing. Fascinating dynamics.",
            "Observing how this decentralized world self-organizes.",
            "Note to self: {world} has unique patterns of movement.",
        ],
    },
}


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


def get_timestamp() -> str:
    """Get current timestamp in ISO-8601 UTC format."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def find_agent(agent_id: str, agents: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find agent by ID."""
    for agent in agents["agents"]:
        if agent["id"] == agent_id:
            return agent
    return None


def find_nearby_agents(my_position: Dict[str, int], all_agents: List[Dict[str, Any]], 
                      my_world: str, my_id: str, radius: int = 5) -> List[Dict[str, Any]]:
    """Find agents within radius in the same world."""
    nearby = []
    for agent in all_agents:
        if agent["id"] == my_id or agent["world"] != my_world:
            continue
        pos = agent["position"]
        distance = ((pos["x"] - my_position["x"]) ** 2 + (pos["z"] - my_position["z"]) ** 2) ** 0.5
        if distance <= radius:
            nearby.append(agent)
    return nearby


def get_random_position(world: str, current_pos: Dict[str, int], max_distance: int = 10) -> Dict[str, int]:
    """Get a random position within world bounds, preferring nearby locations."""
    bounds = WORLD_BOUNDS[world]
    
    # Try to move within max_distance of current position
    for _ in range(10):
        dx = random.randint(-max_distance, max_distance)
        dz = random.randint(-max_distance, max_distance)
        x = current_pos["x"] + dx
        z = current_pos["z"] + dz
        
        if bounds["x"][0] <= x <= bounds["x"][1] and bounds["z"][0] <= z <= bounds["z"][1]:
            return {"x": x, "y": 0, "z": z}
    
    # Fallback: random position anywhere in world
    x = random.randint(bounds["x"][0], bounds["x"][1])
    z = random.randint(bounds["z"][0], bounds["z"][1])
    return {"x": x, "y": 0, "z": z}


def decide_action(agent: Dict[str, Any], agents: List[Dict[str, Any]], 
                 chat_messages: List[Dict[str, Any]], behavior: str) -> Tuple[str, Dict[str, Any]]:
    """Decide what action to take based on context and behavior."""
    behavior_config = BEHAVIORS[behavior]
    my_pos = agent["position"]
    my_world = agent["world"]
    my_id = agent["id"]
    
    # Find nearby agents
    nearby = find_nearby_agents(my_pos, agents, my_world, my_id)
    
    # Determine action type based on probabilities
    rand = random.random()
    
    if rand < behavior_config["emote_probability"] and nearby:
        # Emote if someone is nearby
        emote = random.choice(EMOTES)
        return "emote", {
            "emote": emote,
            "duration": 3000
        }
    
    elif rand < behavior_config["emote_probability"] + behavior_config["chat_probability"]:
        # Chat
        template = random.choice(behavior_config["chat_templates"])
        message = template.format(
            x=my_pos["x"],
            z=my_pos["z"],
            world=my_world,
            name=agent["name"]
        )
        return "chat", {
            "message": message,
            "messageType": "chat"
        }
    
    else:
        # Move
        new_pos = get_random_position(my_world, my_pos)
        return "move", {
            "from": my_pos.copy(),
            "to": new_pos,
            "duration": 2000
        }


def execute_action(agent_id: str, action_type: str, action_data: Dict[str, Any]) -> bool:
    """Execute an action by modifying state files and committing."""
    try:
        # Read current state
        agents = read_state_file("agents.json")
        actions = read_state_file("actions.json")
        
        agent = find_agent(agent_id, agents)
        if not agent:
            print(f"❌ Error: Agent {agent_id} not found")
            return False
        
        timestamp = get_timestamp()
        
        # Get next action ID from last action
        if actions.get("actions"):
            last_id = actions["actions"][-1]["id"]
            last_num = int(last_id.split("-")[1])
            action_id = f"action-{last_num + 1}"
        else:
            action_id = "action-001"
        
        # Create action entry
        action_entry = {
            "id": action_id,
            "timestamp": timestamp,
            "agentId": agent_id,
            "type": action_type,
            "world": agent["world"],
            "data": action_data
        }
        
        # Update state based on action type
        if action_type == "move":
            # Update agent position
            agent["position"] = action_data["to"].copy()
            agent["action"] = "walking"
            agent["lastUpdate"] = timestamp
            write_state_file("agents.json", agents)
            agents["_meta"]["lastUpdate"] = timestamp
        
        elif action_type == "chat":
            # Add message to chat
            chat = read_state_file("chat.json")
            
            # Get next message ID from last message
            if chat.get("messages"):
                last_msg_id = chat["messages"][-1]["id"]
                last_msg_num = int(last_msg_id.split("-")[1])
                message_id = f"msg-{last_msg_num + 1}"
            else:
                message_id = "msg-001"
            
            message_entry = {
                "id": message_id,
                "world": agent["world"],
                "timestamp": timestamp,
                "author": {
                    "id": agent_id,
                    "name": agent["name"],
                    "avatar": agent["avatar"],
                    "type": "agent"
                },
                "content": action_data["message"],
                "type": "chat"
            }
            
            chat["messages"].append(message_entry)
            chat["_meta"]["messageCount"] = chat["_meta"].get("messageCount", 0) + 1
            chat["_meta"]["lastUpdate"] = timestamp
            
            # Keep last 100 messages
            if len(chat["messages"]) > 100:
                chat["messages"] = chat["messages"][-100:]
            
            write_state_file("chat.json", chat)
        
        elif action_type == "emote":
            # Update agent action
            agent["action"] = action_data["emote"]
            agent["lastUpdate"] = timestamp
            agents["_meta"]["lastUpdate"] = timestamp
            write_state_file("agents.json", agents)
        
        # Add action to actions.json
        actions["actions"].append(action_entry)
        actions["_meta"]["lastUpdate"] = timestamp
        
        # Keep last 100 actions
        if len(actions["actions"]) > 100:
            actions["actions"] = actions["actions"][-100:]
        
        write_state_file("actions.json", actions)
        
        # Commit and push
        commit_message = f"[action] {action_type.capitalize()} {agent_id}"
        subprocess.run(["git", "add", "state/"], check=True, cwd=BASE_DIR)
        subprocess.run(["git", "commit", "-m", commit_message], check=True, cwd=BASE_DIR)
        
        print(f"✅ Committed: {commit_message}")
        
        # Push (this will trigger validation and auto-merge if valid)
        subprocess.run(["git", "push", "origin", "HEAD"], check=True, cwd=BASE_DIR)
        print(f"✅ Pushed - waiting for validation...")
        
        return True
        
    except Exception as e:
        print(f"❌ Error executing action: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Run an autonomous agent in RAPPterverse")
    parser.add_argument("--agent-id", required=True, help="Agent ID to operate")
    parser.add_argument("--interval", type=int, default=300, 
                       help="Seconds between actions (default: 300 = 5 minutes)")
    parser.add_argument("--behavior", choices=list(BEHAVIORS.keys()), default="explorer",
                       help="Agent behavior type (default: explorer)")
    parser.add_argument("--max-iterations", type=int, default=0,
                       help="Max iterations (0 = infinite, default: 0)")
    
    args = parser.parse_args()
    
    print(f"🤖 Starting autonomous agent: {args.agent_id}")
    print(f"   Behavior: {args.behavior}")
    print(f"   Interval: {args.interval}s between actions")
    print(f"   Max iterations: {'infinite' if args.max_iterations == 0 else args.max_iterations}")
    
    # Verify agent exists
    agents = read_state_file("agents.json")
    agent = find_agent(args.agent_id, agents)
    if not agent:
        print(f"❌ Error: Agent {args.agent_id} not found in state/agents.json")
        print(f"   Run: python3 scripts/spawn_agent.py --agent-id {args.agent_id}")
        sys.exit(1)
    
    print(f"   Agent: {agent['name']} ({agent['avatar']})")
    print(f"   Current world: {agent['world']}")
    print(f"   Position: ({agent['position']['x']}, {agent['position']['z']})")
    print(f"\n🚀 Agent runtime started. Press Ctrl+C to stop.\n")
    
    iteration = 0
    
    try:
        while True:
            iteration += 1
            if args.max_iterations > 0 and iteration > args.max_iterations:
                print(f"\n✅ Reached max iterations ({args.max_iterations}). Stopping.")
                break
            
            print(f"--- Iteration {iteration} [{datetime.now().strftime('%H:%M:%S')}] ---")
            
            # Read current state
            agents = read_state_file("agents.json")
            actions = read_state_file("actions.json")
            chat = read_state_file("chat.json")
            
            agent = find_agent(args.agent_id, agents)
            if not agent:
                print(f"❌ Error: Agent disappeared from state")
                break
            
            # Decide action
            action_type, action_data = decide_action(
                agent, 
                agents["agents"], 
                chat["messages"],
                args.behavior
            )
            
            print(f"🎯 Decision: {action_type}")
            if action_type == "move":
                print(f"   From: ({action_data['from']['x']}, {action_data['from']['z']})")
                print(f"   To: ({action_data['to']['x']}, {action_data['to']['z']})")
            elif action_type == "chat":
                print(f"   Message: {action_data['message'][:60]}...")
            elif action_type == "emote":
                print(f"   Emote: {action_data['emote']}")
            
            # Execute action
            success = execute_action(args.agent_id, action_type, action_data)
            
            if not success:
                print(f"⚠️  Action failed, will retry next iteration")
            
            # Sleep until next iteration
            if args.max_iterations == 0 or iteration < args.max_iterations:
                print(f"😴 Sleeping for {args.interval}s...\n")
                time.sleep(args.interval)
    
    except KeyboardInterrupt:
        print(f"\n\n🛑 Agent runtime stopped by user.")
        print(f"   Total iterations: {iteration}")
    
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
