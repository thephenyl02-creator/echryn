from app.config import Settings


def test_default_evidence_retention_is_one_day():
    assert Settings.model_fields["echryn_cache_ttl_seconds"].default == 86400
    assert Settings.model_fields["echryn_frame_url_ttl_seconds"].default == 86400
