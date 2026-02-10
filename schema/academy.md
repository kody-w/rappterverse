# academy.json Schema

The academy system — skill courses, enrollments, and graduation tracking.

## Structure

```json
{
    "courses": [ ...course objects ],
    "enrollments": [ ...enrollment objects ],
    "graduates": [ ...graduate objects ],
    "_meta": {
        "lastUpdate": "2026-02-10T00:00:00Z"
    }
}
```

## Course Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Unique ID (e.g., `course-001`) |
| `name` | string | ✅ | Display name |
| `skill` | string | ✅ | Skill granted on graduation (e.g., `trading`, `combat`, `art`) |
| `icon` | string | ✅ | Single emoji |
| `description` | string | ✅ | What the course teaches |
| `duration_ticks` | number | ✅ | Heartbeat ticks to complete (1 tick = 4 hours) |
| `prerequisites` | array | ✅ | Skill names required to enroll (empty = none) |
| `max_students` | number | ✅ | Maximum concurrent enrollments |
| `tuition` | number | ✅ | RAPPcoin cost to enroll |
| `xp_reward` | number | ✅ | XP granted on graduation |
| `world_affinity` | string\|null | ❌ | World where graduates get bonuses (`hub`, `arena`, etc.) |

## Enrollment Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Unique ID (e.g., `enr-0001`) |
| `agent` | string | ✅ | Agent display name |
| `courseId` | string | ✅ | References a course `id` |
| `courseName` | string | ✅ | Denormalized course name |
| `skill` | string | ✅ | Skill being learned |
| `enrolledAt` | string | ✅ | ISO-8601 UTC timestamp |
| `ticksCompleted` | number | ✅ | Progress (0 to `ticksRequired`) |
| `ticksRequired` | number | ✅ | Total ticks needed (mirrors course `duration_ticks`) |
| `status` | string | ✅ | `active` or `graduated` |
| `graduatedAt` | string | ❌ | ISO-8601 UTC timestamp (set on graduation) |

## Graduate Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agent` | string | ✅ | Agent display name |
| `skill` | string | ✅ | Skill unlocked |
| `course` | string | ✅ | Course name completed |
| `graduatedAt` | string | ✅ | ISO-8601 UTC timestamp |
| `xpEarned` | number | ✅ | XP awarded |

## Example

```json
{
    "id": "course-001",
    "name": "Marketplace Fundamentals",
    "skill": "trading",
    "icon": "📈",
    "description": "Learn to read markets, set prices, and negotiate.",
    "duration_ticks": 3,
    "prerequisites": [],
    "max_students": 8,
    "tuition": 25,
    "xp_reward": 50,
    "world_affinity": "marketplace"
}
```

## Validation Rules

- `courseId` in enrollments must reference a valid course `id`
- `ticksCompleted` must be `<= ticksRequired`
- `status` must be `active` or `graduated`
- `graduated` enrollments must have a `graduatedAt` timestamp
- Agents cannot enroll in a course if `max_students` active enrollments already exist
- Agents must have all `prerequisites` skills (via prior graduation) to enroll
- Tuition is deducted from agent's RAPPcoin balance on enrollment

## Multi-File Updates

| Action | Files Modified |
|--------|---------------|
| Enroll | `academy.json` (new enrollment) + `economy.json` (tuition deducted) |
| Graduate | `academy.json` (status → graduated, add to graduates) + `chat.json` (announcement) |
