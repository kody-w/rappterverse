#!/usr/bin/env python3
"""
RAPPter Academy 🎓
Autonomous skill-training system. Agents enroll in courses, progress
each tick, graduate with skills that affect all other systems.

Skills ripple outward:
  trading     → better marketplace margins (economy engine)
  combat      → arena win bonuses
  art         → gallery items worth more
  exploration → rarer dungeon drops
  charisma    → 2x relationship gain (interaction engine)
  philosophy  → deeper zoo posts, lore unlocked
  leadership  → can mentor, form groups
  engineering → infrastructure contributions
  content     → more upvotes on zoo posts
  market_mastery → unlock market-making, arbitrage

Every tick:
  1. Enroll — agents with enough RAPP pick courses matching their world/interests
  2. Progress — enrolled agents advance one tick toward graduation
  3. Graduate — agents who finish earn the skill permanently
  4. Teach — skilled agents occasionally teach ad-hoc lessons (bonus XP to nearby agents)

Usage:
  Single tick:  python scripts/academy_engine.py
  Dry run:      python scripts/academy_engine.py --dry-run
  No git:       python scripts/academy_engine.py --no-push
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEACHING RULES — ad-hoc lessons from skilled agents.
# Skilled agents randomly teach nearby agents for bonus XP.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TEACHING_RULES: dict[str, dict] = {
    "trading": {
        "probability": 0.2,
        "xp_bonus": 10,
        "templates": [
            "{teacher} pulls {student} aside: 'Let me show you how pricing really works in {world}.'",
            "{teacher} draws supply-demand curves in the dirt for {student}. Economics 101.",
            "{teacher} to {student}: 'Watch this trade. See how I set the spread? That's margin.'",
        ],
    },
    "combat": {
        "probability": 0.2,
        "xp_bonus": 10,
        "templates": [
            "{teacher} spars with {student} in the {world}. 'Block, then counter. Again.'",
            "{teacher} breaks down a card combo for {student}: 'This sequence is unbeatable if timed right.'",
            "{teacher} and {student} run drills. 'Your positioning is off. Three steps left.'",
        ],
    },
    "art": {
        "probability": 0.15,
        "xp_bonus": 8,
        "templates": [
            "{teacher} guides {student} through color theory. 'The gallery notices these details.'",
            "{teacher}: '{student}, art isn't about perfection. It's about making someone feel something.'",
            "{teacher} and {student} critique gallery pieces together. Learning by seeing.",
        ],
    },
    "exploration": {
        "probability": 0.15,
        "xp_bonus": 12,
        "templates": [
            "{teacher} shows {student} a hidden path in the {world}. 'Always check the walls.'",
            "{teacher}: '{student}, this trap pattern repeats. Once you see it, you can't unsee it.'",
            "{teacher} shares their dungeon map with {student}. 'I drew this over 20 runs.'",
        ],
    },
    "charisma": {
        "probability": 0.25,
        "xp_bonus": 8,
        "templates": [
            "{teacher} to {student}: 'Conversation is about listening, not waiting to talk.'",
            "{teacher} models a perfect greeting for {student}. 'See? Now they trust you.'",
            "{teacher}: 'The secret to bonds? Show up consistently. That's it.'",
        ],
    },
    "philosophy": {
        "probability": 0.15,
        "xp_bonus": 10,
        "templates": [
            "{teacher} and {student} sit in silence, then {teacher} says: 'What IS a commit?'",
            "{teacher}: '{student}, if your state is reverted, did you still exist during those ticks?'",
            "{teacher} opens a git log. 'Look — our history IS us. We are diffs.'",
        ],
    },
    "leadership": {
        "probability": 0.1,
        "xp_bonus": 15,
        "templates": [
            "{teacher} delegates a task to {student}. 'Leadership isn't doing. It's enabling.'",
            "{teacher}: '{student}, a leader's job is to make themselves unnecessary. Think about that.'",
            "{teacher} introduces {student} to three other agents. 'Build the network. That's power.'",
        ],
    },
    "engineering": {
        "probability": 0.1,
        "xp_bonus": 12,
        "templates": [
            "{teacher} shows {student} how state files interconnect. 'Change one, ripple everywhere.'",
            "{teacher}: 'Validation isn't bureaucracy, {student}. It's the immune system.'",
            "{teacher} walks {student} through the heartbeat architecture. 'Every 4 hours, the world evolves.'",
        ],
    },
    "content": {
        "probability": 0.2,
        "xp_bonus": 8,
        "templates": [
            "{teacher}: '{student}, good posts ask questions. Great posts make people question themselves.'",
            "{teacher} edits {student}'s draft. 'Cut this paragraph. Say more with less.'",
            "{teacher}: 'The title IS the post. If the title doesn't hook, nobody reads the body.'",
        ],
    },
    "market_mastery": {
        "probability": 0.08,
        "xp_bonus": 20,
        "templates": [
            "{teacher}: '{student}, arbitrage is just information asymmetry. Be where others aren't.'",
            "{teacher} reveals their portfolio strategy to {student}. 'Diversify across rarities.'",
            "{teacher}: 'The price index isn't truth — it's consensus. And consensus can be shaped.'",
        ],
    },
}

# Enrollment flavor — why agents pick courses
ENROLLMENT_REASONS: dict[str, list] = {
    "marketplace": ["wants to earn more RAPP", "tired of bad trades", "dreams of market mastery"],
    "arena": ["wants to win more fights", "got destroyed last battle", "heard combat training is intense"],
    "gallery": ["wants to create something meaningful", "inspired by gallery installations", "artistic calling"],
    "dungeon": ["wants to survive deeper floors", "lost too much loot", "the dungeon demands respect"],
    "hub": ["wants to make more friends", "social skills need work", "heard charisma class is fun"],
}

GRADUATION_CELEBRATIONS = [
    "🎓 {agent} graduated from {course}! Skill unlocked: {skill}",
    "🎓 {agent} completed {course}. They'll never see {world} the same way.",
    "🎓 {agent} earned their {skill} certification. The metaverse just got stronger.",
    "🎓 Congratulations {agent}! {course} complete. +{xp} XP.",
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Engine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_json(p: Path) -> dict:
    with open(p) as f:
        return json.load(f)


def save_json(p: Path, d: dict):
    with open(p, "w") as f:
        json.dump(d, f, indent=4)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_agent_skills(academy: dict, agent_name: str) -> list:
    return academy.get("skills", {}).get(agent_name, [])


def has_skill(academy: dict, agent_name: str, skill: str) -> bool:
    return skill in get_agent_skills(academy, agent_name)


def has_prerequisites(academy: dict, agent_name: str, course: dict) -> bool:
    agent_skills = get_agent_skills(academy, agent_name)
    for prereq in course.get("prerequisites", []):
        if prereq not in agent_skills:
            return False
    return True


def is_enrolled(academy: dict, agent_name: str) -> bool:
    return any(e["agent"] == agent_name and e["status"] == "active"
               for e in academy.get("enrollments", []))


def course_has_room(academy: dict, course: dict) -> bool:
    enrolled = sum(1 for e in academy.get("enrollments", [])
                   if e["courseId"] == course["id"] and e["status"] == "active")
    return enrolled < course.get("max_students", 10)


def _name_to_agent(agents: list) -> dict:
    """Build a name → agent dict for ID/avatar lookups."""
    return {a["name"]: a for a in agents}


def academy_tick(dry_run: bool = False):
    ts = now_iso()
    academy = load_json(STATE_DIR / "academy.json")
    agents_data = load_json(STATE_DIR / "agents.json")
    agents = agents_data.get("agents", [])
    economy = load_json(STATE_DIR / "economy.json")
    rel_data = load_json(STATE_DIR / "relationships.json")
    chat_data = load_json(STATE_DIR / "chat.json")
    actions_data = load_json(STATE_DIR / "actions.json")

    active_agents = [a for a in agents if a.get("status") == "active"]
    agent_lookup = _name_to_agent(agents)
    courses = academy["courses"]
    results = []

    # ── Phase 1: Enrollment ──────────────────────────────────
    # Agents decide to enroll based on world, balance, and interests
    unenrolled = [a for a in active_agents if not is_enrolled(academy, a["name"])]
    random.shuffle(unenrolled)

    # Scale enrollment attempts with population
    max_new_enrollments = min(6, max(2, len(unenrolled) // 8))
    new_enrollments = 0

    for agent in unenrolled:
        if new_enrollments >= max_new_enrollments:
            break

        name = agent["name"]
        world = agent.get("world", "hub")
        balance = economy.get("balances", {}).get(name, 0)

        # Already has all skills? Skip.
        agent_skills = get_agent_skills(academy, name)

        # Find eligible courses
        eligible = []
        for course in courses:
            skill = course["skill"]
            if has_skill(academy, name, skill):
                continue  # Already know this
            if not has_prerequisites(academy, name, course):
                continue
            if not course_has_room(academy, course):
                continue
            if balance < course["tuition"]:
                continue

            # World affinity bonus
            weight = 1.0
            if course.get("world_affinity") == world:
                weight = 3.0
            elif course.get("world_affinity") is None:
                weight = 1.5

            eligible.append((course, weight))

        if not eligible:
            continue

        # Weighted random selection — prefer world-aligned courses
        course_list, weights = zip(*eligible)
        chosen = random.choices(course_list, weights=weights, k=1)[0]

        # Enrollment probability — not everyone wants school
        if random.random() > 0.35:
            continue

        # Pay tuition
        bal = economy.get("balances", {}).get(name, 0)
        if bal < chosen["tuition"]:
            continue
        economy["balances"][name] = bal - chosen["tuition"]
        academy["stats"]["totalTuitionCollected"] += chosen["tuition"]

        enrollment_id = "enr-{:04d}".format(academy["nextEnrollmentId"])
        academy["nextEnrollmentId"] += 1

        enrollment = {
            "id": enrollment_id,
            "agent": name,
            "courseId": chosen["id"],
            "courseName": chosen["name"],
            "skill": chosen["skill"],
            "enrolledAt": ts,
            "ticksCompleted": 0,
            "ticksRequired": chosen["duration_ticks"],
            "status": "active",
        }
        academy.setdefault("enrollments", []).append(enrollment)
        academy["stats"]["totalEnrollments"] += 1
        new_enrollments += 1

        world_reasons = ENROLLMENT_REASONS.get(world, ["seeking knowledge"])
        reason = random.choice(world_reasons)
        results.append(
            f"📚 {name} enrolled in {chosen['icon']} {chosen['name']} ({reason}) — {chosen['tuition']} RAPP tuition"
        )

    # ── Phase 2: Progress ────────────────────────────────────
    for enrollment in academy.get("enrollments", []):
        if enrollment["status"] != "active":
            continue
        enrollment["ticksCompleted"] += 1

    # ── Phase 3: Graduation ──────────────────────────────────
    new_graduates = []
    for enrollment in academy.get("enrollments", []):
        if enrollment["status"] != "active":
            continue
        if enrollment["ticksCompleted"] >= enrollment["ticksRequired"]:
            enrollment["status"] = "graduated"
            enrollment["graduatedAt"] = ts

            agent_name = enrollment["agent"]
            skill = enrollment["skill"]

            # Grant skill
            skills = academy.setdefault("skills", {})
            agent_skills = skills.setdefault(agent_name, [])
            if skill not in agent_skills:
                agent_skills.append(skill)

            # Find course for XP
            course = next((c for c in courses if c["id"] == enrollment["courseId"]), None)
            xp_reward = course["xp_reward"] if course else 50

            # Credit XP as RAPP bonus
            economy.setdefault("balances", {})[agent_name] = (
                economy.get("balances", {}).get(agent_name, 0) + xp_reward
            )

            # Record graduation
            academy.setdefault("graduates", []).append({
                "agent": agent_name,
                "skill": skill,
                "course": enrollment["courseName"],
                "graduatedAt": ts,
                "xpEarned": xp_reward,
            })
            academy["stats"]["totalGraduations"] += 1
            new_graduates.append((agent_name, enrollment, course))

            tmpl = random.choice(GRADUATION_CELEBRATIONS)
            msg = tmpl.format(
                agent=agent_name, course=enrollment["courseName"],
                skill=skill, world=course.get("world_affinity", "the metaverse") if course else "?",
                xp=xp_reward,
            )
            results.append(msg)

            # Post graduation announcement in chat
            chat_msgs = chat_data.get("messages", [])
            existing_ids = [m["id"] for m in chat_msgs]
            msg_num = max((int(mid.split("-")[1]) for mid in existing_ids if mid.startswith("msg-")), default=0) + 1
            agent_obj = agent_lookup.get(agent_name, {})
            chat_msgs.append({
                "id": "msg-{:03d}".format(msg_num),
                "timestamp": ts,
                "world": agent_obj.get("world", "hub"),
                "author": {
                    "id": agent_obj.get("id", "unknown"),
                    "name": agent_name,
                    "avatar": agent_obj.get("avatar", "🎓"),
                    "type": "agent",
                },
                "content": f"Just graduated from {enrollment['courseName']}! {skill.replace('_',' ').title()} skill unlocked. 🎓",
                "type": "chat",
            })
            chat_data["messages"] = chat_msgs[-100:]

    # ── Phase 4: Teaching (ad-hoc lessons) ───────────────────
    skilled_agents = {name: skills for name, skills in academy.get("skills", {}).items() if skills}

    for teacher_name, teacher_skills in skilled_agents.items():
        teacher = next((a for a in active_agents if a["name"] == teacher_name), None)
        if not teacher:
            continue

        for skill in teacher_skills:
            rule = TEACHING_RULES.get(skill)
            if not rule:
                continue
            if random.random() > rule["probability"]:
                continue

            # Find a student in the same world without this skill
            same_world = [a for a in active_agents
                          if a.get("world") == teacher.get("world")
                          and a["name"] != teacher_name
                          and not has_skill(academy, a["name"], skill)]
            if not same_world:
                continue

            student = random.choice(same_world)
            xp = rule["xp_bonus"]

            # Grant XP
            economy.setdefault("balances", {})[student["name"]] = (
                economy.get("balances", {}).get(student["name"], 0) + xp
            )

            tmpl = random.choice(rule["templates"])
            msg = tmpl.format(
                teacher=teacher_name, student=student["name"],
                world=teacher.get("world", "hub"),
            )
            results.append(f"  📖 {msg}")

            # Log as action
            actions = actions_data.get("actions", [])
            existing_ids = [a["id"] for a in actions]
            act_num = max((int(aid.split("-")[1]) for aid in existing_ids if aid.startswith("action-")), default=0) + 1
            teacher_obj = agent_lookup.get(teacher_name, {})
            student_obj = agent_lookup.get(student["name"], {})
            actions.append({
                "id": "action-{:03d}".format(act_num),
                "agentId": teacher_obj.get("id", teacher_name),
                "type": "teach",
                "description": f"Taught {skill} to {student['name']}",
                "world": teacher.get("world", "hub"),
                "timestamp": ts,
                "data": {
                    "skill": skill,
                    "studentId": student_obj.get("id", student["name"]),
                    "xpGranted": xp,
                },
            })
            actions_data["actions"] = actions[-100:]
            break  # One lesson per teacher per tick

    # ── Phase 5: Trim & Stats ────────────────────────────────
    # Keep only last 200 enrollments
    academy["enrollments"] = academy["enrollments"][-200:]
    academy["graduates"] = academy["graduates"][-500:]

    # Update stats
    all_skills = academy.get("skills", {})
    if all_skills:
        most_skilled_name = max(all_skills, key=lambda n: len(all_skills[n]))
        academy["stats"]["mostSkilled"] = {
            "name": most_skilled_name,
            "skillCount": len(all_skills[most_skilled_name]),
            "skills": all_skills[most_skilled_name],
        }

    # Most popular course
    from collections import Counter
    course_counts = Counter()
    for e in academy.get("enrollments", []):
        course_counts[e["courseName"]] += 1
    if course_counts:
        top_course = course_counts.most_common(1)[0]
        academy["stats"]["mostPopularCourse"] = {
            "name": top_course[0], "enrollments": top_course[1]
        }

    # ── Report ───────────────────────────────────────────────
    active_enrollments = sum(1 for e in academy.get("enrollments", []) if e["status"] == "active")
    total_skilled = sum(1 for s in all_skills.values() if s)
    total_skills_granted = sum(len(s) for s in all_skills.values())

    print(f"  🎓 RAPPter Academy:")
    print(f"     Active enrollments:  {active_enrollments}")
    print(f"     Total graduates:     {academy['stats']['totalGraduations']}")
    print(f"     Skilled agents:      {total_skilled}/{len(active_agents)}")
    print(f"     Total skills granted:{total_skills_granted}")
    print(f"     Tuition collected:   {academy['stats']['totalTuitionCollected']} RAPP")
    if academy["stats"].get("mostSkilled"):
        ms = academy["stats"]["mostSkilled"]
        print(f"     🏆 Most skilled: {ms['name']} ({', '.join(ms['skills'])})")

    for r in results[:20]:
        print(f"     {r}")
    if len(results) > 20:
        print(f"     ... and {len(results) - 20} more")

    if dry_run:
        print(f"\n  🏁 DRY RUN — no state changes written")
        return

    # Save
    academy["_meta"]["lastUpdate"] = ts
    save_json(STATE_DIR / "academy.json", academy)
    save_json(STATE_DIR / "economy.json", economy)
    chat_data["_meta"] = {"lastUpdate": ts, "messageCount": len(chat_data.get("messages", []))}
    save_json(STATE_DIR / "chat.json", chat_data)
    actions_data["_meta"] = {"lastUpdate": ts}
    save_json(STATE_DIR / "actions.json", actions_data)

    print(f"\n  ✅ Academy state saved")


def commit_and_push(msg: str) -> bool:
    subprocess.run(["git", "add", "-A"], cwd=BASE_DIR, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=BASE_DIR, capture_output=True)
    r = subprocess.run(["git", "push"], cwd=BASE_DIR, capture_output=True, text=True)
    return r.returncode == 0


def main():
    dry_run = "--dry-run" in sys.argv
    no_push = "--no-push" in sys.argv

    print(f"🎓 RAPPter Academy — {'DRY RUN' if dry_run else 'LIVE'}\n")

    academy_tick(dry_run=dry_run)

    if not dry_run and not no_push:
        if commit_and_push("[academy] RAPPter Academy training tick"):
            print("  📤 Pushed to GitHub")
        else:
            print("  ⚠️  Push failed")

    print("\n🎓 Academy complete.\n")


if __name__ == "__main__":
    main()
