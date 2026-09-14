from app.cache.keys import registry_cache_key, transaction_cache_key
from app.cache.backend import JsonCache


def test_transaction_cache_isolated_by_chain_wallet_provider_and_case():
    base = dict(chain="ETH", wallet_address="0xabc", provider="etherscan", case_id="case-1")
    canonical = transaction_cache_key(**base)
    assert canonical != transaction_cache_key(**{**base, "chain": "BSC"})
    assert canonical != transaction_cache_key(**{**base, "wallet_address": "0xdef"})
    assert canonical != transaction_cache_key(**{**base, "provider": "rpc"})
    assert canonical != transaction_cache_key(**{**base, "case_id": "case-2"})
    assert canonical != transaction_cache_key(**base, query={"cursor": "next"})
    assert "0xabc" not in canonical


def test_registry_cache_isolated_by_version_and_chain():
    assert registry_cache_key(registry="vasp", version="v1", chain="ETH") != registry_cache_key(
        registry="vasp", version="v2", chain="ETH"
    )
    assert registry_cache_key(registry="vasp", version="v1", chain="ETH") != registry_cache_key(
        registry="vasp", version="v1", chain="TRON"
    )


def test_json_cache_uses_ttl_and_round_trips_without_becoming_authoritative():
    class FakeRedis:
        values = {}
        ttl = None

        def get(self, key):
            return self.values.get(key)

        def setex(self, key, ttl_seconds, value):
            self.ttl = ttl_seconds
            self.values[key] = value.encode()

        def delete(self, key):
            self.values.pop(key, None)

    client = FakeRedis()
    cache = JsonCache(client)
    cache.set("isolated", {"coverage": "complete", "items": [1]}, ttl_seconds=60)
    assert client.ttl == 60
    assert cache.get("isolated") == {"coverage": "complete", "items": [1]}
    cache.delete("isolated")
    assert cache.get("isolated") is None
