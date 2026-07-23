# Net Sihirbazı (Son Yerleşen Kişinin Netleri) — Design

## Background

YÖK Atlas recently (2026 tercih dönemi) opened up a new public tool, **Net Sihirbazı**,
alongside the existing Tercih Sihirbazı. It exposes the exam net counts (TYT/AYT/YDT
subtest nets) of the last-placed candidate for every program/university/year
combination — i.e. "son yerleşen kişinin netleri". This is a single feature: the
"Net Sihirbazı" page *is* the "son yerleşen kişinin netleri" lookup; there is no
separate feature to build.

`yokatlas-py` currently only wraps the tercih-kılavuzu (`/api/tercih-kilavuz/*`)
endpoints (contenjan/yerleşen/puan/sıra data via `YokAtlasClient.search`). This
design adds a symmetric wrapper around the new netler endpoint.

## Endpoint (reverse-engineered via Chrome DevTools network inspection)

```
POST https://yokatlas.yok.gov.tr/api/netler/search
Content-Type: application/json
```

Request body:

```json
{
  "filters": {
    "puanTuru": "SAY",          // SAY | SÖZ | EA | DİL | TYT, or null (= all)
    "yil": "2025",               // string year or null
    "birimGrupId": 2010,          // SINGLE int or null (not a list)
    "birimTuruId": 46,             // 46 = LISANS, 47 = ONLISANS, or null
    "universiteTuru": "DEVLET",  // "DEVLET" | "VAKIF" (others exist but unconfirmed)
    "katsayi": null,               // float or null; no UI control, advanced/rare
    "universiteId": 105322        // SINGLE int or null (not a list)
  },
  "page": 0,
  "size": 20,
  "sortBy": "...",    // accepted but has no observed effect on ordering
  "direction": "..."   // accepted but has no observed effect on ordering
}
```

Response: a Spring-style `Page<T>` shape identical to the tercih-kılavuzu search
response, plus one extra field:

```json
{
  "content": [...],
  "empty": false, "first": true, "last": true,
  "number": 0, "numberOfElements": 20, "size": 20,
  "totalElements": 958, "totalPages": 48,
  "source": "snapshot"
}
```

### Row shape (per `puanTuru`)

Common fields on every row:

```
yil, kilavuzKodu, puanTuru, katsayi, tabanPuan, obp,
universiteId, universiteAdi,
birimGrupId, birimGrupAdi,
birimId, birimAdi,
birimTuruId, birimTuruAdi,   // "LISANS" | "ÖNLISANS" (note: dotted Ö, like Program)
universiteTuru
```

Net fields present depend on `puanTuru` (verified live for all 5 types):

| puanTuru | extra fields |
|---|---|
| TYT (önlisans) | `tytTrkNet, tytSosNet, tytMatNet, tytFenNet` |
| SAY | + `aytMatNet, aytFizNet, aytKimNet, aytBioNet` |
| SÖZ | + `aytTdeNet, aytTrh1Net, aytCog1Net, aytTrh2Net, aytCog2Net, aytFelNet, aytDinNet` |
| EA | + `aytMatNet, aytTdeNet, aytTrh1Net, aytCog1Net` |
| DİL | + `ydtYdilNet` |

All lisans rows also carry `tytTrkNet, tytSosNet, tytMatNet, tytFenNet` (the TYT
subtest is common to every puanTuru).

### Behavior notes verified live

- `puanTuru` is *not* actually required server-side (the UI marks it required
  with `*`, but an empty/`null` filter returns a mix of all puan türleri).
  Sending `null` for `birimTuruId` returns both LISANS + ONLISANS mixed
  (34599 + 28464 = 63063 total, confirmed by direct query).
