import time

from app.storage.cache import FileCache


def test_cache_groups_variants_under_stable_identity(tmp_path, monkeypatch):
    from app.storage import cache as cache_module

    monkeypatch.setattr(cache_module.settings, "echryn_data_dir", str(tmp_path))
    monkeypatch.setattr(cache_module.settings, "echryn_cache_ttl_seconds", 3600)

    cache = FileCache()
    identity = "instagram-123"

    cache.put_variant(identity, "metadata-mm0-fdnone", {"id": "a", "status": "complete"})
    cache.put_variant(identity, "evidence-mm1-fdurls", {"id": "b", "status": "complete"})

    files = list((tmp_path / "cache").glob("*.json"))
    assert len(files) == 1
    assert cache.get_variant(identity, "metadata-mm0-fdnone")["id"] == "a"
    assert cache.get_variant(identity, "evidence-mm1-fdurls")["id"] == "b"


def test_cache_variant_ttl_is_independent(tmp_path, monkeypatch):
    from app.storage import cache as cache_module

    monkeypatch.setattr(cache_module.settings, "echryn_data_dir", str(tmp_path))
    monkeypatch.setattr(cache_module.settings, "echryn_cache_ttl_seconds", 10)

    cache = FileCache()
    identity = "instagram-123"
    cache.put_variant(identity, "old", {"id": "old"})
    cache.put_variant(identity, "fresh", {"id": "fresh"})

    path = cache._path(identity)
    document = cache._read_document(identity)
    document["variants"]["old"]["_cached_at"] = time.time() - 100
    cache._write_document(identity, document)

    assert cache.get_variant(identity, "old") is None
    assert cache.get_variant(identity, "fresh")["id"] == "fresh"
