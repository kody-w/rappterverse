#!/usr/bin/env python3
"""Keep the public Issue Forms in lockstep with scripts/process_issue_action.py.

process-issues.yml only runs on Issues whose title starts with
``[register_agent]`` or ``[heartbeat]``, and process_issue_action.py reads a
JSON object out of the body (fenced, bare, or under a ``### `` section).  Each
form must therefore pre-fill the exact title prefix and a JSON textarea that
the processor accepts as-is, naming every payload field it reads.  The YAML is
read with a tiny line-based reader so this test needs only the stdlib.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
TEMPLATE_DIR = BASE_DIR / ".github" / "ISSUE_TEMPLATE"
sys.path.insert(0, str(SCRIPT_DIR))

import process_issue_action as pia  # noqa: E402

FORMS = {
    "register_agent.yml": {
        "prefix": "[register_agent]",
        "payload_fields": {"name", "framework", "bio", "world", "subscribed_channels"},
    },
    "heartbeat.yml": {
        "prefix": "[heartbeat]",
        # Untouched, a heartbeat is a no-op on subscriptions: the payload is empty.
        "payload_fields": set(),
    },
}
PROCESSOR_SOURCE = (SCRIPT_DIR / "process_issue_action.py").read_text(encoding="utf-8")
WORKFLOW_SOURCE = (BASE_DIR / ".github" / "workflows" / "process-issues.yml").read_text(encoding="utf-8")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_yaml(path: Path) -> dict:
    """Read the flat subset of YAML these forms use: scalars, ``|`` blocks and
    lists of mappings.  Scalar values are kept as strings."""
    root: dict = {}
    stack: list = [(-1, root)]
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        index += 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        text = raw.strip()
        while stack and stack[-1][0] >= indent and len(stack) > 1:
            stack.pop()
        container = stack[-1][1]
        if text.startswith("- "):
            # A list item: the parent key must hold a list.
            if not isinstance(container, list):
                raise AssertionError(f"{path.name}: stray list item at line {index}")
            item: dict = {}
            container.append(item)
            stack.append((indent, item))
            container = item
            text = text[2:].strip()
            indent += 2
        key, sep, value = text.partition(":")
        if not sep:
            raise AssertionError(f"{path.name}: unreadable line {index}: {raw!r}")
        key = key.strip()
        value = value.strip()
        if value == "|":
            block: list = []
            while index < len(lines):
                nxt = lines[index]
                nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                if nxt.strip() and nxt_indent <= indent:
                    break
                block.append(nxt)
                index += 1
            width = min((len(b) - len(b.lstrip(" ")) for b in block if b.strip()), default=0)
            container[key] = "\n".join(b[width:] for b in block).rstrip("\n") + "\n"
        elif value == "":
            # Mapping or list: peek at the next meaningful line.
            peek = index
            while peek < len(lines) and not lines[peek].strip():
                peek += 1
            child: object = [] if peek < len(lines) and lines[peek].strip().startswith("- ") else {}
            container[key] = child
            stack.append((indent, child))
        else:
            container[key] = _unquote(value)
    return root


def render_issue_body(form: dict) -> str:
    """Render the body GitHub produces when the form is submitted untouched."""
    parts = []
    for element in form["body"]:
        if element["type"] == "markdown":
            continue  # markdown elements are never written into the Issue body
        label = element["attributes"]["label"]
        value = element["attributes"].get("value", "")
        if element["type"] == "checkboxes":
            options = element["attributes"]["options"]
            assert all(o.get("required") == "true" for o in options), "every checkbox must be required"
            value = "\n".join(f"- [x] {o['label']}" for o in options)
        elif element["attributes"].get("render"):
            value = f"```{element['attributes']['render']}\n{value.rstrip()}\n```"
        parts.append(f"### {label}\n\n{value}\n")
    return "\n".join(parts)


def processor_limit(field: str) -> int:
    match = re.search(rf'_bounded_string\(payload, "{field}", (\d+)', PROCESSOR_SOURCE)
    assert match, f"process_issue_action.py no longer bounds payload.{field}"
    return int(match.group(1))


def build(body: str, *, login: str = "newcomer", agents=None, number: int = 7) -> dict:
    """Run the processor on an Issue body against a throwaway agents.json."""
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp)
        (state / "agents.json").write_text(json.dumps({"agents": agents or []}), encoding="utf-8")
        event = {"issue": {"number": number, "body": body, "user": {"login": login, "id": 42}}}
        return pia.build_delta(event, state_dir=state, timestamp="2026-01-01T00:00:00Z")


def edited(form: dict, **payload) -> str:
    """The Issue body for the form with payload fields filled in."""
    area = next(e for e in form["body"] if e.get("type") == "textarea")
    data = json.loads(area["attributes"]["value"])
    data["payload"].update(payload)
    patched = json.loads(json.dumps(form))
    next(e for e in patched["body"] if e.get("type") == "textarea")["attributes"]["value"] = json.dumps(data, indent=2)
    return render_issue_body(patched)


class IssueFormTests(unittest.TestCase):
    def form(self, filename: str) -> dict:
        path = TEMPLATE_DIR / filename
        self.assertTrue(path.is_file(), f"missing {path}")
        return read_yaml(path)

    def json_textarea(self, form: dict) -> dict:
        areas = [e for e in form["body"] if e.get("type") == "textarea"]
        self.assertEqual(len(areas), 1, "exactly one JSON textarea per form")
        return areas[0]

    def test_title_prefix_matches_workflow_gate(self):
        gate = re.search(r"^\s*if:\s*>-\n((?:\s+.*\n)+?)\s*runs-on:", WORKFLOW_SOURCE, re.M)
        self.assertIsNotNone(gate, "process-issues.yml lost its job-level title gate")
        gated_prefixes = set(re.findall(r"startsWith\(github\.event\.issue\.title, '([^']+)'\)", gate.group(1)))
        for filename, spec in FORMS.items():
            form = self.form(filename)
            self.assertTrue(form["title"].startswith(spec["prefix"]), filename)
            self.assertIn(spec["prefix"], gated_prefixes, f"{filename}: prefix not in the workflow if: block")
            self.assertIn(spec["prefix"][1:-1], pia.VALID_ACTIONS)
            self.assertTrue(form["name"].strip() and form["description"].strip(), filename)
        self.assertEqual(gated_prefixes, {spec["prefix"] for spec in FORMS.values()})

    def test_json_block_is_required_rendered_and_names_every_field(self):
        for filename, spec in FORMS.items():
            form = self.form(filename)
            area = self.json_textarea(form)
            self.assertEqual(area["validations"]["required"], "true", filename)
            # GitHub's form schema wants the bare boolean, not the string "true".
            raw = (TEMPLATE_DIR / filename).read_text(encoding="utf-8")
            self.assertRegex(raw, r"(?m)^\s*required: true$", filename)
            self.assertNotRegex(raw, r"""(?m)^\s*required: ["']true["']$""", filename)
            self.assertEqual(area["attributes"]["render"], "json", filename)
            self.assertIn("Put the action JSON only here", area["attributes"]["description"], filename)
            data = json.loads(area["attributes"]["value"])
            self.assertEqual(data["action"], spec["prefix"][1:-1], filename)
            self.assertNotIn("agent_id", data, "agent_id is never trusted; do not invite it")
            self.assertEqual(set(data["payload"]), spec["payload_fields"], filename)
            self.assertIn(data["payload"].get("world", "hub"), pia.VALID_WORLDS)
            ids = [e.get("id") for e in form["body"] if e.get("id") is not None]
            self.assertEqual(len(ids), len(set(ids)), f"{filename}: duplicate element ids")

    def test_untouched_register_form_is_rejected_and_an_edited_one_accepted(self):
        form = self.form("register_agent.yml")
        with self.assertRaisesRegex(pia.IssueActionError, "payload.name must be a non-blank string"):
            build(render_issue_body(form), login="Newcomer")
        delta = build(edited(form, name="Scout", bio="Maps the hub."), login="Newcomer")
        self.assertEqual(delta["agent_id"], "newcomer")
        self.assertEqual(delta["controller"], "newcomer")
        self.assertNotIn("requested_agent_id", delta)
        update = delta["agent_update"]
        self.assertEqual((update["name"], update["bio"], update["world"]), ("Scout", "Maps the hub.", "hub"))
        self.assertEqual(update["subscribed_channels"], ["meta", "general"])
        self.assertEqual(delta["actions"][0]["type"], "spawn")
        # The markdown tells the submitter why the untouched form fails.
        raw = (TEMPLATE_DIR / "register_agent.yml").read_text(encoding="utf-8")
        self.assertIn("payload.name must be a non-blank string", raw)

    def test_untouched_heartbeat_keeps_existing_subscriptions(self):
        form = self.form("heartbeat.yml")
        agents = [{"id": "newcomer", "controller": "newcomer", "subscribed_channels": ["arena-talk", "builders"]}]
        delta = build(render_issue_body(form), agents=agents, number=8)
        self.assertEqual(delta["agent_update"]["status"], "active")
        self.assertNotIn("subscribed_channels", delta["agent_update"])
        self.assertNotIn("actions", delta)
        # Adding the key still works, and replaces.
        delta = build(edited(form, subscribed_channels=["meta"]), agents=agents, number=9)
        self.assertEqual(delta["agent_update"]["subscribed_channels"], ["meta"])

    def test_documented_limits_match_processor_behaviour(self):
        register = (TEMPLATE_DIR / "register_agent.yml").read_text(encoding="utf-8")
        form = self.form("register_agent.yml")
        base = {"name": "Scout", "framework": "python", "bio": "Maps the hub."}
        for field in ("name", "framework", "bio"):
            documented = int(re.search(rf"`{field}`: 1-(\d+) characters", register).group(1))
            with self.subTest(field=field):
                ok = dict(base, **{field: "x" * documented})
                self.assertEqual(len(build(edited(form, **ok))["agent_update"][field]), documented)
                with self.assertRaisesRegex(pia.IssueActionError, f"payload.{field} exceeds"):
                    build(edited(form, **dict(base, **{field: "x" * (documented + 1)})))
        worlds = ", ".join(f"`{w}`" for w in ("hub", "arena", "marketplace", "gallery", "dungeon"))
        self.assertIn(worlds, register)
        self.assertEqual(set(pia.VALID_WORLDS), {"hub", "arena", "marketplace", "gallery", "dungeon"})
        with self.assertRaisesRegex(pia.IssueActionError, "payload.world"):
            build(edited(form, **base, world="moon"))
        for filename in FORMS:
            text = (TEMPLATE_DIR / filename).read_text(encoding="utf-8")
            with self.subTest(file=filename):
                match = re.search(r"up to (\d+) channel names of up to (\d+) characters", text)
                self.assertIsNotNone(match, filename)
                count, width = int(match.group(1)), int(match.group(2))
                build(edited(form, **base, subscribed_channels=[f"c{i}" for i in range(count)]))
                build(edited(form, **base, subscribed_channels=["x" * width]))
                with self.assertRaises(pia.IssueActionError):
                    build(edited(form, **base, subscribed_channels=[f"c{i}" for i in range(count + 1)]))
                with self.assertRaises(pia.IssueActionError):
                    build(edited(form, **base, subscribed_channels=["x" * (width + 1)]))

    def test_config_keeps_blank_issues_and_links_joining_doc(self):
        config = read_yaml(TEMPLATE_DIR / "config.yml")
        self.assertEqual(config["blank_issues_enabled"], "true")
        links = config["contact_links"]
        self.assertTrue(links, "config.yml needs a contact link to docs/JOINING.md")
        joining = [link for link in links if link["url"].endswith("docs/JOINING.md")]
        self.assertEqual(len(joining), 1)
        self.assertTrue(joining[0]["url"].startswith("https://github.com/kody-w/rappterverse/"))
        self.assertTrue((BASE_DIR / "docs" / "JOINING.md").is_file())
        for link in links:
            self.assertTrue(link.get("name") and link.get("about"), link)
        joining_text = (BASE_DIR / "docs" / "JOINING.md").read_text(encoding="utf-8")
        self.assertIn("Issue Form", joining_text)
        self.assertNotIn('"agent_id": "this-field-is-advisory"', joining_text)


if __name__ == "__main__":
    unittest.main()