- When **both** `universiteId` and `birimGrupId` are given together (i.e. "one
  specific program at one specific university") and `yil` is *not* given, the
  response returns the last 3 years of history for that program (e.g.
  2025/2024/2023) instead of a single row. This is the "Son Kişinin Net
  Verileri" detail view.
- When `yil` is omitted and the query is broader (missing university or
  program), only the current/latest completed year (2025 as of writing) is
  returned — one row per matching program.
- `yil` accepts the *current* guide year (2026) but returns "no records" for
  it since 2026 placement results don't exist yet at time of writing. Valid
  data years observed: 2023, 2024, 2025.
- `sortBy`/`direction` parameters are accepted without error but do not
  change result ordering in any observed test — results are always sorted by
  `tabanPuan` descending. Not worth exposing as a meaningfully-functional
  parameter; we pass through best-effort only, matching existing `search()`
  behavior, and do not promise sort control in docs.
- **Confirmed same ID namespace as `/api/tercih-kilavuz/*`**: `universiteId`
  105322 = BOĞAZİÇİ ÜNİVERSİTESİ in both APIs; `birimGrupId` 2010 = Bilgisayar
  Mühendisliği in both APIs. This means the existing `LookupCache` (already
  populated from `/api/tercih-kilavuz/universiteler` and
  `/universite-programlar`) can resolve names to IDs for this new endpoint
  with **no new fetcher/lookup needed**.
- `ProgramGroup` (from the existing lookup) already carries a `puan_turu`
  field per program name, so resolving `program="Bilgisayar Mühendisliği"`
  also yields the correct `puanTuru` to default to, mirroring what the actual
  Net Sihirbazı UI does (auto-fills Puan Türü when a program is chosen).

## Design

### `models.py`

- Add `source: str | None = None` to the existing generic `SearchPage[T]`
  model. This is backward compatible (optional field, existing `Program`
  pages simply won't populate it) and avoids introducing a second Page class.
- Add `Net` model: one net-search result row. All puanTuru-specific net
  fields (`ayt_mat_net`, `ayt_tde_net`, `ydt_ydil_net`, etc.) are declared as
  `float | None = None` since presence depends on `puan_turu`. Reuses the
  same `_model_config()` alias-generator helper as `Program`/`University`
  etc. `birim_turu_adi` gets the same "ÖNLISANS" → "ONLISANS" normalization
  `Program` already does (extract that one-line normalization into a small
  shared helper in `models.py` rather than duplicating the conditional).
- Add `NetFilters` model, parallel to `SearchFilters` but with **singular**
  ID fields (`universite_id: int | None`, `birim_grup_id: int | None` — not
  lists) since the endpoint doesn't accept arrays for these. Fields:
  `puan_turu`, `universite_turu` (`Literal["DEVLET", "VAKIF"]`, same
  restriction as `SearchFilters` today), `birim_turu_id`, `yil: int | None`,
  `katsayi: float | None`, plus smart string fields `universite: str | None`,
  `program: str | None` (singular). Same "smart + id collision forbidden"
  validation pattern as `SearchFilters._no_smart_id_collision`. A
  `to_payload()` method renders the camelCase request `filters` object
  (`yil` rendered as a string per observed API behavior, or `None`).

### `client.py`

- Add `_NETLER_SEARCH_PATH = "/api/netler/search"`.
- Add `_resolve_net_smart_fields(filters, cache) -> NetFilters` helper,
  parallel to `_resolve_smart_fields` but resolving singular
  `universite`/`program` strings to singular IDs (and defaulting
  `puan_turu` from the resolved `ProgramGroup.puan_turu` when the caller
  didn't set one explicitly).
- `YokAtlasClient.search_netler(filters, *, page=0, size=20, smart_search=True) -> SearchPage[Net]`
  — same shape/skeleton as `search()`, POSTs to `_NETLER_SEARCH_PATH`.
- Same method on `AsyncYokAtlasClient`.
- Module-level convenience `search_netler(...)` using the lazy default
  client singleton, symmetric with `search_programs`.

### `__init__.py`

Export `Net`, `NetFilters`, `search_netler`.

### Out of scope

- `sortBy`/`direction` — accepted passthrough only, no functional guarantee
  documented (matches reality: server ignores them).
- No smart resolution for `katsayi` (raw float passthrough only — no UI
  control for it, rarely needed).
- `universiteTuru` values beyond `DEVLET`/`VAKIF` (KKTC, Yurtdışı Vakıf,
  Yurtdışı Kamu) are not supported, consistent with the existing
  `SearchFilters.universite_turu` restriction.
- No new HTTP fetchers or lookup endpoints — reuses `LookupCache` as-is.

## Testing

- Extend the existing `tests/` pytest suite (`test_client_sync.py`,
  `test_client_async.py`, `test_models.py`, `test_lookup.py` — using the
  mocked-transport fixtures already in `conftest.py`) to cover:
  single program+university (multi-year history), broad program-only search
  (latest year, paginated), smart-search resolution (name → id, and
  program → default puan_turu), and the `NetFilters` collision validation.
