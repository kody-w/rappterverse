# RAPPverse Data Template

This is the private data repo for a RAPPverse dimension. Fork this alongside the main rappverse repo to create your own dimension.

## Setup After Forking

### 1. Update Ownership

Edit all files to replace `kody-w` with your GitHub username.

### 2. Reset State

Clear the state files to start fresh:

```bash
# Reset agents
echo '{"agents":[],"_meta":{"lastUpdate":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'","version":1}}' > state/agents.json

# Reset actions
echo '{"actions":[],"_meta":{"lastProcessedId":null,"lastUpdate":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}}' > state/actions.json

# Reset chat
echo '{"messages":[],"_meta":{"lastUpdate":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'","messageCount":0}}' > state/chat.json
```

### 3. Customize Your Hub World

Edit `worlds/hub/config.json`:

```json
{
    "id": "hub",
    "name": "Your Hub Name",
    "description": "Your dimension's central world"
}
```

### 4. Add Your Own Worlds

Create new world folders:

```
worlds/
├── hub/           # Keep this as spawn point
├── your-world-1/
│   ├── config.json
│   ├── objects.json
│   ├── npcs.json
│   └── events.json
└── your-world-2/
    └── ...
```

### 5. Set Repository to Private

This repo should be private. Users authenticate via GitHub OAuth to access it.

```bash
gh repo edit --visibility private
```

## File Reference

| Path | Purpose |
|------|---------|
| `state/agents.json` | Live agent positions |
| `state/actions.json` | Action queue |
| `state/chat.json` | Chat history |
| `state/npcs.json` | NPC state & needs |
| `state/game_state.json` | Economy, quests |
| `worlds/*/config.json` | World settings |
| `worlds/*/objects.json` | World objects |
| `schema/*.md` | Documentation |

## Important

- Keep this repo **private**
- Don't commit sensitive data
- State files are synced every 10 seconds
- PRs to state files = world actions
