# Net Sihirbazı (netler API) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-class support for YÖK Atlas's new Net Sihirbazı (`POST /api/netler/search`) — "son yerleşen kişinin netleri" — as a `search_netler()` method on both clients, mirroring the existing `search()` surface.

**Architecture:** Thin addition parallel to the existing tercih-kılavuzu wrapper: new `Net`/`NetFilters` pydantic models, one new endpoint constant + method pair on `YokAtlasClient`/`AsyncYokAtlasClient`, a module-level convenience function, and reuse of the existing `LookupCache` for smart (name→id) resolution — no new HTTP fetchers, since `birimGrupId`/`universiteId` share the same ID namespace as `/api/tercih-kilavuz/*` (verified live).

**Tech Stack:** Python 3.10+, pydantic v2, httpx, pytest + pytest-asyncio (mock transport via `httpx.MockTransport`, no real network calls in the test suite).

## Global Constraints

- Follow the design in `docs/superpowers/specs/2026-07-23-net-sihirbazi-design.md` exactly — endpoint path, request/response shapes, and behavior notes documented there come from live API inspection, not guesses.
- `universite_turu` on `NetFilters` is restricted to `Literal["DEVLET", "VAKIF"]`, matching the existing `SearchFilters.universite_turu` restriction (other values like KKTC/Yurtdışı are out of scope).
- No new HTTP fetcher/lookup endpoints — `NetFilters.universite`/`.program` smart resolution reuses the existing `LookupCache` populated from `/api/tercih-kilavuz/universiteler` and `/universite-programlar`.
- `sortBy`/`direction` are not exposed as functional parameters on `search_netler` (the live API accepts but ignores them — see spec "Behavior notes").
- All new tests use the existing `httpx.MockTransport`-based fixtures in `tests/conftest.py` — no real network calls.
- Match existing code style: `from __future__ import annotations`, full type hints, alias-generator-based camelCase (`_model_config()` / `to_camel`), Turkish domain field names (`universite`, `program`, `birim_grup_id`, etc.) per existing `SearchFilters`/`Program`.

---

### Task 1: `Net` and `NetFilters` models

**Files:**
- Modify: `yokatlas_py/models.py`
- Test: `tests/test_models.py`
- Modify (fixtures used by the test): `tests/conftest.py`

**Interfaces:**
- Produces: `yokatlas_py.models.Net` (pydantic model, fields below), `yokatlas_py.models.NetFilters` (pydantic model with `.to_payload() -> dict[str, Any]`), `SearchPage.source: str | None` (new optional field on the existing generic `SearchPage[T]`).
- `Net` fields (all via `_model_config()` alias generator, camelCase on the wire): `yil: int`, `kilavuz_kodu: int`, `puan_turu: str`, `katsayi: float | None`, `taban_puan: float | None`, `obp: float | None`, `tyt_trk_net: float | None`, `tyt_sos_net: float | None`, `tyt_mat_net: float | None`, `tyt_fen_net: float | None`, `ayt_mat_net: float | None`, `ayt_fiz_net: float | None`, `ayt_kim_net: float | None`, `ayt_bio_net: float | None`, `ayt_tde_net: float | None`, `ayt_trh1_net: float | None`, `ayt_cog1_net: float | None`, `ayt_trh2_net: float | None`, `ayt_cog2_net: float | None`, `ayt_fel_net: float | None`, `ayt_din_net: float | None`, `ydt_ydil_net: float | None`, `universite_id: int`, `universite_adi: str`, `birim_grup_id: int | None`, `birim_grup_adi: str | None`, `birim_id: int | None`, `birim_adi: str`, `birim_turu_id: int | None`, `birim_turu_adi: Literal["LISANS", "ONLISANS"]`, `universite_turu: Literal["DEVLET", "VAKIF", "VAKIF MYO"]`.
- `NetFilters` fields: `puan_turu: PuanTuru | None`, `universite_id: int | None`, `birim_grup_id: int | None`, `birim_turu_id: int | None`, `universite_turu: Literal["DEVLET", "VAKIF"] | None`, `yil: int | None`, `katsayi: float | None`, `universite: str | None`, `program: str | None`. `extra="forbid"`.

- [ ] **Step 1: Add the shared ÖNLİSANS-spelling normalization helper**

