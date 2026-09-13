"""The standard-library YAML subset reader (``portable_memory/_yaml.py``)."""
from __future__ import annotations

from portable_memory._yaml import load_yaml


def test_scalars_core_schema_typing():
    doc = load_yaml(
        "a: 5\nb: -7\nc: +3\nd: 0.85\ne: 1.0\nf: 1e3\ng: true\nh: False\ni: null\nj: ~\nk:\n"
        "l: 2026-01-30\nm: 12:30\nn: 0x1F\no: yes\np: 1.\nq: .5\nr: \"7\"\ns: '0.5'\n"
    )
    assert doc["a"] == 5 and isinstance(doc["a"], int)
    assert doc["b"] == -7 and doc["c"] == 3
    assert doc["d"] == 0.85 and isinstance(doc["d"], float)
    assert doc["e"] == 1.0 and isinstance(doc["e"], float)
    assert doc["f"] == 1000.0
    assert doc["g"] is True and doc["h"] is False
    assert doc["i"] is None and doc["j"] is None and doc["k"] is None
    assert doc["l"] == "2026-01-30"          # dates stay strings
    assert doc["m"] == "12:30" and doc["n"] == "0x1F" and doc["o"] == "yes"
    assert doc["p"] == "1." and doc["q"] == ".5"   # outside the subset → strings
    assert doc["r"] == "7" and doc["s"] == "0.5"   # quoted → always strings


def test_quoted_strings_and_escapes():
    doc = load_yaml(
        'a: "line\\nbreak \\"q\\" \\u00e9 \\\\ end"\n'
        "b: 'it''s # not a comment'\n"
        'c: "has: colon" # comment\n'
        "d: don't stop  # apostrophe inside plain text\n"
        "e: \"unterminated\n"
    )
    assert doc["a"] == 'line\nbreak "q" é \\ end'
    assert doc["b"] == "it's # not a comment"
    assert doc["c"] == "has: colon"
    assert doc["d"] == "don't stop"
    assert doc["e"] == "unterminated"


def test_nested_mappings_sequences_and_same_indent_sequence():
    doc = load_yaml(
        "root:\n  child:\n    deep: 1\n  list:\n  - a\n  - b\n  objs:\n    - name: x\n      type: t\n    - name: y\n"
        "empty_map: {}\nempty_list: []\n"
    )
    assert doc["root"]["child"]["deep"] == 1
    assert doc["root"]["list"] == ["a", "b"]
    assert doc["root"]["objs"] == [{"name": "x", "type": "t"}, {"name": "y"}]
    assert doc["empty_map"] == {} and doc["empty_list"] == []


def test_sequence_items_with_inline_mapping_and_nested_blocks():
    doc = load_yaml("- id: 1\n  tags: [a, b]\n  meta:\n    k: v\n- id: 2\n-\n  id: 3\n- plain\n- [1, 2]\n")
    assert doc[0] == {"id": 1, "tags": ["a", "b"], "meta": {"k": "v"}}
    assert doc[1] == {"id": 2}
    assert doc[2] == {"id": 3}
    assert doc[3] == "plain"
    assert doc[4] == [1, 2]


def test_block_scalars_literal_folded_and_chomping():
    doc = load_yaml(
        "lit: |\n  one\n  two\n\nlit_strip: |-\n  a\n  b\n\n\nlit_keep: |+\n  a\n\n\nfold: >\n  one\n  two\n\n  three\n"
        "fold_strip: >-\n  x\n  y\nafter: 1\n"
    )
    assert doc["lit"] == "one\ntwo\n"
    assert doc["lit_strip"] == "a\nb"
    assert doc["lit_keep"] == "a\n\n\n"
    assert doc["fold"] == "one two\nthree\n"
    assert doc["fold_strip"] == "x y"
    assert doc["after"] == 1


def test_block_scalar_keeps_hash_and_extra_indentation():
    doc = load_yaml("s: |\n  # not a comment\n    indented more\n  end\n")
    assert doc["s"] == "# not a comment\n  indented more\nend\n"


def test_flow_collections_single_and_multi_line():
    doc = load_yaml(
        'a: {positive: 3, negative: 0, neutral: 2}\nb: ["x, y", \'z\', 4, true, null]\n'
        "c: [\n  1,\n  2,\n]\nd: {k: [1, {n: 2}], e: }\n"
    )
    assert doc["a"] == {"positive": 3, "negative": 0, "neutral": 2}
    assert doc["b"] == ["x, y", "z", 4, True, None]
    assert doc["c"] == [1, 2]
    assert doc["d"] == {"k": [1, {"n": 2}], "e": None}


def test_comments_documents_and_directives():
    doc = load_yaml("%YAML 1.2\n---\n# leading comment\na: 1 # trailing\n# between\nb: 2\n...\n")
    assert doc == {"a": 1, "b": 2}
    multi = load_yaml("---\n- 1\n---\n- 2\n")
    assert multi == [[1], [2]]
    assert load_yaml("") is None
    assert load_yaml("# only a comment\n") is None


def test_multi_line_plain_scalar_and_url_values():
    doc = load_yaml("s: first part\n  second part\nu: https://example.com/a:b\nnext: 1\n")
    assert doc["s"] == "first part second part"
    assert doc["u"] == "https://example.com/a:b"
    assert doc["next"] == 1


def test_garbage_degrades_to_strings_not_exceptions():
    for text in ("just text", "[unbalanced", "{a: [1,", ": weird", "- - -", "\t\ttabs: 1", "a:\n\tb: 1"):
        load_yaml(text)  # must not raise
    assert load_yaml("just text") == "just text"
    assert load_yaml("[unbalanced") == ["unbalanced"]          # lenient: an unclosed flow list still yields its items
    deep = load_yaml("[" * 500)                                 # nesting is capped; the remainder degrades to a string
    for _ in range(64):
        assert isinstance(deep, list) and len(deep) == 1
        deep = deep[0]
    assert isinstance(deep, (list, str))
