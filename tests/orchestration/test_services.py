"""real_services() binds every tool to the teammates' modules, without importing them for real."""

import sys
import types
from decimal import Decimal

import claimsense.mcp_servers as mcp_pkg
from claimsense.agents.services import real_calculate, real_services

BINDINGS = {
    "policy_kb": ["policy_search", "get_clause"],
    "claims_db": [
        "get_policy",
        "claim_history",
        "settle_claim",
        "record_repudiation",
        "record_history",
    ],
    "tariff": ["tariff_range"],
}


def _fake_modules(monkeypatch):
    fakes = {}
    for mod, names in BINDINGS.items():
        fake = types.ModuleType(f"claimsense.mcp_servers.{mod}")
        for n in names:
            setattr(fake, n, lambda *a, _n=n, **k: _n)
        fakes[mod] = fake
    fakes["approvals"] = types.ModuleType("claimsense.mcp_servers.approvals")
    fakes["approvals"].senior_threshold_inr = lambda: Decimal("123456")
    for mod, fake in fakes.items():
        monkeypatch.setitem(sys.modules, f"claimsense.mcp_servers.{mod}", fake)
        monkeypatch.setattr(mcp_pkg, mod, fake, raising=False)
    return fakes


# check=False: these tests swap in fake tool modules, which the L15 tool pins rightly refuse.
# The pins themselves are tested in tests/security/test_tool_pins.py.
def test_real_services_binds_each_tool_to_its_owner_module(monkeypatch):
    fakes = _fake_modules(monkeypatch)
    svc = real_services(check=False)
    for mod, names in BINDINGS.items():
        for n in names:
            assert getattr(svc, n) is getattr(fakes[mod], n), n
    assert svc.calculate is real_calculate


def test_real_services_takes_the_shared_senior_threshold(monkeypatch):
    _fake_modules(monkeypatch)
    assert real_services(check=False).senior_threshold == Decimal("123456")


def test_registry_exposes_only_real_bindings(monkeypatch):
    fakes = _fake_modules(monkeypatch)
    reg = real_services(check=False).registry()
    assert reg["settle_claim"] is fakes["claims_db"].settle_claim
    assert reg["policy_search"] is fakes["policy_kb"].policy_search