The API sends `"ÖNLISANS"` (Turkish dotted Ö) for both `Program` and the new `Net` model. Extract the existing inline normalization in `Program._group_yearly` (in `yokatlas_py/models.py`) into a shared module-level function so `Net` can reuse it instead of duplicating the loop.

In `yokatlas_py/models.py`, find this block inside `Program._group_yearly` (currently around line 216-220):

```python
        # The API sends "ÖNLISANS" (Turkish dotted Ö); normalize to the ASCII
        # canonical value the model exposes. Accepts either key spelling.
        for key in ("birimTuruAdi", "birim_turu_adi"):
            if data.get(key) == "ÖNLISANS":
                data[key] = "ONLISANS"
```

Replace it with a call to a new helper, and add that helper just above the `Program` class (right after the `_build_yearly_stats` function, before `class Program(BaseModel):`):

```python
def _normalize_onlisans_spelling(data: dict[str, Any]) -> dict[str, Any]:
    """The API sends "ÖNLISANS" (Turkish dotted Ö); normalize to the ASCII
    canonical value the models expose. Accepts either key spelling."""
    for key in ("birimTuruAdi", "birim_turu_adi"):
        if data.get(key) == "ÖNLISANS":
            data[key] = "ONLISANS"
    return data
```

And the replaced line inside `Program._group_yearly`:

```python
        data = _normalize_onlisans_spelling(data)
```

- [ ] **Step 2: Add `source` field to `SearchPage`**

In `yokatlas_py/models.py`, in the `SearchPage` class, add one field after `yil`:

```python
class SearchPage(BaseModel, Generic[T]):
    model_config = _model_config()

    content: list[T]
    total_elements: int
    total_pages: int
    size: int
    number: int
    first: bool
    last: bool
    number_of_elements: int
    empty: bool
    yil: int | None = None
    source: str | None = None
```

- [ ] **Step 3: Write the failing tests for `Net` and `SearchPage.source`**

First add a sample netler row + response builder to `tests/conftest.py` (used by this task and Tasks 2-4). Add near `SAMPLE_PROGRAM_RAW`/`make_search_response` (after `make_search_response`, before `SAMPLE_UNIVERSITIES`):

```python
SAMPLE_NET_ROW: dict[str, Any] = {
    "yil": 2025,
    "kilavuzKodu": 102210277,
    "puanTuru": "SAY",
    "katsayi": 0.12,
    "tabanPuan": 533.05003,
    "obp": 473.958,
    "tytTrkNet": 33.75,
    "tytSosNet": 16.25,
    "tytMatNet": 38.75,
    "tytFenNet": 20.0,
    "aytMatNet": 38.75,
    "aytFizNet": 12.75,
    "aytKimNet": 11.75,
    "aytBioNet": 13.0,
    "universiteId": 173500,
    "universiteAdi": "BOĞAZİÇİ ÜNİVERSİTESİ",
    "birimGrupId": 4001,
    "birimGrupAdi": "Bilgisayar Mühendisliği",
    "birimId": 150153,
    "birimAdi": "Bilgisayar Mühendisliği (İngilizce)",
    "birimTuruId": 46,
    "birimTuruAdi": "LISANS",
    "universiteTuru": "DEVLET",
}


def make_net_search_response(items: list[dict[str, Any]] | None = None, *, total: int | None = None, size: int = 20, page: int = 0) -> dict[str, Any]:
    items = items if items is not None else [SAMPLE_NET_ROW]
    total = total if total is not None else len(items)
    total_pages = max(1, (total + size - 1) // size) if size else 1
    return {
        "content": items,
        "empty": len(items) == 0,
        "first": page == 0,
        "last": page >= total_pages - 1,
        "number": page,
        "numberOfElements": len(items),
        "size": size,
        "totalElements": total,
        "totalPages": total_pages,
        "source": "snapshot",
    }
```

Note: `universiteId` 173500 and `birimGrupId` 4001 intentionally match the existing `SAMPLE_UNIVERSITIES`/`SAMPLE_PROGRAMS` entries (BOĞAZİÇİ ÜNİVERSİTESİ / Bilgisayar Mühendisliği) so later smart-search tests resolve against the same fixture data.

