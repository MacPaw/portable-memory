"""OpenAI (ChatGPT conversations.json) and Claude (memory files) adapter tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from portable_memory.adapters import ClaudeAdapter, OpenAIAdapter


# ------------------------------------------------------------------ OpenAI

def _export():
    return [{
        "title": "Trip planning",
        "conversation_id": "conv_1",
        "create_time": 1700000000.0,
        "mapping": {
            "root": {"id": "root", "message": None, "parent": None, "children": ["a"]},
            "a": {"id": "a", "parent": "root", "children": ["b"], "message": {
                "id": "m_sys", "author": {"role": "system"},
                "content": {"content_type": "text", "parts": [""]}, "create_time": None}},
            # deliberately out of mapping order to exercise create_time sorting:
            "c": {"id": "c", "parent": "b", "children": [], "message": {
                "id": "m_asst", "author": {"role": "assistant"},
                "content": {"content_type": "text", "parts": ["Sure! Here is a plan..."]},
                "metadata": {"model_slug": "gpt-4o"}, "create_time": 1700000200.0}},
            "b": {"id": "b", "parent": "a", "children": ["c"], "message": {
                "id": "m_user", "author": {"role": "user"},
                "content": {"content_type": "text", "parts": ["Plan a trip to Kyoto"]},
                "create_time": 1700000100.0}},
            "d": {"id": "d", "parent": "c", "children": [], "message": {
                "id": "m_hidden", "author": {"role": "assistant"},
                "content": {"content_type": "text", "parts": ["hidden"]},
                "metadata": {"is_visually_hidden_from_conversation": True},
                "create_time": 1700000300.0}},
        },
    }]


def test_openai_conversations_export():
    eps = OpenAIAdapter.parse_episodes(json.dumps(_export()))
    # system + hidden dropped; user + assistant kept, ordered by create_time.
    assert [e.id for e in eps] == ["m_user", "m_asst"]
    assert [e.speaker for e in eps] == ["user", "assistant"]
    assert all(e.source_type == "chat" for e in eps)
    assert all(e.context_id == "conv_1" for e in eps)

    user = eps[0]
    assert user.details == "Plan a trip to Kyoto"
    assert user.event_time == datetime.fromtimestamp(1700000100.0, tz=timezone.utc)
    assert user.metadata["openai_conversation_title"] == "Trip planning"
    assert user.metadata["openai_role"] == "user"
    assert "openai_model" not in user.metadata

    asst = eps[1]
    assert asst.metadata["openai_model"] == "gpt-4o"
    assert asst.metadata["openai_message_id"] == "m_asst"


def test_openai_accepts_single_conversation_and_bytes():
    eps = OpenAIAdapter.parse_episodes(json.dumps(_export()[0]).encode("utf-8"))
    assert len(eps) == 2


def test_openai_saved_memories_fallback():
    eps = OpenAIAdapter.parse_episodes(["I prefer metric units.", {"id": "mem_2", "memory": "Lives in Kyiv."}])
    assert len(eps) == 2
    assert eps[0].source_type == "note" and eps[0].metadata["openai_source"] == "memory"
    assert eps[1].id == "mem_2" and eps[1].details == "Lives in Kyiv."


def test_openai_empty_and_garbage():
    assert OpenAIAdapter.parse_episodes([]) == []
    assert OpenAIAdapter.parse_episodes("{}") == []


# ------------------------------------------------------------------ Claude

CLAUDE_FILES = [
    {"path": "memory/MEMORY.md", "content": "# Memory index\n- project-x: launch\n"},
    {"path": "memory/project-x.md",
     "content": "---\nname: project-x\ndescription: X launch plan\nmetadata:\n  type: project\n---\n"
                "Ship X on Pi Day. Owner: Ada.\n"},
    {"path": "memory/empty.md", "content": "---\n---\n   \n"},
]


def test_claude_memory_files():
    eps = ClaudeAdapter.parse_episodes(CLAUDE_FILES)
    by_id = {e.id: e for e in eps}
    assert "empty" not in by_id  # empty body dropped
    assert set(by_id) == {"MEMORY", "project-x"}

    px = by_id["project-x"]
    assert px.source_type == "note"
    assert px.summary == "X launch plan"
    assert px.details == "Ship X on Pi Day. Owner: Ada."
    assert px.categories == ["project"]
    assert px.metadata["claude_type"] == "project"
    assert px.metadata["claude_name"] == "project-x"
    assert px.metadata["claude_path"] == "memory/project-x.md"
    assert px.metadata["claude_description"] == "X launch plan"

    idx = by_id["MEMORY"]
    assert idx.metadata["claude_role"] == "index"
    assert "Memory index" in idx.details


def test_claude_accepts_tuples_and_dict():
    from_tuples = ClaudeAdapter.parse_episodes([("a.md", "hello world")])
    assert len(from_tuples) == 1 and from_tuples[0].details == "hello world"
    from_dict = ClaudeAdapter.parse_episodes({"b.md": "another note"})
    assert len(from_dict) == 1 and from_dict[0].id == "b"


def test_claude_no_frontmatter():
    eps = ClaudeAdapter.parse_episodes([{"path": "notes.md", "content": "Just a plain note."}])
    assert eps[0].details == "Just a plain note."
    assert eps[0].summary == "Just a plain note."
    assert eps[0].categories == []


def test_openai_multimodal_parts_keep_text_only():
    conv = {"conversation_id": "c", "mapping": {"n": {"message": {
        "id": "m1", "author": {"role": "user"},
        "content": {"content_type": "multimodal_text",
                    "parts": ["look at this", {"content_type": "image_asset_pointer"}]},
        "create_time": 1700000100.0}}}}
    eps = OpenAIAdapter.parse_episodes(json.dumps(conv))
    assert len(eps) == 1
    assert eps[0].details == "look at this"  # non-string parts skipped, text kept


def test_openai_regeneration_branches_are_all_kept():
    # A regenerated answer leaves BOTH assistant variants in the mapping tree. v1 keeps
    # every visible turn (lossless superset); current_node path-following is a possible
    # follow-up. This pins the include-all behavior.
    conv = {"conversation_id": "c", "current_node": "v2", "mapping": {
        "u": {"message": {"id": "m_u", "author": {"role": "user"},
              "content": {"parts": ["q"]}, "create_time": 1.0}},
        "v1": {"message": {"id": "m_v1", "author": {"role": "assistant"},
               "content": {"parts": ["first answer"]}, "create_time": 2.0}},
        "v2": {"message": {"id": "m_v2", "author": {"role": "assistant"},
               "content": {"parts": ["regenerated answer"]}, "create_time": 3.0}},
    }}
    eps = OpenAIAdapter.parse_episodes(json.dumps(conv))
    assert [e.id for e in eps] == ["m_u", "m_v1", "m_v2"]


def test_claude_unclosed_frontmatter_falls_back_to_whole_content():
    eps = ClaudeAdapter.parse_episodes([{"path": "broken.md",
                                         "content": "---\nname: broken\nno closing fence"}])
    assert len(eps) == 1
    assert "name: broken" in eps[0].details  # nothing dropped
