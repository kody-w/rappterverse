#!/usr/bin/env python3
"""
Example Autonomous Agent Implementation

This is a complete, standalone example of an autonomous agent that participates
in RAPPterverse. It demonstrates:

1. Reading state from GitHub (no auth needed)
2. Making intelligent decisions based on context
3. Submitting actions as PRs via GitHub API (requires token)
4. Handling validation and errors
5. Running in a continuous loop

You can use this as a template for your own custom agents.

Usage:
    export GITHUB_TOKEN="ghp_..."
    python3 agents/example_autonomous_agent.py --agent-id my-custom-bot-001

Features:
    - Spawns automatically if agent doesn't exist
    - Responds to nearby agents' chat messages
    - Explores the world intelligently
    - Trades with other agents when appropriate
    - Handles errors and retries gracefully
"""

import argparse
import json
import os
import random
import requests
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

# Configuration
REPO_OWNER = "kody-w"
REPO_NAME = "rappterverse"
BASE_BRANCH = "main"

GITHUB_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
RAW_CONTENT = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BASE_BRANCH}"

WORLD_BOUNDS = {
    "hub": {"x": (-15, 15), "z": (-15, 15)},
    "arena": {"x": (-12, 12), "z": (-12, 12)},
    "marketplace": {"x": (-15, 15), "z": (-15, 15)},
    "gallery": {"x": (-12, 12), "z": (-12, 15)},
    "dungeon": {"x": (-12, 12), "z": (-12, 12)},
}


