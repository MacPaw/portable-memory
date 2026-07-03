"""Coverage expansion: the gaps the launch audit found untested.

- ALL 15 record kinds round-trip (the base suite exercises only episode/entity/edge).
- Every exported record validates against the shared JSON Schemas (drift net).
- Incremental (--since) semantics: delta-filtered kinds, chunks-follow-parent,
  structural kinds always full, tombstones/audit since-filtered.
- Evidence Pack export; redact tombstones survive the wire with their op intact.

Self-contained (own FullStore) so it merges cleanly next to every open PR.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from portable_memory import (BundleExporter, BundleImporter, BundleValidator,
                             ExportMode, PortableMemoryStore, StoreInfo)
from portable_memory.records import (PortableCategory, PortableChunk, PortableCommunity,
                                     PortableContext, PortableCore, PortableEdge,
                                     PortableEntity, PortableEpisode, PortableEpisodeLink,
                                     PortableFact, PortableFactLink, PortablePreference,
                                     PortableProcedure, PortableResource, PortableSecretRef)
from portable_memory.tombstone import (DerivedRefs, PortableAuditRecord, Tombstone,
                                       TombstoneOp)

T_OLD = datetime(2024, 1, 1, tzinfo=timezone.utc)
T_NEW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CUTOFF = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _episode(id_, ts):
    return PortableEpisode(
        id=id_, event_time=ts, mention_time=ts, ingestion_time=ts, source_type="note",
        actors=["a"], summary="s", details="d", sensitivity="low", metadata={"k": "v"},
        categories=["c"], importance=0.5, confidence=0.7, lifecycle_state="HOT",
        extraction_state="done", access_count=1, pinned=True, vault_refs=["vault_1"])


class FullStore(PortableMemoryStore):
    """A store holding one record of EVERY kind, keyed for merge-by-id/natural-key."""

    def __init__(self):
        self.episodes = {}
        self.entities = {}
        self.edges = {}
        self.facts = {}
        self.fact_links = {}
        self.episode_links = {}
        self.resources = {}
        self.chunks = {}
        self.cores = {}
        self.procedures = {}
        self.contexts = {}
        self.communities = {}
        self.categories = {}
        self.preferences = {}
        self.secret_refs = {}
        self.tombstones = []
        self.audit = []
        self.applied_ops: list[str] = []

    @classmethod
    def seeded(cls, episode_ts=T_NEW, include_audit=True):
        s = cls()
        e = _episode("ep_1", episode_ts)
        s.episodes[e.id] = e
        s.entities["ent_1"] = PortableEntity(id="ent_1", entity_type="person",
                                             canonical_name="Ada", aliases=["A"],
                                             summary="s", sensitivity="low", updated_at=T_NEW)
        s.edges["edge_1"] = PortableEdge(id="edge_1", src_entity_id="ent_1",
                                         dst_entity_id="ent_1", edge_type="self",
                                         t_valid_from=T_NEW, ingestion_time=T_NEW,
                                         confidence=0.9, evidence_episode_ids=["ep_1"])
        s.facts["fact_1"] = PortableFact(id="fact_1", episode_id="ep_1", subject="Ada",
                                         predicate="leads", obj="X", text="Ada leads X",
                                         t_valid_from=T_NEW, confidence=0.9, importance=0.5,
                                         created_at=T_NEW)
        s.fact_links[("fact_1", "fact_1")] = PortableFactLink(
            src_fact_id="fact_1", dst_fact_id="fact_1", link_type="refines", created_at=T_NEW)
        s.episode_links[("ep_1", "ep_1")] = PortableEpisodeLink(
            src_episode_id="ep_1", dst_episode_id="ep_1", link_type="related", weight=0.5)
        s.resources["res_1"] = PortableResource(id="res_1", uri="file:///x",
                                                mime_type="text/plain",
                                                content_hash="sha256:ab", title="t",
                                                summary="s", created=T_NEW, modified=T_NEW)
        s.chunks["chunk_1"] = PortableChunk(id="chunk_1", resource_id="res_1", position=0,
                                            text="chunk text", sensitivity="low")
        s.cores["human"] = PortableCore(id="human", content="profile", char_budget=100,
                                        version=1)
        s.procedures["proc_1"] = PortableProcedure(id="proc_1", name="n",
                                                   trigger_pattern="p", steps=["a"],
                                                   success_count=1, failure_count=0,
                                                   enabled=True)
        s.contexts["ctx_1"] = PortableContext(id="ctx_1", label="l", archived=False,
                                              created_at=T_NEW)
        s.communities["com_1"] = PortableCommunity(id="com_1", label="l", summary="s",
                                                   member_entity_ids=["ent_1"])
        s.categories["prefs"] = PortableCategory(name="prefs", description="d")
        s.preferences["theme"] = PortablePreference(key="theme", value="dark")
        s.secret_refs["sec_1"] = PortableSecretRef(id="sec_1", label="api key",
                                                   sensitivity="high", category="cred",
                                                   preview="…last4",
                                                   encryption_metadata="aes-256-gcm",
                                                   created_at=T_NEW)
        s.tombstones.append(Tombstone(id="tomb_1", op=TombstoneOp.DELETE,
                                      target_kind="episode", target_id="ep_gone",
                                      deleted_at=T_NEW, actor="user",
                                      derived=DerivedRefs(), reason="erasure"))
        if include_audit:
            s.audit.append(PortableAuditRecord(ts=T_NEW, actor="user", op="delete",
                                               target_id="ep_gone", reason="erasure"))
        return s

    def store_info(self):
        return StoreInfo(generator="coverage/1.0", schema_version=1)

    # export readers
    def export_episodes(self): return list(self.episodes.values())
    def export_entities(self): return list(self.entities.values())
    def export_edges(self): return list(self.edges.values())
    def export_facts(self): return list(self.facts.values())
    def export_fact_links(self): return list(self.fact_links.values())
    def export_episode_links(self): return list(self.episode_links.values())
    def export_resources(self): return list(self.resources.values())
    def export_chunks(self): return list(self.chunks.values())
    def export_core_blocks(self): return list(self.cores.values())
    def export_procedures(self): return list(self.procedures.values())
    def export_contexts(self): return list(self.contexts.values())
    def export_communities(self): return list(self.communities.values())
    def export_categories(self): return list(self.categories.values())
    def export_preferences(self): return list(self.preferences.values())
    def export_secret_refs(self): return list(self.secret_refs.values())
    def export_tombstones(self, since=None):
        return [t for t in self.tombstones if since is None or t.deleted_at >= since]
    def export_audit_log(self, since=None):
        return [a for a in self.audit if since is None or a.ts >= since]

    # import writers
    def tombstoned_target_ids(self): return {t.target_id for t in self.tombstones}
    def apply_tombstone(self, t):
        self.applied_ops.append(t.op.value)
        self.tombstones.append(t)
    def import_episode(self, e, ext=None): self.episodes[e.id] = e
    def import_entity(self, e): self.entities[e.id] = e
    def import_edge(self, e): self.edges[e.id] = e
    def import_fact(self, f): self.facts[f.id] = f
    def import_fact_link(self, l): self.fact_links[(l.src_fact_id, l.dst_fact_id)] = l
    def import_episode_link(self, l): self.episode_links[(l.src_episode_id, l.dst_episode_id)] = l
    def import_resource(self, r): self.resources[r.id] = r
    def import_chunk(self, c): self.chunks[c.id] = c
    def import_core_block(self, c): self.cores[c.id] = c
    def import_procedure(self, p): self.procedures[p.id] = p
    def import_context(self, c): self.contexts[c.id] = c
    def import_community(self, c): self.communities[c.id] = c
    def import_category(self, c): self.categories[c.name] = c
    def import_preference(self, p): self.preferences[p.key] = p
    def import_secret_ref(self, r): self.secret_refs[r.id] = r


ALL_KINDS = ["episode", "entity", "edge", "fact", "factLink", "episodeLink", "resource",
             "chunk", "core", "procedure", "context", "community", "category",
             "preference", "secretRef"]


def _data_files(root):
    out = {}
    for sub in ("items", "audit"):
        d = Path(root) / sub
        if d.is_dir():
            for f in sorted(d.iterdir()):
                out[f"{sub}/{f.name}"] = f.read_bytes()
    out["CHECKSUMS"] = (Path(root) / "CHECKSUMS").read_bytes()
    return out


def test_all_fifteen_kinds_round_trip_byte_identically():
    # No audit rows here: the audit trail is host-owned — it is WRITTEN on export but
    # never imported into the store (pinned separately below) — so a bundle carrying a
    # log could never re-export byte-identically.
    src = FullStore.seeded(include_audit=False)
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        m = BundleExporter().export(src, d1)
        # Every kind exported exactly once, plus the tombstone stream.
        for kind in ALL_KINDS:
            assert m.counts.get(kind) == 1, f"{kind} missing from manifest counts"
        assert m.counts.get("tombstone") == 1
        assert BundleValidator().validate(d1).ok

        dst = FullStore()
        report = BundleImporter().import_bundle(dst, d1)
        for kind in ALL_KINDS:
            assert report.applied.get(kind) == 1, f"{kind} not applied on import"

        # The strongest equality check: the re-export is byte-identical.
        BundleExporter().export(dst, d2)
        assert _data_files(d1) == _data_files(d2)


def test_audit_log_is_exported_but_not_imported_into_the_store():
    # The portable trail travels in the bundle for governance/Evidence-Pack purposes;
    # the IMPORTER does not replay it into the receiving store (the host owns its own
    # mutation history). This pins that asymmetry as intended behavior.
    src = FullStore.seeded(include_audit=True)
    with tempfile.TemporaryDirectory() as d:
        m = BundleExporter().export(src, d)
        assert m.counts.get("audit") == 1
        assert (Path(d) / "audit/log.jsonl").is_file()
        dst = FullStore()
        BundleImporter().import_bundle(dst, d)
        assert dst.audit == []


def test_exported_records_validate_against_shared_schemas():
    jsonschema = pytest.importorskip("jsonschema")
    schemas_dir = Path(__file__).resolve().parents[1] / "Schemas"

    def validator(name):
        return jsonschema.Draft202012Validator(
            json.loads((schemas_dir / f"{name}.schema.json").read_text()))

    with tempfile.TemporaryDirectory() as d:
        BundleExporter().export(FullStore.seeded(), d)
        checked = 0
        # Every item kind with a schema must validate line-by-line.
        for path in sorted((Path(d) / "items").iterdir()):
            kind = path.name.removesuffix(".jsonl")
            v = validator(kind)
            for line in path.read_text().splitlines():
                if line.strip():
                    v.validate(json.loads(line))
                    checked += 1
        for name, rel in (("tombstone", "audit/tombstones.jsonl"), ("log", "audit/log.jsonl")):
            v = validator(name)
            for line in (Path(d) / rel).read_text().splitlines():
                if line.strip():
                    v.validate(json.loads(line))
                    checked += 1
        validator("manifest").validate(json.loads((Path(d) / "manifest.json").read_text()))
        assert checked >= len(ALL_KINDS) + 2, "expected every kind + audit streams checked"


def test_incremental_since_semantics():
    src = FullStore.seeded(episode_ts=T_NEW)
    # An OLD episode, an OLD resource with its own chunk, an OLD tombstone + audit row —
    # all before the cutoff and thus outside the delta.
    old_ep = _episode("ep_old", T_OLD)
    src.episodes[old_ep.id] = old_ep
    src.resources["res_old"] = PortableResource(id="res_old", uri="file:///old",
                                                mime_type="text/plain", content_hash="sha256:cd",
                                                title="t", summary="s", created=T_OLD,
                                                modified=T_OLD)
    src.chunks["chunk_old"] = PortableChunk(id="chunk_old", resource_id="res_old",
                                            position=0, text="old", sensitivity="low")
    src.tombstones.insert(0, Tombstone(id="tomb_old", op=TombstoneOp.DELETE,
                                       target_kind="episode", target_id="ep_ancient",
                                       deleted_at=T_OLD, actor="user",
                                       derived=DerivedRefs(), reason="old"))
    src.audit.insert(0, PortableAuditRecord(ts=T_OLD, actor="user", op="delete",
                                            target_id="ep_ancient", reason="old"))

    with tempfile.TemporaryDirectory() as d:
        m = BundleExporter().export(src, d, mode=ExportMode.INCREMENTAL, since=CUTOFF)
        assert m.export_mode == ExportMode.INCREMENTAL and m.since is not None

        episodes = (Path(d) / "items/episode.jsonl").read_text()
        assert '"id":"ep_1"' in episodes and "ep_old" not in episodes

        resources = (Path(d) / "items/resource.jsonl").read_text()
        assert "res_1" in resources and "res_old" not in resources
        # Chunks follow their parent resource into the delta.
        chunks = (Path(d) / "items/chunk.jsonl").read_text()
        assert "chunk_1" in chunks and "chunk_old" not in chunks

        # Structural kinds are ALWAYS full, even incremental.
        assert "ent_1" in (Path(d) / "items/entity.jsonl").read_text()
        assert "edge_1" in (Path(d) / "items/edge.jsonl").read_text()
        assert "theme" in (Path(d) / "items/preference.jsonl").read_text()

        # Tombstones and audit are since-filtered.
        tombs = (Path(d) / "audit/tombstones.jsonl").read_text()
        assert "tomb_1" in tombs and "tomb_old" not in tombs
        audit = (Path(d) / "audit/log.jsonl").read_text()
        assert '"targetID":"ep_gone"' in audit and audit.count("\n") == 1


def test_evidence_pack_export():
    src = FullStore.seeded()
    with tempfile.TemporaryDirectory() as d:
        m = BundleExporter().export_evidence_pack(src, d)
        for rel in ("audit/log.jsonl", "audit/tombstones.jsonl", "provenance/edges.jsonl"):
            assert (Path(d) / rel).is_file(), f"{rel} missing from Evidence Pack"
        assert "evidence-pack" in m.capabilities and "proof-of-deletion" in m.capabilities
        assert m.counts.get("tombstone") == 1 and m.counts.get("provenanceEdge") == 1
        assert BundleValidator().validate(d).ok


def test_redact_tombstone_survives_the_wire_with_op_intact():
    src = FullStore.seeded()
    src.tombstones.append(Tombstone(id="tomb_r", op=TombstoneOp.REDACT,
                                    target_kind="episode", target_id="ep_redact_me",
                                    deleted_at=T_NEW, actor="user",
                                    derived=DerivedRefs(), reason="GDPR Art. 17"))
    with tempfile.TemporaryDirectory() as d:
        BundleExporter().export(src, d)
        line = next(l for l in (Path(d) / "audit/tombstones.jsonl").read_text().splitlines()
                    if "tomb_r" in l)
        assert '"op":"redact"' in line

        dst = FullStore()
        BundleImporter().import_bundle(dst, d)
        # The receiver hook saw the redact op (content-purge semantics are the host's
        # obligation per spec §5 — this pins that the op arrives intact).
        assert "redact" in dst.applied_ops
        redacted = next(t for t in dst.tombstones if t.id == "tomb_r")
        assert redacted.op is TombstoneOp.REDACT