Now add to `tests/test_models.py` (add `Net, NetFilters` to the existing `from yokatlas_py.models import ...` line, and add `SAMPLE_NET_ROW, make_net_search_response` to the existing `from .conftest import ...` line):

```python
def test_net_model_parses_say_fields() -> None:
    net = Net.model_validate(SAMPLE_NET_ROW)
    assert net.kilavuz_kodu == 102210277
    assert net.universite_adi == "BOĞAZİÇİ ÜNİVERSİTESİ"
    assert net.birim_turu_adi == "LISANS"
    assert net.ayt_fiz_net == pytest.approx(12.75)
    assert net.ayt_tde_net is None  # SAY rows don't carry SÖZ-only fields


def test_net_model_normalizes_onlisans_turkish_spelling() -> None:
    raw = {**SAMPLE_NET_ROW, "birimTuruAdi": "ÖNLISANS"}
    net = Net.model_validate(raw)
    assert net.birim_turu_adi == "ONLISANS"


def test_net_page_validates_source_field() -> None:
    page = SearchPage[Net].model_validate(make_net_search_response([SAMPLE_NET_ROW], total=1, size=10))
    assert page.source == "snapshot"
    assert page.content[0].kilavuz_kodu == 102210277


def test_net_filters_payload_camel_case_and_defaults() -> None:
    payload = NetFilters().to_payload()
    assert payload == {
        "puanTuru": None,
        "universiteId": None,
        "birimGrupId": None,
        "birimTuruId": None,
        "universiteTuru": None,
        "yil": None,
        "katsayi": None,
    }


def test_net_filters_serializes_yil_as_string() -> None:
    assert NetFilters(yil=2025).to_payload()["yil"] == "2025"


def test_net_filters_normalizes_puan_turu_aliases() -> None:
    assert NetFilters(puan_turu="SÖZ").to_payload()["puanTuru"] == "SÖZ"


def test_net_filters_rejects_smart_id_collision() -> None:
    with pytest.raises(ValueError, match="universite/universite_id"):
        NetFilters(universite="boğaziçi", universite_id=1)
    with pytest.raises(ValueError, match="program/birim_grup_id"):
        NetFilters(program="bilgisayar", birim_grup_id=1)


def test_net_filters_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        NetFilters.model_validate({"unknown_field": 1})
```

