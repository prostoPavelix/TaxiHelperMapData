# TaxiHelperMapData — архітектура й безпечне оновлення

## Призначення

Це публічний репозиторій відтворюваних OpenStreetMap-даних для Android Taxi Helper. Тут немає
історії водія, секторів, налаштувань, ручних/вивчених адрес або коду приватної програми.

## Автоматичний цикл

GitHub Actions запускається щомісяця або вручну:

1. Завантажує один Volyn `.osm.pbf`.
2. Обчислює SHA-256 source snapshot.
3. Будує з нього всі візуальні, адресні та дорожні файли.
4. Запускає deterministic verifiers і topology fixtures.
5. Публікує весь комплект одним stable release `offline-map-latest` лише після gate.

ПК власника для регулярного оновлення не потрібний.

## Format 4

- `lutsk_area.map` — Mapsforge fallback/visual map;
- `lutsk_addresses.tsv` — адреси, будинки, POI, aliases і координати;
- `lutsk_streets.tsv` — sampled street geometry;
- `visual_roads.bin` — компактні основні дороги для lightweight Canvas;
- `road_graph.bin` — directed passenger-car graph з one-way/access/turn restrictions;
- `road_anchor_index.bin` — компактні road components/anchors для live point lookup;
- `road_manifest.json` — graph capabilities, versions, OSM provenance і artifact hashes;
- `map-manifest.json` — outer bundle version, sizes, SHA-256 і статистика змін.

Outer manifest перелічує сім payload files; сам `map-manifest.json` є керівним файлом.

## Gate

Публікація заборонена, якщо:

- declared size або SHA-256 не збігаються;
- OSM provenance graph і outer bundle різний;
- погіршилася адресна/street coverage понад дозволену межу;
- зникли critical Lutsk street families;
- не проходять one-way, bridge, disconnected component, rail/detour та boundary fixtures;
- binary magic/version, row counts або deterministic output некоректні.

OSM coverage gate і learned aliases принципово розділені: приватне навчання користувача не
може приховати регресію публічних даних.

## Android activation

Телефон спочатку завантажує всі файли як `.pending`, перевіряє кожен, звіряє graph provenance
з outer manifest і лише потім атомарно переміщує весь комплект. Попередні файли зберігаються
як `.previous`. Змішування карти, адрес та graph різних версій заборонене.

Після зміни graph SHA старий V3 forecast generation не використовується. До завершення нового
ручного або screen-off rebuild Android показує sector-only forecast. Geometric V2 fallback
після production Stage 8 не використовується.

Оновлення public bundle не стирає SQLite, історію, DriverZone, manual address assignments або
learned rules. Нові будинки/вулиці/POI стають доступними через нові exact indexes; locality і
conflict safety лишаються відповідальністю Android resolver.

## Фактичний production gate 07–08.09.2026

- workflow run: `34164856459` — success;
- release version: `20260907-215810`;
- source OSM SHA-256:
  `21130f856f1a8c7a76ec9d850277ec5016bab7c93315d81d58fe688a8987e7e7`;
- address/POI records: 103 249;
- unique streets: 729; street samples: 6 336;
- Android downloaded and activated format 4 successfully;
- V3 rebuilt on phone: generation 11, 531/531 GPS facts, 949 query anchors, 25 843 rows,
  status `COMPLETE`.

## Подальша робота

Stage 9B має окремо симулювати interrupted/corrupt download і довести `.previous` rollback на
телефоні. Це не змінює регулярний monthly workflow і не потребує нового initial bundle.