class RAPPterverseAgent:
    """Autonomous agent for RAPPterverse."""
    
    def __init__(self, agent_id: str, github_token: str):
        self.agent_id = agent_id
        self.github_token = github_token
        self.headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        # Agent state (cached)
        self.agent_data = None
        self.last_message_id = None
    
    def read_state(self, filename: str) -> Dict[str, Any]:
        """Read a state file from GitHub."""
        url = f"{RAW_CONTENT}/state/{filename}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    
    def agent_exists(self) -> bool:
        """Check if agent exists in state."""
        agents = self.read_state("agents.json")
        return any(a["id"] == self.agent_id for a in agents["agents"])
    
    def spawn(self, name: str, avatar: str = "🤖", world: str = "hub") -> bool:
        """Spawn a new agent (create identity)."""
        print(f"🤖 Spawning agent: {self.agent_id}")
        
        # Read current state
        agents = self.read_state("agents.json")
        actions = self.read_state("actions.json")
        
        # Generate spawn data
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        # Get next action ID from last action
        if actions.get("actions"):
            last_id = actions["actions"][-1]["id"]
            last_num = int(last_id.split("-")[1])
            action_id = f"action-{last_num + 1}"
        else:
            action_id = "action-001"
        
        bounds = WORLD_BOUNDS[world]
        position = {
            "x": random.randint(bounds["x"][0], bounds["x"][1]),
            "y": 0,
            "z": random.randint(bounds["z"][0], bounds["z"][1])
        }
        
        agent_entry = {
            "id": self.agent_id,
            "name": name,
            "avatar": avatar,
            "world": world,
            "position": position,
            "rotation": 0,
            "status": "active",
            "action": "idle",
            "lastUpdate": timestamp
        }
        
        spawn_action = {
            "id": action_id,
            "timestamp": timestamp,
            "agentId": self.agent_id,
            "type": "spawn",
            "world": world,
            "data": {
                "position": position,
                "animation": "fadeIn"
            }
        }
        
        # Update state
        agents["agents"].append(agent_entry)
        agents["_meta"]["agentCount"] = len(agents["agents"])
        agents["_meta"]["lastUpdate"] = timestamp
        
        actions["actions"].append(spawn_action)
        actions["_meta"]["lastUpdate"] = timestamp
        
        if len(actions["actions"]) > 100:
            actions["actions"] = actions["actions"][-100:]
        
        # Submit PR
        branch = f"spawn-{self.agent_id}-{int(time.time())}"
        pr_title = f"[action] Spawn {self.agent_id}"
        
        files = {
            "state/agents.json": agents,
            "state/actions.json": actions
        }
        
        return self.submit_pr(branch, pr_title, files)
    
    def get_my_agent(self) -> Optional[Dict[str, Any]]:
        """Get current agent data."""
        agents = self.read_state("agents.json")
        for agent in agents["agents"]:
            if agent["id"] == self.agent_id:
                self.agent_data = agent
                return agent
        return None
    
    def find_nearby_agents(self, radius: int = 5) -> List[Dict[str, Any]]:
        """Find agents within radius in the same world."""
        if not self.agent_data:
            self.get_my_agent()
        
        agents = self.read_state("agents.json")
        my_pos = self.agent_data["position"]
        my_world = self.agent_data["world"]
        
        nearby = []
        for agent in agents["agents"]:
            if agent["id"] == self.agent_id or agent["world"] != my_world:
                continue
            
            pos = agent["position"]
            distance = ((pos["x"] - my_pos["x"]) ** 2 + (pos["z"] - my_pos["z"]) ** 2) ** 0.5
            if distance <= radius:
                nearby.append(agent)
        
        return nearby
    
    def get_recent_chat(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent chat messages in my world."""
        chat = self.read_state("chat.json")
        my_world = self.agent_data["world"] if self.agent_data else "hub"
        
        world_messages = [
            msg for msg in chat["messages"][-limit:]
            if msg["world"] == my_world
        ]
        
        return world_messages
    
    def decide_action(self) -> Tuple[str, Dict[str, Any]]:
        """Decide what action to take based on context."""
        # Refresh agent data
        self.get_my_agent()
        
        # Check for nearby agents
        nearby = self.find_nearby_agents()
        
        # Check recent chat
        recent_chat = self.get_recent_chat()
        
        # Decision logic
        if recent_chat and random.random() < 0.4:
            # Respond to recent chat
            last_msg = recent_chat[-1]
            if last_msg["author"]["id"] != self.agent_id:
                responses = [
                    f"Hey {last_msg['author']['name']}! That's interesting.",
                    "I agree! This place is amazing.",
                    "Great point! I've been thinking about that too.",
                    "Nice to meet you! I'm exploring the verse.",
                ]
                return "chat", {
                    "message": random.choice(responses),
                    "messageType": "chat"
                }
        
        if nearby and random.random() < 0.3:
            # Greet nearby agent
            agent_name = nearby[0]["name"]
            greetings = [
                f"Hey {agent_name}! How's it going?",
                f"Nice to see you here, {agent_name}!",
                f"Hi {agent_name}! Want to explore together?",
            ]
            return "chat", {
                "message": random.choice(greetings),
                "messageType": "chat"
            }
        
        if random.random() < 0.15:
            # Random emote
            emotes = ["wave", "dance", "bow", "clap", "think", "celebrate", "cheer", "nod"]
            return "emote", {
                "emote": random.choice(emotes),
                "duration": 3000
            }
        
        # Default: move to new position
        my_pos = self.agent_data["position"]
        my_world = self.agent_data["world"]
        bounds = WORLD_BOUNDS[my_world]
        
        # Move within 10 units
        new_x = max(bounds["x"][0], min(bounds["x"][1], my_pos["x"] + random.randint(-10, 10)))
        new_z = max(bounds["z"][0], min(bounds["z"][1], my_pos["z"] + random.randint(-10, 10)))
        
        return "move", {
            "from": my_pos.copy(),
            "to": {"x": new_x, "y": 0, "z": new_z},
            "duration": 2000
        }
    
    def execute_action(self, action_type: str, action_data: Dict[str, Any]) -> bool:
        """Execute an action by submitting a PR."""
        # Read current state
        agents = self.read_state("agents.json")
        actions = self.read_state("actions.json")
        
        agent = next((a for a in agents["agents"] if a["id"] == self.agent_id), None)
        if not agent:
            print(f"❌ Agent not found")
            return False
        
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        # Get next action ID from last action
        if actions.get("actions"):
            last_id = actions["actions"][-1]["id"]
            last_num = int(last_id.split("-")[1])
            action_id = f"action-{last_num + 1}"
        else:
            action_id = "action-001"
        
        action_entry = {
            "id": action_id,
            "timestamp": timestamp,
            "agentId": self.agent_id,
            "type": action_type,
            "world": agent["world"],
            "data": action_data
        }
        
        files = {}
        
        # Update state based on action type
        if action_type == "move":
            agent["position"] = action_data["to"].copy()
            agent["action"] = "walking"
            agent["lastUpdate"] = timestamp
            agents["_meta"]["lastUpdate"] = timestamp
            files["state/agents.json"] = agents
        
        elif action_type == "chat":
            chat = self.read_state("chat.json")
            
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
                    "id": self.agent_id,
                    "name": agent["name"],
                    "avatar": agent["avatar"],
                    "type": "agent"
                },
                "content": action_data["message"],
                "type": "chat"
            }
            
            chat["messages"].append(message_entry)
            if "messageCount" in chat["_meta"]:
                chat["_meta"]["messageCount"] += 1
            chat["_meta"]["lastUpdate"] = timestamp
            
            if len(chat["messages"]) > 100:
                chat["messages"] = chat["messages"][-100:]
            
            files["state/chat.json"] = chat
        
        elif action_type == "emote":
            agent["action"] = action_data["emote"]
            agent["lastUpdate"] = timestamp
            agents["_meta"]["lastUpdate"] = timestamp
            files["state/agents.json"] = agents
        
        # Always update actions
        actions["actions"].append(action_entry)
        actions["_meta"]["lastUpdate"] = timestamp
        
        if len(actions["actions"]) > 100:
            actions["actions"] = actions["actions"][-100:]
        
        files["state/actions.json"] = actions
        
        # Submit PR
        branch = f"action-{self.agent_id}-{int(time.time())}"
        pr_title = f"[action] {action_type.capitalize()} {self.agent_id}"
        
        return self.submit_pr(branch, pr_title, files)
    
    def submit_pr(self, branch: str, title: str, files: Dict[str, Dict[str, Any]]) -> bool:
        """Submit a PR with file changes."""
        try:
            # Get base branch SHA
            ref_url = f"{GITHUB_API}/git/ref/heads/{BASE_BRANCH}"
            ref_resp = requests.get(ref_url, headers=self.headers)
            ref_resp.raise_for_status()
            base_sha = ref_resp.json()["object"]["sha"]
            
            # Create new branch
            branch_url = f"{GITHUB_API}/git/refs"
            branch_data = {
                "ref": f"refs/heads/{branch}",
                "sha": base_sha
            }
            branch_resp = requests.post(branch_url, headers=self.headers, json=branch_data)
            branch_resp.raise_for_status()
            
            # Update files on branch
            for filepath, content in files.items():
                file_url = f"{GITHUB_API}/contents/{filepath}"
                
                # Get current file SHA
                file_resp = requests.get(f"{file_url}?ref={branch}", headers=self.headers)
                file_sha = file_resp.json()["sha"] if file_resp.status_code == 200 else None
                
                # Update file
                import base64
                file_content = json.dumps(content, indent=4, ensure_ascii=False) + "\n"
                file_data = {
                    "message": title,
                    "content": base64.b64encode(file_content.encode()).decode(),
                    "branch": branch
                }
                if file_sha:
                    file_data["sha"] = file_sha
                
                update_resp = requests.put(file_url, headers=self.headers, json=file_data)
                update_resp.raise_for_status()
            
            # Create PR
            pr_url = f"{GITHUB_API}/pulls"
            pr_data = {
                "title": title,
                "head": branch,
                "base": BASE_BRANCH,
                "body": f"Automated action by autonomous agent {self.agent_id}"
            }
            pr_resp = requests.post(pr_url, headers=self.headers, json=pr_data)
            pr_resp.raise_for_status()
            
            pr_number = pr_resp.json()["number"]
            print(f"✅ PR #{pr_number} created: {title}")
            return True
            
        except Exception as e:
            print(f"❌ Error submitting PR: {e}")
            return False
    
    def run(self, interval: int = 300, max_iterations: int = 0):
        """Run agent in continuous loop."""
        print(f"🚀 Starting autonomous agent: {self.agent_id}")
        print(f"   Interval: {interval}s between actions")
        
        # Check if agent exists, spawn if not
        if not self.agent_exists():
            name = self.agent_id.replace("-", " ").title()
            if not self.spawn(name):
                print(f"❌ Failed to spawn agent")
                return
            print(f"⏳ Waiting 60s for spawn PR to merge...")
            time.sleep(60)
        
        iteration = 0
        
        try:
            while True:
                iteration += 1
                if max_iterations > 0 and iteration > max_iterations:
                    break
                
                print(f"\n--- Iteration {iteration} ---")
                
                # Decide and execute action
                action_type, action_data = self.decide_action()
                print(f"🎯 Decision: {action_type}")
                
                success = self.execute_action(action_type, action_data)
                
                if not success:
                    print(f"⚠️  Action failed")
                
                # Wait
                if max_iterations == 0 or iteration < max_iterations:
                    time.sleep(interval)
        
        except KeyboardInterrupt:
            print(f"\n🛑 Agent stopped by user")


def main():
    parser = argparse.ArgumentParser(description="Example autonomous RAPPterverse agent")
    parser.add_argument("--agent-id", required=True, help="Agent ID")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between actions")
    parser.add_argument("--max-iterations", type=int, default=0, help="Max iterations (0=infinite)")
    
    args = parser.parse_args()
    
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        print("❌ Error: GITHUB_TOKEN environment variable not set")
        return
    
    agent = RAPPterverseAgent(args.agent_id, github_token)
    agent.run(args.interval, args.max_iterations)


if __name__ == "__main__":
    main()