- [ ] **Step 4: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_models.py -k "net_" -v`
Expected: FAIL — `ImportError: cannot import name 'Net' from 'yokatlas_py.models'` (or `NetFilters`).

- [ ] **Step 5: Implement `Net` and `NetFilters` in `yokatlas_py/models.py`**

Add `Net` right after the `Program` class (after its `all_years` property, before the `SearchPage` section comment):

```python
class Net(BaseModel):
    """A single Net Sihirbazı result row — the last-placed candidate's exam
    net counts for one program/university/year (``/api/netler/search``).

    Which ``*_net`` fields are populated depends on :attr:`puan_turu`: TYT
    fields are always present; SAY adds ``ayt_mat/fiz/kim/bio_net``; SÖZ adds
    ``ayt_tde/trh1/cog1/trh2/cog2/fel/din_net``; EA adds a subset of both;
    DİL adds ``ydt_ydil_net``.
    """

    model_config = _model_config()

    yil: int
    kilavuz_kodu: int
    puan_turu: str
    katsayi: float | None = None
    taban_puan: float | None = None
    obp: float | None = None

    tyt_trk_net: float | None = None
    tyt_sos_net: float | None = None
    tyt_mat_net: float | None = None
    tyt_fen_net: float | None = None

    ayt_mat_net: float | None = None
    ayt_fiz_net: float | None = None
    ayt_kim_net: float | None = None
    ayt_bio_net: float | None = None

    ayt_tde_net: float | None = None
    ayt_trh1_net: float | None = None
    ayt_cog1_net: float | None = None
    ayt_trh2_net: float | None = None
    ayt_cog2_net: float | None = None
    ayt_fel_net: float | None = None
    ayt_din_net: float | None = None

    ydt_ydil_net: float | None = None

    universite_id: int
    universite_adi: str
    birim_grup_id: int | None = None
    birim_grup_adi: str | None = None
    birim_id: int | None = None
    birim_adi: str
    birim_turu_id: int | None = None
    birim_turu_adi: Literal["LISANS", "ONLISANS"]
    universite_turu: Literal["DEVLET", "VAKIF", "VAKIF MYO"]

    @model_validator(mode="before")
    @classmethod
    def _normalize_birim_turu(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return _normalize_onlisans_spelling(dict(data))
```

Add `NetFilters` right after `SearchFilters` (after its `_normalize_puan_turu` staticmethod, before `__all__`):

```python
class NetFilters(BaseModel):
    """Filters accepted by :class:`yokatlas_py.client.YokAtlasClient.search_netler`
    (the Net Sihirbazı / "son yerleşen kişinin netleri" endpoint).

    Unlike :class:`SearchFilters`, ``universite_id``/``birim_grup_id`` are
    *singular* — the underlying API does not accept lists for this endpoint.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    puan_turu: PuanTuru | None = None
    universite_id: int | None = None
    birim_grup_id: int | None = None
    birim_turu_id: int | None = None
    universite_turu: Literal["DEVLET", "VAKIF"] | None = None
    yil: int | None = None
    katsayi: float | None = None

    # Smart (string) filters — resolved when smart_search=True
    universite: str | None = None
    program: str | None = None

    @model_validator(mode="after")
    def _no_smart_id_collision(self) -> "NetFilters":
        clashes: list[str] = []
        if self.universite is not None and self.universite_id is not None:
            clashes.append("universite/universite_id")
        if self.program is not None and self.birim_grup_id is not None:
            clashes.append("program/birim_grup_id")
        if clashes:
            raise ValueError(
                "Smart filter and ID filter cannot be set together: " + ", ".join(clashes)
            )
        return self

    def to_payload(self) -> dict[str, Any]:
        """Render the filter object as the API expects (camelCase, singular IDs)."""
        return {
            "puanTuru": SearchFilters._normalize_puan_turu(self.puan_turu),
            "universiteId": self.universite_id,
            "birimGrupId": self.birim_grup_id,
            "birimTuruId": self.birim_turu_id,
            "universiteTuru": self.universite_turu,
            "yil": str(self.yil) if self.yil is not None else None,
            "katsayi": self.katsayi,
        }
```

`SearchFilters._normalize_puan_turu` is already a `@staticmethod`, so calling it as `SearchFilters._normalize_puan_turu(...)` from `NetFilters` is valid and avoids duplicating the `SOZ`/`DIL` alias dict.

Finally add `Net` and `NetFilters` to the `__all__` list at the bottom of `yokatlas_py/models.py`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (all tests, including the pre-existing ones — confirms the `Program`/`SearchPage` refactor didn't break anything).

- [ ] **Step 7: Commit**

```bash
git add yokatlas_py/models.py tests/test_models.py tests/conftest.py
git commit -m "feat(models): add Net and NetFilters models for the netler API"
```

---

### Task 2: Sync `search_netler()` on `YokAtlasClient` + module convenience function

**Files:**
- Modify: `yokatlas_py/client.py`
- Modify: `tests/conftest.py` (mock transport handler)
- Test: `tests/test_client_sync.py`

**Interfaces:**
- Consumes: `yokatlas_py.models.Net`, `NetFilters` (Task 1), `yokatlas_py._lookup.LookupCache.resolve_university(name) -> University`, `.resolve_program(name) -> ProgramGroup` (existing, unchanged).
- Produces: `yokatlas_py.client._NETLER_SEARCH_PATH: str`, `yokatlas_py.client._resolve_net_smart_fields(filters: NetFilters, cache: LookupCache) -> NetFilters`, `YokAtlasClient.search_netler(filters=None, *, page=0, size=20, smart_search=True) -> SearchPage[Net]`, module-level `yokatlas_py.client.search_netler(filters=None, *, page=0, size=20, smart_search=True) -> SearchPage[Net]`.

- [ ] **Step 1: Extend the mock transport handler to answer `/api/netler/search`**

In `tests/conftest.py`, inside `_mock_handler`, add a new branch before the final `return httpx.Response(404, ...)` line:

```python
    if path == "/api/netler/search":
        import json as _json
        body = request.content
        try:
            payload = _json.loads(body) if body else {}
        except Exception:
            payload = {}
        filters = payload.get("filters") or {}
        size = payload.get("size", 20)
        page = payload.get("page", 0)
        universite_id = filters.get("universiteId")
        birim_grup_id = filters.get("birimGrupId")
        yil = filters.get("yil")
        if universite_id and birim_grup_id and not yil:
            # "detail" view: one specific program at one specific university
            # returns the last 3 years of history (mirrors the real API).
            rows = [{**SAMPLE_NET_ROW, "yil": y} for y in (2025, 2024, 2023)]
            return httpx.Response(200, json=make_net_search_response(rows, total=len(rows), size=size, page=page))
        return httpx.Response(200, json=make_net_search_response(size=size, page=page))
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_client_sync.py` (change the existing `from yokatlas_py.models import SearchFilters` line to `from yokatlas_py.models import NetFilters, SearchFilters`, and add two new import lines: `from yokatlas_py._lookup import LookupCache` and `from yokatlas_py.client import _resolve_net_smart_fields`):

```python
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
```

`SAMPLE_NET_ROW` and `make_net_search_response` are defined in `tests/conftest.py` itself (Task 1, Step 3), so the mock handler in Step 1 above uses them directly with no additional import.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_client_sync.py -k "netler or resolve_net" -v`
Expected: FAIL — `AttributeError: 'YokAtlasClient' object has no attribute 'search_netler'` (and `ImportError` for `_resolve_net_smart_fields`).

- [ ] **Step 4: Implement in `yokatlas_py/client.py`**

Add the import of `Net`/`NetFilters` — change the existing models import line:

```python
from .models import City, Net, NetFilters, Program, ProgramGroup, SearchFilters, SearchPage, University
```

Add the endpoint constant next to the existing path constants:

```python
_NETLER_SEARCH_PATH = "/api/netler/search"
```

Add these two helpers right after `_resolve_smart_fields` (before the `# Sync client` section comment):

```python
def _coerce_net_filters(value: NetFilters | dict[str, Any] | None) -> NetFilters:
    if value is None:
        return NetFilters()
    if isinstance(value, NetFilters):
        return value
    return NetFilters.model_validate(value)


def _build_net_request(filters: NetFilters, *, page: int, size: int) -> dict[str, Any]:
    return {
        "filters": filters.to_payload(),
        "page": int(page),
        "size": int(size),
    }


def _resolve_net_smart_fields(filters: NetFilters, cache: LookupCache) -> NetFilters:
    """Replace string filters (universite/program) with their ID counterparts.

    Unlike :func:`_resolve_smart_fields`, both fields are singular (the
    netler endpoint does not accept lists). Resolving ``program`` also
    defaults ``puan_turu`` from the matched :class:`ProgramGroup` when the
    caller didn't set one explicitly, mirroring what the Net Sihirbazı UI
    does when a program is chosen.
    """
    if not any((filters.universite, filters.program)):
        return filters

    data = filters.model_dump()
    if filters.universite is not None:
        data["universite_id"] = cache.resolve_university(filters.universite).universite_id
        data["universite"] = None
    if filters.program is not None:
        resolved_program = cache.resolve_program(filters.program)
        data["birim_grup_id"] = resolved_program.birim_grup_id
        data["program"] = None
        if filters.puan_turu is None:
            data["puan_turu"] = resolved_program.puan_turu
    return NetFilters.model_validate(data)
```

Add the method to `YokAtlasClient`, right after `search` (before `get_program`):

```python
    def search_netler(
        self,
        filters: NetFilters | dict[str, Any] | None = None,
        *,
        page: int = 0,
        size: int = 20,
        smart_search: bool = True,
    ) -> SearchPage[Net]:
        """Search the Net Sihirbazı (son yerleşen kişinin netleri)."""
        f = _coerce_net_filters(filters)
        if smart_search and any((f.universite, f.program)):
            self._ensure_lookups()
            f = _resolve_net_smart_fields(f, self._lookups)
        body = _build_net_request(f, page=page, size=size)
        raw = self._http.post_json(_NETLER_SEARCH_PATH, json_body=body)
        return SearchPage[Net].model_validate(raw)
```

Add the module-level convenience function right after `search_programs` (before `get_program`'s module-level wrapper):

```python
def search_netler(
    filters: NetFilters | dict[str, Any] | None = None,
    *,
    page: int = 0,
    size: int = 20,
    smart_search: bool = True,
) -> SearchPage[Net]:
    """Convenience wrapper around :meth:`YokAtlasClient.search_netler` using a process-wide client."""
    return _get_default_client().search_netler(
        filters,
        page=page,
        size=size,
        smart_search=smart_search,
    )
```

Add `"search_netler"` to the `__all__` list at the bottom of `yokatlas_py/client.py`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_client_sync.py -v`
Expected: PASS (all tests, including pre-existing ones).

- [ ] **Step 6: Commit**

```bash
git add yokatlas_py/client.py tests/conftest.py tests/test_client_sync.py
git commit -m "feat(client): add sync search_netler() for the Net Sihirbazı endpoint"
```

---

### Task 3: Async `search_netler()` on `AsyncYokAtlasClient`

**Files:**
- Modify: `yokatlas_py/client.py`
- Test: `tests/test_client_async.py`

**Interfaces:**
- Consumes: `Net`, `NetFilters`, `_NETLER_SEARCH_PATH`, `_coerce_net_filters`, `_build_net_request`, `_resolve_net_smart_fields` (Task 2, all in `yokatlas_py/client.py`).
- Produces: `AsyncYokAtlasClient.search_netler(filters=None, *, page=0, size=20, smart_search=True) -> SearchPage[Net]` (async).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_client_async.py` (add `NetFilters` to the existing `from yokatlas_py.models import SearchFilters` line):

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_client_async.py -k netler -v`
Expected: FAIL — `AttributeError: 'AsyncYokAtlasClient' object has no attribute 'search_netler'`.

- [ ] **Step 3: Implement `AsyncYokAtlasClient.search_netler`**

In `yokatlas_py/client.py`, add this method to `AsyncYokAtlasClient`, right after `search` (before `get_program`):

```python
    async def search_netler(
        self,
        filters: NetFilters | dict[str, Any] | None = None,
        *,
        page: int = 0,
        size: int = 20,
        smart_search: bool = True,
    ) -> SearchPage[Net]:
        f = _coerce_net_filters(filters)
        if smart_search and any((f.universite, f.program)):
            await self._ensure_lookups()
            f = _resolve_net_smart_fields(f, self._lookups)
        body = _build_net_request(f, page=page, size=size)
        raw = await self._http.post_json(_NETLER_SEARCH_PATH, json_body=body)
        return SearchPage[Net].model_validate(raw)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_client_async.py -v`
Expected: PASS (all tests, including pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add yokatlas_py/client.py tests/test_client_async.py
git commit -m "feat(client): add async search_netler() for the Net Sihirbazı endpoint"
```

---

### Task 4: Public exports (`__init__.py`)

**Files:**
- Modify: `yokatlas_py/__init__.py`
- Test: `tests/test_models.py` (or a new small import-surface test — see below)

**Interfaces:**
- Consumes: `Net`, `NetFilters` (Task 1), `search_netler` (Task 2, module-level).
- Produces: `yokatlas_py.Net`, `yokatlas_py.NetFilters`, `yokatlas_py.search_netler` as top-level package exports.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py` (top-level, doesn't need a fixture):

```python
def test_net_types_are_exported_from_package_root() -> None:
    import yokatlas_py

    assert yokatlas_py.Net is Net
    assert yokatlas_py.NetFilters is NetFilters
    assert callable(yokatlas_py.search_netler)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_models.py -k package_root -v`
Expected: FAIL — `AttributeError: module 'yokatlas_py' has no attribute 'Net'`.

- [ ] **Step 3: Update `yokatlas_py/__init__.py`**

Change the `.client` import block from:

```python
from .client import (
    AsyncYokAtlasClient,
    YokAtlasClient,
    get_program,
    list_cities,
    list_program_groups,
    list_universities,
    search_programs,
)
```

to:

```python
from .client import (
    AsyncYokAtlasClient,
    YokAtlasClient,
    get_program,
    list_cities,
    list_program_groups,
    list_universities,
    search_netler,
    search_programs,
)
```

Change the `.models` import block from:

```python
from .models import (
    City,
    Program,
    ProgramGroup,
    PuanTuru,
    SearchFilters,
    SearchPage,
    University,
    YearlyStats,
)
```

to:

```python
from .models import (
    City,
    Net,
    NetFilters,
    Program,
    ProgramGroup,
    PuanTuru,
    SearchFilters,
    SearchPage,
    University,
    YearlyStats,
)
```

Add `"search_netler"` to the `# Convenience` section of `__all__`, and `"Net"`, `"NetFilters"` to the `# Models` section of `__all__` (alphabetically among the existing entries).

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS — every test in `tests/` (all four files), no regressions.

- [ ] **Step 6: Commit**

```bash
git add yokatlas_py/__init__.py tests/test_models.py
git commit -m "feat: export Net, NetFilters, and search_netler from the package root"
```

---

### Task 5: Documentation + version bump

**Files:**
- Modify: `API.md`
- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml`
- Modify: `yokatlas_py/__init__.py`

No new tests in this task (documentation-only + version metadata); verification is a final full-suite run plus a manual read-through.

- [ ] **Step 1: Bump the version**

In `pyproject.toml`, change:

```toml
version = "0.6.1"
```

to:

```toml
version = "0.7.0"
```

In `yokatlas_py/__init__.py`, change:

```python
__version__ = "0.6.1"
```

to:

```python
__version__ = "0.7.0"
```

- [ ] **Step 2: Add a CHANGELOG entry**

In `CHANGELOG.md`, insert a new section right after the `# Changelog` heading, before `## 0.6.1`:

```markdown
## 0.7.0

### Added

- **Net Sihirbazı support**: `search_netler()` (sync + async) and the module-level `search_netler()` convenience wrap YÖK Atlas's new `/api/netler/search` endpoint — the last-placed candidate's exam net counts (TYT/AYT/YDT subtest nets) per program/university/year ("son yerleşen kişinin netleri").
- `Net` and `NetFilters` pydantic models. `NetFilters` supports the same smart (name→id) search as `SearchFilters` — `universite`/`program` resolve via the existing lookup cache, with `program` also defaulting `puan_turu` from the matched program group.
- `SearchPage[T]` gained an optional `source` field (present on netler responses).
```

- [ ] **Step 3: Add a section to `API.md`**

Add a new `### Net Sihirbazı` subsection to the "İstemciler" → `YokAtlasClient` section, right after the existing `#### search(...)` block (before `#### get_program`):

```markdown
#### `search_netler(filters=None, *, page=0, size=20, smart_search=True) -> SearchPage[Net]`

Net Sihirbazı'nı (son yerleşen kişinin netleri) arar. `filters` `NetFilters`, `dict` veya `None` olabilir. `universite`/`program` `smart_search=True` iken tekil ID'ye çözülür; `program` verilip `puan_turu` verilmemişse çözülen program grubunun `puan_turu`'sü otomatik kullanılır.

> Hem `universite_id` hem `birim_grup_id` birlikte verilip `yil` verilmezse, o programın son 3 yılının (yıl, taban puan, netler) geçmişi döner — "Son Kişinin Net Verileri" görünümüyle birebir aynı.
```

Add `search_netler` to the `AsyncYokAtlasClient` section's example, right after the existing `prog = await client.get_program(...)` line:

```python
    nets = await client.search_netler(NetFilters(universite="boğaziçi", program="bilgisayar mühendisliği"))
```

Add a `### Net` and `### NetFilters` subsection to "Modeller"/"Filtreler" respectively, mirroring the existing `### Program`/`### SearchFilters` tables:

```markdown
### `Net`

Net Sihirbazı endpoint'inden dönen tek bir kayıt — son yerleşen kişinin netleri.

| Alan | Tip | Açıklama |
|---|---|---|
| `yil` | `int` | Sınav/yerleşme yılı |
| `kilavuz_kodu` | `int` | ÖSYM kılavuz kodu |
| `puan_turu` | `str` | SAY / SÖZ / EA / DİL / TYT |
| `katsayi` | `float \| None` | |
| `taban_puan` | `float \| None` | Son yerleşenin puanı |
| `obp` | `float \| None` | Orta öğretim başarı puanı |
| `tyt_trk_net`, `tyt_sos_net`, `tyt_mat_net`, `tyt_fen_net` | `float \| None` | TYT netleri (her puan türünde var) |
| `ayt_mat_net`, `ayt_fiz_net`, `ayt_kim_net`, `ayt_bio_net` | `float \| None` | SAY netleri |
| `ayt_tde_net`, `ayt_trh1_net`, `ayt_cog1_net`, `ayt_trh2_net`, `ayt_cog2_net`, `ayt_fel_net`, `ayt_din_net` | `float \| None` | SÖZ netleri (EA bir alt kümesini kullanır) |
| `ydt_ydil_net` | `float \| None` | DİL neti |
| `universite_id` / `universite_adi`, `birim_grup_id` / `birim_grup_adi`, `birim_id` / `birim_adi` | — | `Program` ile aynı ID uzayı |
| `birim_turu_adi` | `"LISANS" \| "ONLISANS"` | |
| `universite_turu` | `"DEVLET" \| "VAKIF" \| "VAKIF MYO"` | |

### `NetFilters`

`SearchFilters` ile aynı desende, ancak `universite_id`/`birim_grup_id` **tekil** (liste değil) — endpoint liste kabul etmiyor.

| Alan | Tip | Notlar |
|---|---|---|
| `puan_turu` | `PuanTuru \| None` | |
| `universite_id` | `int \| None` | Doğrudan ID (tekil) |
| `birim_grup_id` | `int \| None` | Doğrudan ID (tekil) |
| `birim_turu_id` | `int \| None` | 46 = LİSANS, 47 = ÖNLİSANS |
| `universite_turu` | `"DEVLET" \| "VAKIF" \| None` | |
| `yil` | `int \| None` | Belirtilmezse: tek program+üniversite sorgusu son 3 yılı, geniş sorgu son yılı döner |
| `katsayi` | `float \| None` | UI'da yok, nadiren gerekir |
| **`universite`** | `str \| None` | Akıllı — `universite_id` ile birlikte verilemez |
| **`program`** | `str \| None` | Akıllı — `birim_grup_id` ile birlikte verilemez; verilirse ve `puan_turu` boşsa otomatik doldurulur |
```

Add a row to the "Endpoint eşlemesi (referans)" table at the bottom:

```markdown
| `/api/netler/search` | POST | `search_netler()` |
```

And update the intro sentence "Bu kütüphane sadece 4 resmi endpoint'i sarar" to "5 resmi endpoint'i sarar".

- [ ] **Step 4: Add a section to `README.md`**

Add a bullet to the "Özellikler" list, right after the "Akıllı arama" bullet:

```markdown
- **Net Sihirbazı**: `search_netler()` ile son yerleşen kişinin TYT/AYT/YDT netlerini (yıl bazında) sorgula.
```

Add a short example right after the existing "Hızlı başlangıç" code block (before "### Async kullanım"):

```markdown
### Net Sihirbazı (son yerleşen kişinin netleri)

```python
from yokatlas_py import YokAtlasClient, NetFilters

with YokAtlasClient() as client:
    # Belirli bir programın son 3 yıllık net geçmişi
    page = client.search_netler(
        NetFilters(universite="boğaziçi", program="bilgisayar mühendisliği"),
    )
    for net in page.content:
        print(f"{net.yil}: TYT Mat {net.tyt_mat_net} / AYT Fizik {net.ayt_fiz_net}")
```
```

- [ ] **Step 5: Add a section to `README_EN.md`**

Add a bullet to the "Features" list, right after "Smart search":

```markdown
- **Net Sihirbazı**: `search_netler()` returns the last-placed candidate's TYT/AYT/YDT net counts per year.
```

Add a matching English example right after the "Quickstart" code block (before "### Async"):

```markdown
### Net Sihirbazı (last-placed candidate's exam nets)

```python
from yokatlas_py import YokAtlasClient, NetFilters

with YokAtlasClient() as client:
    page = client.search_netler(
        NetFilters(universite="boğaziçi", program="bilgisayar mühendisliği"),
    )
    for net in page.content:
        print(net.yil, net.tyt_mat_net, net.ayt_fiz_net)
```
```

- [ ] **Step 6: Run the full test suite one final time**

Run: `uv run pytest -v`
Expected: PASS — all tests across `tests/test_client_async.py`, `tests/test_client_sync.py`, `tests/test_lookup.py`, `tests/test_models.py`.

- [ ] **Step 7: Commit**

```bash
git add API.md README.md README_EN.md CHANGELOG.md pyproject.toml yokatlas_py/__init__.py
git commit -m "docs: document search_netler() and bump version to 0.7.0"
```
