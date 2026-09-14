from services.blockchain import fetcher


def test_live_provider_empty_result_never_falls_back_to_synthetic(monkeypatch):
    monkeypatch.setattr(fetcher, "USE_DEMO_DATA", False)
    monkeypatch.setattr(fetcher, "_get_cached_transactions", lambda *_: None)
    monkeypatch.setattr(fetcher, "_fetch_from_api", lambda *_: [])
    monkeypatch.setattr(
        fetcher,
        "_get_demo_transactions",
        lambda *_: (_ for _ in ()).throw(AssertionError("synthetic fallback called")),
    )

    result = fetcher.fetch_transactions("0x" + "1" * 40, "ETH", object())

    assert result == []
