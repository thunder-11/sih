"""Network-aware wallet validation without provider calls."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from Crypto.Hash import keccak


EVM_CHAINS = ("ETH", "BSC", "POLYGON")
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


@dataclass(frozen=True, slots=True)
class AddressValidation:
    valid: bool
    canonical_address: str | None
    candidates: tuple[str, ...]
    checksum_state: str
    reason: str | None = None
    synthetic_fixture: bool = False


def _base58check(value: str, expected_prefix: int | None = None) -> bool:
    try:
        number = 0
        for char in value:
            number = number * 58 + BASE58_ALPHABET.index(char)
        decoded = number.to_bytes((number.bit_length() + 7) // 8, "big")
        decoded = b"\0" * (len(value) - len(value.lstrip("1"))) + decoded
    except (ValueError, OverflowError):
        return False
    if len(decoded) < 5 or (expected_prefix is not None and decoded[0] != expected_prefix):
        return False
    payload, checksum = decoded[:-4], decoded[-4:]
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] == checksum


def _bech32_polymod(values: list[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for value in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(generators):
            if (top >> index) & 1:
                chk ^= generator
    return chk


def _bech32_valid(value: str) -> bool:
    if value.lower() != value and value.upper() != value:
        return False
    value = value.lower()
    if not value.startswith("bc1") or len(value) > 90:
        return False
    separator = value.rfind("1")
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    try:
        data = [charset.index(char) for char in value[separator + 1:]]
    except ValueError:
        return False
    hrp = value[:separator]
    expanded = [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]
    return len(data) >= 6 and _bech32_polymod(expanded + data) in {1, 0x2BC830A3}


def _evm_checksum_valid(value: str) -> bool:
    body = value[2:]
    if body.islower() or body.isupper():
        return True
    digest = keccak.new(digest_bits=256, data=body.lower().encode("ascii")).hexdigest()
    return all(not char.isalpha() or (char.isupper() == (int(digest[index], 16) >= 8))
               for index, char in enumerate(body))


def validate_wallet(address: str, chain: str | None = None, *, fixture_mode: bool = False) -> AddressValidation:
    raw = address.strip()
    network = chain.strip().upper() if chain else None
    if network and network not in {"BTC", "ETH", "TRON", "BSC", "POLYGON"}:
        return AddressValidation(False, None, (), "invalid", "Unsupported network")
    if fixture_mode and re.fullmatch(r"[A-Za-z0-9_:-]{10,160}", raw) and any(
        marker in raw.upper() for marker in ("DEMO", "VICTIM", "MULE", "MIXER", "BRIDGE", "DEP_")
    ):
        return AddressValidation(True, raw, (network,) if network else (), "fixture", synthetic_fixture=True)
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", raw):
        candidates = EVM_CHAINS
        if network and network not in candidates:
            return AddressValidation(False, None, candidates, "invalid", "Address does not match the selected network")
        if not _evm_checksum_valid(raw):
            return AddressValidation(False, None, candidates, "invalid", "Invalid EVM checksum")
        checksum = "not_present" if raw[2:].islower() or raw[2:].isupper() else "valid"
        return AddressValidation(True, raw.lower(), (network,) if network else candidates, checksum)
    if raw.startswith("T") and len(raw) == 34:
        valid = _base58check(raw, expected_prefix=0x41)
        return AddressValidation(valid and network in {None, "TRON"}, raw if valid else None, ("TRON",),
                                 "valid" if valid else "invalid", None if valid else "Invalid TRON checksum")
    if raw.lower().startswith("bc1"):
        valid = _bech32_valid(raw)
        return AddressValidation(valid and network in {None, "BTC"}, raw.lower() if valid else None, ("BTC",),
                                 "valid" if valid else "invalid", None if valid else "Invalid Bitcoin checksum")
    if raw.startswith(("1", "3")):
        valid = _base58check(raw)
        return AddressValidation(valid and network in {None, "BTC"}, raw if valid else None, ("BTC",),
                                 "valid" if valid else "invalid", None if valid else "Invalid Bitcoin checksum")
    return AddressValidation(False, None, (), "invalid", "Unrecognized wallet encoding")
