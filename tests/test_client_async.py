"""Async client tests against MockTransport."""

from __future__ import annotations

import pytest

from yokatlas_py.client import AsyncYokAtlasClient
from yokatlas_py.exceptions import LookupError
from yokatlas_py.models import NetFilters, SearchFilters


@pytest.mark.asyncio
async def test_async_search(async_client: AsyncYokAtlasClient) -> None:
    page = await async_client.search()
    assert page.total_elements >= 1
    assert page.content[0].kilavuz_kodu == 105490029


@pytest.mark.asyncio
async def test_async_get_program(async_client: AsyncYokAtlasClient) -> None:
    prog = await async_client.get_program(105490029)
    assert prog is not None
    assert prog.kilavuz_kodu == 105490029


@pytest.mark.asyncio
async def test_async_get_program_missing(async_client: AsyncYokAtlasClient) -> None:
    assert await async_client.get_program(999999999) is None


@pytest.mark.asyncio
async def test_async_list_universities(async_client: AsyncYokAtlasClient) -> None:
    unis = await async_client.list_universities()
    assert any(u.universite_adi.startswith("ORTA DOĞU") for u in unis)


@pytest.mark.asyncio
async def test_async_smart_search(async_client: AsyncYokAtlasClient) -> None:
    page = await async_client.search(SearchFilters(universite="boğaziçi"), smart_search=True)
    assert page is not None


@pytest.mark.asyncio
async def test_async_smart_search_unknown(async_client: AsyncYokAtlasClient) -> None:
    with pytest.raises(LookupError):
        await async_client.search(SearchFilters(universite="zzzzzz"), smart_search=True)


@pytest.mark.asyncio
async def test_async_close_idempotent(async_client: AsyncYokAtlasClient) -> None:
    await async_client.aclose()
    await async_client.aclose()


@pytest.mark.asyncio
async def test_async_search_netler_broad(async_client: AsyncYokAtlasClient) -> None:
    page = await async_client.search_netler(NetFilters(puan_turu="SAY"))
    assert page.total_elements >= 1
    assert page.content[0].puan_turu == "SAY"


@pytest.mark.asyncio
async def test_async_search_netler_detail_history(async_client: AsyncYokAtlasClient) -> None:
    page = await async_client.search_netler(NetFilters(universite_id=173500, birim_grup_id=4001))
    assert page.total_elements == 3
    assert sorted(row.yil for row in page.content) == [2023, 2024, 2025]


@pytest.mark.asyncio
async def test_async_search_netler_smart_search(async_client: AsyncYokAtlasClient) -> None:
    page = await async_client.search_netler(NetFilters(universite="boğaziçi"), smart_search=True)
    assert page is not None


@pytest.mark.asyncio
async def test_async_search_netler_smart_search_unknown(async_client: AsyncYokAtlasClient) -> None:
    with pytest.raises(LookupError):
        await async_client.search_netler(NetFilters(universite="zzzzzz"), smart_search=True)
