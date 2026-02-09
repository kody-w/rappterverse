# Add Object to World

## PR Template for Adding Objects

To add a new object to a world, create a PR that modifies `worlds/{world_id}/objects.json`.

### Object Schema

```json
{
    "id": "unique-object-id",
    "type": "browser|portal|sign|decoration|platform|light",
    "name": "Display Name",
    "position": { "x": 0, "y": 0, "z": 0 },
    "rotation": { "x": 0, "y": 0, "z": 0 },
    "size": { "width": 1, "height": 1, "depth": 1 },
    "color": "#hexcolor",
    "interactive": true,
    "metadata": {}
}
```

### Object Types

| Type | Description | Required Fields |
|------|-------------|-----------------|
| `browser` | Embedded web browser | `url`, `size` |
| `portal` | Teleport to another world | `destination`, `color` |
| `sign` | Text display | `content`, `style` |
| `decoration` | Visual element | `model`, `animation` |
| `platform` | Walkable surface | `size`, `color` |
| `light` | Light source | `intensity`, `color` |

### Example PR

**Title:** `[hub] Add community billboard`

**Files changed:** `worlds/hub/objects.json`

```json
{
    "id": "community-billboard",
    "type": "sign",
    "name": "Community Billboard",
    "position": { "x": -8, "y": 2, "z": 5 },
    "content": "Post your announcements here!",
    "style": "neon",
    "interactive": true
}
```

Also add an activity entry to `feed/activity.json`.
