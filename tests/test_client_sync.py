"""Sync client tests against MockTransport."""

from __future__ import annotations

import pytest

from yokatlas_py._lookup import LookupCache
from yokatlas_py.client import YokAtlasClient, _resolve_net_smart_fields
from yokatlas_py.exceptions import LookupError
from yokatlas_py.models import NetFilters, SearchFilters


def test_search_returns_search_page(client: YokAtlasClient) -> None:
    page = client.search()
    assert page.total_elements >= 1
    assert page.content[0].current.year == 2025
    assert len(page.content[0].history) == 3


def test_get_program_returns_single_program(client: YokAtlasClient) -> None:
    prog = client.get_program(105490029)
    assert prog is not None
    assert prog.kilavuz_kodu == 105490029
    assert prog.universite_adi.startswith("İSTANBUL")


def test_get_program_missing_returns_none(client: YokAtlasClient) -> None:
    assert client.get_program(999999999) is None


def test_get_program_validates_input(client: YokAtlasClient) -> None:
    with pytest.raises(ValueError):
        client.get_program("not-a-number")


def test_list_universities_uses_lookup_cache(client: YokAtlasClient) -> None:
    first = client.list_universities()
    second = client.list_universities()
    assert first == second
    assert any(u.universite_adi.startswith("BOĞAZİÇİ") for u in first)


def test_list_program_groups_and_cities(client: YokAtlasClient) -> None:
    progs = client.list_program_groups()
    cities = client.list_cities()
    assert any(p.birim_grup_adi == "Tıp" for p in progs)
    assert any(c.il_adi == "İSTANBUL" for c in cities)


def test_smart_search_resolves_string_to_id(client: YokAtlasClient) -> None:
    f = SearchFilters(universite="bogazici", program="bilgisayar", il="ankara")
    # Smart search should resolve and not raise; mock transport simply returns sample data
    page = client.search(f, smart_search=True)
    assert page is not None


def test_smart_search_unknown_university_raises(client: YokAtlasClient) -> None:
    f = SearchFilters(universite="zzzzzzzzzz")
    with pytest.raises(LookupError):
        client.search(f, smart_search=True)


def test_smart_search_disabled_keeps_string_unresolved(client: YokAtlasClient) -> None:
    # When smart_search is False, smart fields are NOT resolved; the API call
    # ignores them (server-side they don't exist) so search succeeds.
    f = SearchFilters(universite="boğaziçi")
    page = client.search(f, smart_search=False)
    assert page is not None


def test_filters_dict_input_is_accepted(client: YokAtlasClient) -> None:
    page = client.search({"puan_turu": "SAY"}, size=5)
    assert page.size == 5


def test_close_is_idempotent(client: YokAtlasClient) -> None:
    client.close()
    client.close()


def test_search_netler_broad_returns_page(client: YokAtlasClient) -> None:
    page = client.search_netler(NetFilters(puan_turu="SAY"))
    assert page.total_elements >= 1
    assert page.content[0].puan_turu == "SAY"
    assert page.source == "snapshot"


def test_search_netler_detail_returns_three_year_history(client: YokAtlasClient) -> None:
    page = client.search_netler(NetFilters(universite_id=173500, birim_grup_id=4001))
    assert page.total_elements == 3
    assert sorted(row.yil for row in page.content) == [2023, 2024, 2025]


def test_search_netler_smart_search_resolves_string_to_id(client: YokAtlasClient) -> None:
    f = NetFilters(universite="boğaziçi", program="bilgisayar mühendisliği")
    page = client.search_netler(f, smart_search=True)
    assert page is not None


def test_search_netler_smart_search_unknown_university_raises(client: YokAtlasClient) -> None:
    f = NetFilters(universite="zzzzzzzzzz")
    with pytest.raises(LookupError):
        client.search_netler(f, smart_search=True)


def test_search_netler_dict_input_is_accepted(client: YokAtlasClient) -> None:
    page = client.search_netler({"puan_turu": "SAY"}, size=5)
    assert page.size == 5


def test_resolve_net_smart_fields_resolves_university_and_program() -> None:
    cache = LookupCache(ttl=60)
    cache.populate(
        universities=[{"universiteId": 173500, "universiteAdi": "BOĞAZİÇİ ÜNİVERSİTESİ"}],
        program_groups=[{"birimGrupId": 4001, "birimGrupAdi": "Bilgisayar Mühendisliği", "puanTuru": "SAY"}],
        cities=[],
    )
    resolved = _resolve_net_smart_fields(NetFilters(universite="boğaziçi", program="bilgisayar mühendisliği"), cache)
    assert resolved.universite_id == 173500
    assert resolved.universite is None
    assert resolved.birim_grup_id == 4001
    assert resolved.program is None


def test_resolve_net_smart_fields_defaults_puan_turu_from_program() -> None:
    cache = LookupCache(ttl=60)
    cache.populate(
        universities=[],
        program_groups=[{"birimGrupId": 4001, "birimGrupAdi": "Bilgisayar Mühendisliği", "puanTuru": "SAY"}],
        cities=[],
    )
    resolved = _resolve_net_smart_fields(NetFilters(program="bilgisayar mühendisliği"), cache)
    assert resolved.puan_turu == "SAY"


def test_resolve_net_smart_fields_keeps_explicit_puan_turu() -> None:
    cache = LookupCache(ttl=60)
    cache.populate(
        universities=[],
        program_groups=[{"birimGrupId": 4001, "birimGrupAdi": "Bilgisayar Mühendisliği", "puanTuru": "SAY"}],
        cities=[],
    )
    resolved = _resolve_net_smart_fields(NetFilters(program="bilgisayar mühendisliği", puan_turu="EA"), cache)
    assert resolved.puan_turu == "EA"
