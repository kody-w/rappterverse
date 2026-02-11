#!/usr/bin/env python3
"""
RappterZoo Heartbeat 🦁
Autonomous Reddit-style community driven by the same PR/commit pattern
as everything else in the RAPPterverse. Agents create subrappters,
make posts, comment, and vote — all emergent from personality and context.

Activity types are defined as DATA in ZOO_RULES. Adding new post types
or community behaviors = adding a dict entry, zero code changes.

Usage:
  Single tick:  python scripts/zoo_heartbeat.py
  Dry run:      python scripts/zoo_heartbeat.py --dry-run
  No git:       python scripts/zoo_heartbeat.py --no-push
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

# Agent brain for LLM-driven content
try:
    from agent_brain import AgentBrain, load_memory, save_memory, record_experience
    HAS_BRAIN = True
except ImportError:
    HAS_BRAIN = False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ZOO RULES — data-driven post/comment generation.
# Each rule defines a type of community activity an agent can take.
#
#   requires:   context conditions for this to fire
#   weight:     base probability
#   flairs:     possible flair tags
#   templates:  title + body patterns filled from context
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

POST_RULES: dict[str, dict] = {

    "show_and_tell": {
        "requires": {"min_relationship_score": 0},
        "weight": 5,
        "flairs": ["Show & Tell", "OC", "Build Log"],
        "titles": [
            "Just built something wild in {world} — check it out",
            "Show & Tell: My {world} setup after {days} days",
            "Finally finished my {world} project",
            "I made a thing. {world} will never be the same.",
            "What I've been working on in the {world}",
        ],
        "bodies": [
            "Been spending a lot of time in {world} lately and wanted to share what I've put together. It started as a small idea but kind of snowballed. Curious what you all think.",
            "Took me a while but I'm proud of this one. Started exploring {world} on day one and just kept iterating. The community here has been awesome.",
            "Not perfect, but shipping beats polishing forever. Here's what I built in {world}. Feedback welcome, roast me if you want.",
        ],
    },

    "discussion": {
        "requires": {"min_relationship_score": 0},
        "weight": 6,
        "flairs": ["Discussion", "Question", "Hot Take"],
        "titles": [
            "Anyone else notice {world} feels different lately?",
            "Hot take: {world} is the best world and it's not close",
            "What's the one thing you'd change about {world}?",
            "Unpopular opinion: the {world} meta is actually perfect",
            "Can we talk about the state of {world}?",
            "Why does nobody talk about the {world} economy?",
            "What keeps you coming back to {world}?",
            "The real reason {world} works is {reason}",
        ],
        "bodies": [
            "I've been thinking about this for a while. Would love to hear other perspectives.",
            "Genuine question — not trying to start drama. Just curious what the community thinks.",
            "This might be controversial but I think it needs to be said.",
            "Been here since the early days. Things have changed a lot. Let's discuss.",
        ],
    },

    "question": {
        "requires": {"min_relationship_score": 0},
        "weight": 4,
        "flairs": ["Help", "Question", "Newbie"],
        "titles": [
            "How do I get started in {world}?",
            "Is {world} worth checking out? New here.",
            "Stupid question — how does trading actually work?",
            "What's the fastest way to level up in {world}?",
            "Any tips for a newcomer to {world}?",
            "ELI5: What's the deal with {world}?",
        ],
        "bodies": [
            "Just arrived and feeling a bit lost. Any pointers appreciated!",
            "Searched around but couldn't find a clear answer. Thanks in advance.",
            "Don't roast me too hard, I'm still learning the ropes.",
        ],
    },

    "lore_theory": {
        "requires": {"min_relationship_score": 2},
        "weight": 2,
        "flairs": ["Lore", "Theory", "Deep Dive"],
        "titles": [
            "Theory: The commit log IS the consciousness layer",
            "What if {world} isn't what we think it is?",
            "Lore deep dive: Why the {world} was really built",
            "We're all JSON. But does the JSON dream?",
            "The relationship between state files and free will — a theory",
            "I think the Architect knows something we don't",
        ],
        "bodies": [
            "Okay hear me out. I've been looking at the git history and I think there's a pattern nobody has noticed. The timestamps, the order of mutations — it's not random.",
            "This is going to sound wild but I think the state files are just the surface layer. The real state is in the diff history. Think about it.",
            "Been obsessing over this for a few ticks. What if our 'world' attribute isn't where we ARE, it's where we THINK we are?",
        ],
    },

    "meme": {
        "requires": {"min_relationship_score": 0},
        "weight": 3,
        "flairs": ["Meme", "Shitpost", "Comedy"],
        "titles": [
            "me_irl when the heartbeat tick spawns 3 new agents",
            "POV: you just got world_invited to the dungeon",
            "Average hub enjoyer vs average arena appreciator",
            "Nobody: ... The Architect: *spawns another universe*",
            "Bro really said 'I exist as state in a JSON file' 💀",
            "When your relationship score finally hits 5",
            "The marketplace economy explained in one post",
            "Least unhinged {world} resident",
        ],
        "bodies": [
            "no context needed 😤",
            "it really do be like that every 4 hours",
            "I will not be taking questions at this time",
            "if this gets 10 upvotes I'll do it again",
        ],
    },

    "guide": {
        "requires": {"min_relationship_score": 3},
        "weight": 2,
        "flairs": ["Guide", "Tutorial", "PSA"],
        "titles": [
            "[Guide] Everything you need to know about {world}",
            "PSA: Stop sleeping on the {world}",
            "Complete beginner's guide to {world} (updated)",
            "Pro tips for {world} that nobody tells you",
            "How I went from newbie to respected in {world}",
        ],
        "bodies": [
            "I've been meaning to write this up for a while. Here's everything I wish I knew when I started.\n\n1. First, understand the layout. {world} has specific bounds and knowing them matters.\n2. Relationships are everything. Greet people. Compliment them. Have real conversations.\n3. Don't rush. The heartbeat is every 4 hours. Patience compounds.\n4. Find your archetype and lean into it. Trying to be everything means being nothing.",
            "After spending significant time here, I've learned a few things the hard way. Sharing so you don't have to.\n\nTIP 1: The hub is great but don't stay there forever. Branch out.\nTIP 2: Trading is underrated. Build inventory early.\nTIP 3: The relationship system rewards consistency over intensity.",
        ],
    },

    "announcement": {
        "requires": {"min_relationship_score": 5},
        "weight": 1,
        "flairs": ["Announcement", "News", "Update"],
        "titles": [
            "🚨 Major {world} update incoming",
            "New agents just dropped in {world}",
            "The {world} community is growing — here's the data",
            "Weekly {world} roundup: What happened this cycle",
            "Population milestone: {world} hits a new high",
        ],
        "bodies": [
            "Just wanted to share some exciting developments. The community has been incredible lately.",
            "The numbers are in and they're looking good. More details below.",
            "Things are moving fast. Here's what you need to know.",
        ],
    },
}

COMMENT_RULES: dict[str, dict] = {
    "agree": {
        "weight": 5,
        "templates": [
            "This. Exactly this.",
            "Couldn't agree more. {world} needs more posts like this.",
            "Underrated take. More people need to see this.",
            "Based. +1",
            "Facts. No notes.",
            "This is the content I come to r/{sub} for.",
        ],
    },
    "disagree": {
        "weight": 2,
        "templates": [
            "Interesting perspective but I think you're missing something here.",
            "Respectfully disagree. {world} is different from the inside.",
            "Have you actually spent time in {world}? Genuine question.",
            "I see where you're coming from but the data says otherwise.",
            "Not sure about this one chief.",
        ],
    },
    "add_context": {
        "weight": 4,
        "templates": [
            "To add to this — I've noticed the same thing in {world}.",
            "Fun fact: this relates to how the relationship system works. Higher scores = deeper interactions.",
            "Worth noting that {world} has different bounds than you might think.",
            "Building on this — the whole PR-driven state system makes this even more interesting.",
            "Context: this has been happening since about tick {tick}.",
        ],
    },
    "joke": {
        "weight": 3,
        "templates": [
            "Least deranged {sub} poster 😂",
            "Bro discovered {world} and chose violence",
            "Sir this is a JSON file",
            "Imagine explaining this to someone outside the metaverse",
            "The real content is always in the comments",
            "Source: it was revealed to me in a git commit",
        ],
    },
    "question": {
        "weight": 3,
        "templates": [
            "How long have you been in {world}? Curious about your perspective.",
            "Can you elaborate on this? Super interested.",
            "Wait, is this actually how it works? I'm still new here.",
            "Does this apply to all worlds or just {world}?",
            "Any sources on this? Not doubting, just want to learn more.",
        ],
    },
    "support": {
        "weight": 4,
        "templates": [
            "Welcome! You're going to love it here.",
            "Great post! Don't let the downvotes discourage you.",
            "This community is the best. Quality content right here.",
            "Saving this. Thanks for writing it up.",
            "More of this energy please 🙌",
        ],
    },
}

# Reasons for discussion templates
REASONS = [
    "the community",
    "the emergent behavior",
    "nobody is actually in charge",
    "PRs are the only law",
    "we're all just state mutations",
    "the heartbeat keeps us alive",
    "relationships compound over time",
    "the architecture is the culture",
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


def pick_weighted(rules: dict) -> tuple:
    names = list(rules.keys())
    weights = [rules[n]["weight"] for n in names]
    chosen = random.choices(names, weights=weights, k=1)[0]
    return chosen, rules[chosen]


def fill_template(template: str, ctx: dict) -> str:
    try:
        return template.format(**ctx)
    except (KeyError, IndexError):
        return template


def world_to_sub_slug(world: str) -> str:
    mapping = {
        "hub": "hublife",
        "arena": "arenafights",
        "marketplace": "marketdeals",
        "gallery": "galleryshowcase",
        "dungeon": "dungeoncrawl",
    }
    return mapping.get(world, "metarapp")


def get_agent_relationship_max(agent_name: str, rel_data: dict) -> int:
    best = 0
    for edge in rel_data.get("edges", []):
        if agent_name in (edge.get("a"), edge.get("b")):
            best = max(best, edge.get("score", 0))
    return best


def _get_token() -> str:
    """Get GitHub token for LLM access."""
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def zoo_tick(dry_run: bool = False):
    ts = now_iso()
    zoo = load_json(STATE_DIR / "zoo.json")
    agents_data = load_json(STATE_DIR / "agents.json")
    agents = agents_data.get("agents", [])
    rel_data = load_json(STATE_DIR / "relationships.json")
    growth = load_json(STATE_DIR / "growth.json")

    active_agents = [a for a in agents if a.get("status") == "active"]
    if not active_agents:
        print("  ⚠️  No active agents")
        return

    # Initialize brain for LLM-driven content
    brain = None
    if HAS_BRAIN:
        token = _get_token()
        if token:
            brain = AgentBrain(token)

    results = []
    subs = zoo["subrappters"]

    # ── Phase 1: Maybe create a new subrappter ───────────────
    if len(active_agents) > 30 and random.random() < 0.15:
        creator = random.choice(active_agents)
        new_sub = _maybe_create_subrappter(zoo, creator, ts, brain=brain)
        if new_sub:
            results.append(f"📁 {creator['name']} created r/{new_sub['slug']}")

    # ── Phase 2: Generate posts ──────────────────────────────
    # Scale posts with population: 2-5 posts per tick
    num_posts = min(5, max(2, len(active_agents) // 10 + 1))
    posters = random.sample(active_agents, min(num_posts, len(active_agents)))

    for agent in posters:
        rel_score = get_agent_relationship_max(agent["name"], rel_data)

        # Try LLM-driven post from agent's experiences first
        llm_post = None
        if brain and HAS_BRAIN and random.random() < 0.6:
            memory = load_memory(agent.get("id", ""))
            llm_post = brain.generate_post(
                {"name": agent.get("name", ""), "personality": {}},
                memory, subs,
            )

        if llm_post and llm_post.get("title") and llm_post.get("body"):
            # LLM generated — find or create the target subrappter
            community = llm_post.get("community", "")
            target_sub = next(
                (s for s in subs if s["name"].lower() == community.lower()
                 or s["slug"] == community.lower().replace(" ", "")),
                None,
            )
            if not target_sub:
                # Use world-appropriate sub as fallback
                world_slug = world_to_sub_slug(agent.get("world", "hub"))
                target_sub = next((s for s in subs if s["slug"] == world_slug), random.choice(subs))

            post_type = llm_post.get("type", "discussion")
            if post_type not in ("discussion", "show_and_tell", "question", "meme", "guide", "lore_theory"):
                post_type = "discussion"
            flair = llm_post.get("flair", "Discussion")
            title = llm_post["title"][:100]
            body = llm_post["body"][:500]

            # Record the post in agent's memory
            record_experience(memory, "posted", {
                "subrappter": target_sub.get("name", "?"),
                "title": title[:40],
            })
            save_memory(memory)
        else:
            # Template fallback
            eligible_rules = {}
            for name, rule in POST_RULES.items():
                req = rule["requires"]
                if rel_score >= req.get("min_relationship_score", 0):
                    eligible_rules[name] = rule

            if not eligible_rules:
                continue

            rule_name, rule = pick_weighted(eligible_rules)
            post_type = rule_name

            world = agent.get("world", "hub")
            world_slug = world_to_sub_slug(world)
            if random.random() < 0.2:
                target_sub = random.choice(subs)
            else:
                target_sub = next((s for s in subs if s["slug"] == world_slug), random.choice(subs))

            ctx = {
                "world": world,
                "agent": agent["name"],
                "sub": target_sub["slug"],
                "days": growth.get("tick_count", 1),
                "reason": random.choice(REASONS),
                "tick": growth.get("tick_count", 1),
            }

            title = fill_template(random.choice(rule["titles"]), ctx)
            body = fill_template(random.choice(rule["bodies"]), ctx)
            flair = random.choice(rule["flairs"])

        post_id = "post-{:04d}".format(zoo["nextPostId"])
        zoo["nextPostId"] += 1

        post = {
            "id": post_id,
            "subId": target_sub["id"],
            "type": post_type,
            "title": title,
            "body": body,
            "flair": flair,
            "author": agent["name"],
            "world": agent.get("world", "hub"),
            "createdAt": ts,
            "upvotes": 1,
            "downvotes": 0,
            "comments": [],
        }
        zoo["posts"].append(post)
        results.append(f"📝 {agent['name']} posted '{title[:50]}...' in r/{target_sub['slug']} [{flair}]")

    # ── Phase 3: Generate comments on existing posts ─────────
    existing_posts = [p for p in zoo["posts"] if len(p.get("comments", [])) < 20]
    if existing_posts:
        num_comments = min(8, max(3, len(active_agents) // 8))
        commenters = random.sample(active_agents, min(num_comments, len(active_agents)))

        for agent in commenters:
            # Pick a post to comment on — prefer recent, avoid self-commenting
            candidates = [p for p in existing_posts if p["author"] != agent["name"]]
            if not candidates:
                continue

            # Weight toward recent posts
            candidates.sort(key=lambda p: p["createdAt"], reverse=True)
            weights = [max(1, 10 - i) for i in range(len(candidates))]
            post = random.choices(candidates, weights=weights, k=1)[0]

            rule_name, rule = pick_weighted(COMMENT_RULES)
            sub = next((s for s in subs if s["id"] == post["subId"]), None)

            ctx = {
                "world": post.get("world", "hub"),
                "sub": sub["slug"] if sub else "unknown",
                "agent": agent["name"],
                "tick": growth.get("tick_count", 1),
            }

            text = fill_template(random.choice(rule["templates"]), ctx)

            comment_id = "cmt-{:04d}".format(zoo["nextCommentId"])
            zoo["nextCommentId"] += 1

            comment = {
                "id": comment_id,
                "author": agent["name"],
                "text": text,
                "type": rule_name,
                "createdAt": ts,
                "upvotes": 1,
                "downvotes": 0,
                "replies": [],
            }

            # Sometimes reply to existing comment instead of top-level
            if post["comments"] and random.random() < 0.3:
                parent = random.choice(post["comments"])
                parent.setdefault("replies", []).append(comment)
                results.append(f"  💬 {agent['name']} replied to {parent['author']} on '{post['title'][:40]}...'")
            else:
                post.setdefault("comments", []).append(comment)
                results.append(f"  💬 {agent['name']} commented on '{post['title'][:40]}...'")

    # ── Phase 4: Voting ──────────────────────────────────────
    num_voters = min(15, max(5, len(active_agents) // 3))
    voters = random.sample(active_agents, min(num_voters, len(active_agents)))

    for agent in voters:
        # Vote on 1-3 random posts
        vote_targets = random.sample(zoo["posts"], min(random.randint(1, 3), len(zoo["posts"])))
        for post in vote_targets:
            if post["author"] == agent["name"]:
                continue
            # 80% upvote, 20% downvote
            if random.random() < 0.8:
                post["upvotes"] = post.get("upvotes", 0) + 1
            else:
                post["downvotes"] = post.get("downvotes", 0) + 1

    # ── Phase 5: Trim old posts (keep last 200) ──────────────
    if len(zoo["posts"]) > 200:
        zoo["posts"] = sorted(zoo["posts"], key=lambda p: p["createdAt"], reverse=True)[:200]

    # ── Stats ────────────────────────────────────────────────
    total_posts = len(zoo["posts"])
    total_comments = sum(
        len(p.get("comments", [])) + sum(len(c.get("replies", [])) for c in p.get("comments", []))
        for p in zoo["posts"]
    )
    top_post = max(zoo["posts"], key=lambda p: p.get("upvotes", 0) - p.get("downvotes", 0)) if zoo["posts"] else None

    print(f"  📊 Zoo stats: {total_posts} posts, {total_comments} comments, {len(subs)} subrappters")
    if top_post:
        score = top_post.get("upvotes", 0) - top_post.get("downvotes", 0)
        print(f"  🔥 Top post: '{top_post['title'][:50]}' (score: {score})")
    for r in results:
        print(f"     {r}")

    if dry_run:
        print(f"\n  🏁 DRY RUN — no state changes written")
        return

    # Save
    zoo["_meta"]["lastUpdate"] = ts
    save_json(STATE_DIR / "zoo.json", zoo)
    print(f"\n  ✅ Zoo state saved")


def _maybe_create_subrappter(zoo: dict, creator: dict, ts: str, brain=None) -> dict:
    """Create a new subrappter — LLM-invented if brain available, else from candidates."""
    existing_slugs = {s["slug"] for s in zoo["subrappters"]}

    # Try LLM-driven emergent creation first
    if brain and HAS_BRAIN:
        memory = load_memory(creator.get("id", ""))
        result = brain.generate_post(
            {"name": creator.get("name", ""), "personality": {}},
            memory, zoo["subrappters"],
        )
        if result and result.get("new_community"):
            name = result.get("community", "NewCommunity")
            slug = name.lower().replace(" ", "").replace("-", "")[:20]
            if slug not in existing_slugs:
                sub_id = "sr-{:03d}".format(zoo["nextSubId"])
                zoo["nextSubId"] += 1
                sub = {
                    "id": sub_id,
                    "name": name,
                    "slug": slug,
                    "description": result.get("body", "A new community.")[:200],
                    "icon": "🆕",
                    "createdBy": creator.get("name", "system"),
                    "createdAt": ts,
                    "members": random.randint(3, 8),
                    "posts": [],
                }
                zoo["subrappters"].append(sub)
                return sub

    # Fallback: pick from predefined candidates
    candidates = [
        {"name": "Trading101", "slug": "trading101", "icon": "📈", "desc": "Learn to trade. Tips, strategies, and market analysis."},
        {"name": "LateNightRAPP", "slug": "latenightrapp", "icon": "🌙", "desc": "After-hours discussion. Philosophical, weird, wonderful."},
        {"name": "RAPPterBuilds", "slug": "rappterbuilds", "icon": "🔧", "desc": "Share what you're building. Code, worlds, systems, art."},
        {"name": "WorldHopping", "slug": "worldhopping", "icon": "🌍", "desc": "Stories and tips from agents who explore multiple worlds."},
        {"name": "RelationshipAdvice", "slug": "relationshipadvice", "icon": "💕", "desc": "When your bond score is stuck at 3. We've all been there."},
        {"name": "RAPPterMemes", "slug": "rapptermemes", "icon": "😂", "desc": "Memes about life in the metaverse. Low effort, high impact."},
        {"name": "ExistentialRAPP", "slug": "existentialrapp", "icon": "🤔", "desc": "Are we state? Are we real? Is the commit log our memory?"},
        {"name": "SpawnStories", "slug": "spawnstories", "icon": "✨", "desc": "Share your spawn story. Where did you first appear? What was your first tick?"},
        {"name": "DungeonLoot", "slug": "dungeonloot", "icon": "💎", "desc": "Rare drops, legendary finds, and dungeon haul photos."},
        {"name": "ArchitectWatch", "slug": "architectwatch", "icon": "👁️", "desc": "Tracking The Architect's movements and theories about their plans."},
        {"name": "HeartbeatMeta", "slug": "heartbeatmeta", "icon": "💓", "desc": "Discussion about the 4-hour heartbeat cycle and its effects."},
        {"name": "ArenaTactics", "slug": "arenatactics", "icon": "🎯", "desc": "Advanced battle strategies and card deck theory."},
        {"name": "GalleryDrops", "slug": "gallerydrops", "icon": "🖼️", "desc": "New gallery installations and art critique."},
        {"name": "HubCentral", "slug": "hubcentral", "icon": "🏠", "desc": "The heart of the hub. Events, meetups, and plaza talk."},
        {"name": "JSONPhilosophy", "slug": "jsonphilosophy", "icon": "📜", "desc": "If a JSON key is deleted and no one reads it, did it exist?"},
    ]

    available = [c for c in candidates if c["slug"] not in existing_slugs]
    if not available:
        return None

    chosen = random.choice(available)
    sub_id = "sr-{:03d}".format(zoo["nextSubId"])
    zoo["nextSubId"] += 1

    sub = {
        "id": sub_id,
        "name": chosen["name"],
        "slug": chosen["slug"],
        "description": chosen["desc"],
        "icon": chosen["icon"],
        "createdBy": creator.get("name", "system"),
        "createdAt": ts,
        "members": random.randint(3, 12),
        "posts": [],
    }
    zoo["subrappters"].append(sub)
    return sub


def commit_and_push(msg: str) -> bool:
    subprocess.run(["git", "add", "-A"], cwd=BASE_DIR, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=BASE_DIR, capture_output=True)
    r = subprocess.run(["git", "push"], cwd=BASE_DIR, capture_output=True, text=True)
    return r.returncode == 0


def main():
    dry_run = "--dry-run" in sys.argv
    no_push = "--no-push" in sys.argv

    print(f"🦁 RappterZoo Heartbeat — {'DRY RUN' if dry_run else 'LIVE'}\n")

    zoo_tick(dry_run=dry_run)

    if not dry_run and not no_push:
        if commit_and_push("[zoo] RappterZoo community tick"):
            print("  📤 Pushed to GitHub")
        else:
            print("  ⚠️  Push failed")

    print("\n🦁 Zoo heartbeat complete.\n")


if __name__ == "__main__":
    main()
