"""Short time zone names as ICU formats them for ``en-US``.

The session-memory hook stamps its heading with the ``timeZoneName`` part of
``Intl.DateTimeFormat("en-US", {timeZoneName: "short"})``
(``src/hooks/bundled/session-memory/handler.ts:52-86``). Python has no ICU,
so this module reproduces that part from data:

- zones whose CLDR metazone has an ``en`` short name (the North American
  zones, the GMT zones and the UTC aliases) map ``(UTC offset in minutes,
  daylight time)`` to that name;
- every other zone and offset uses ICU's localized GMT format: ``GMT+3``,
  ``GMT+5:30``, ``GMT-0:44:30``, and ``GMT+0`` for a zero offset.

The table was measured on 2026-09-26 with Node v25.2.1 (ICU 78.1, tz 2025b)
for every zone in Python's ``zoneinfo.available_timezones()`` at 72
instants from 2005 to 2026-08, keeping only the instants where Python's
tzdata (2026c on the measuring machine) and ICU agree on the local time.
Checked against the same probe: 42976 of those 42984 zone-instant pairs
match; the 8 others are America/Ciudad_Juarez before 2022, when ICU gave it
the GMT format rather than MST/MDT. Before 2005, after a tzdata change, or
where Python's tzdata and ICU differ, the name can also differ from Node's.
"""

from __future__ import annotations

from datetime import datetime

_EN_US_SHORT_ZONE_NAME_GROUPS: tuple[tuple[dict[tuple[int, bool], str], tuple[str, ...]], ...] = (
    (
        {(0, False): "GMT"},
        (
            "Africa/Abidjan", "Africa/Accra", "Africa/Bamako", "Africa/Banjul", "Africa/Bissau",
            "Africa/Conakry", "Africa/Dakar", "Africa/Freetown", "Africa/Lome", "Africa/Monrovia",
            "Africa/Nouakchott", "Africa/Ouagadougou", "Africa/Sao_Tome", "Africa/Timbuktu",
            "America/Danmarkshavn", "Antarctica/Troll", "Atlantic/Reykjavik", "Atlantic/St_Helena",
            "Etc/GMT+0", "Etc/GMT-0", "Etc/GMT0", "Etc/Greenwich", "Europe/Belfast",
            "Europe/Guernsey", "Europe/Isle_of_Man", "Europe/Jersey", "Europe/London", "GB",
            "GB-Eire", "Greenwich", "Iceland",
        ),
    ),
    (
        {(-240, True): "EDT", (-300, False): "EST"},
        (
            "America/Detroit", "America/Fort_Wayne", "America/Indiana/Indianapolis",
            "America/Indiana/Marengo", "America/Indiana/Petersburg", "America/Indiana/Vevay",
            "America/Indiana/Vincennes", "America/Indiana/Winamac", "America/Indianapolis",
            "America/Iqaluit", "America/Kentucky/Louisville", "America/Kentucky/Monticello",
            "America/Louisville", "America/Montreal", "America/Nassau", "America/New_York",
            "America/Nipigon", "America/Pangnirtung", "America/Port-au-Prince",
            "America/Thunder_Bay", "America/Toronto", "Canada/Eastern", "EST5EDT",
            "US/East-Indiana", "US/Eastern", "US/Michigan",
        ),
    ),
    (
        {(-240, False): "AST"},
        (
            "America/Anguilla", "America/Antigua", "America/Aruba", "America/Barbados",
            "America/Blanc-Sablon", "America/Curacao", "America/Dominica", "America/Grenada",
            "America/Guadeloupe", "America/Kralendijk", "America/Lower_Princes", "America/Marigot",
            "America/Martinique", "America/Montserrat", "America/Port_of_Spain",
            "America/Puerto_Rico", "America/Santo_Domingo", "America/St_Barthelemy",
            "America/St_Kitts", "America/St_Lucia", "America/St_Thomas", "America/St_Vincent",
            "America/Tortola", "America/Virgin",
        ),
    ),
    (
        {(-300, True): "CDT", (-360, False): "CST"},
        (
            "America/Chicago", "America/Managua", "America/Matamoros", "America/Menominee",
            "America/Merida", "America/Mexico_City", "America/Monterrey",
            "America/North_Dakota/Center", "America/North_Dakota/New_Salem", "America/Rainy_River",
            "America/Rankin_Inlet", "America/Resolute", "America/Winnipeg", "CST6CDT",
            "Canada/Central", "Mexico/General", "US/Central",
        ),
    ),
    (
        {(0, False): "UTC"},
        (
            "Etc/GMT", "Etc/UCT", "Etc/UTC", "Etc/Universal", "Etc/Zulu", "GMT", "GMT+0", "GMT-0",
            "GMT0", "UCT", "UTC", "Universal", "Zulu",
        ),
    ),
    (
        {(-420, True): "PDT", (-480, False): "PST"},
        (
            "America/Dawson", "America/Ensenada", "America/Los_Angeles", "America/Santa_Isabel",
            "America/Tijuana", "America/Vancouver", "America/Whitehorse", "Canada/Pacific",
            "Canada/Yukon", "Mexico/BajaNorte", "PST8PDT", "US/Pacific",
        ),
    ),
    (
        {(-360, True): "MDT", (-420, False): "MST"},
        (
            "America/Boise", "America/Cambridge_Bay", "America/Ciudad_Juarez", "America/Denver",
            "America/Edmonton", "America/Inuvik", "America/Shiprock", "America/Yellowknife",
            "Canada/Mountain", "MST7MDT", "Navajo", "US/Mountain",
        ),
    ),
    (
        {(-360, False): "CST"},
        (
            "America/Belize", "America/Chihuahua", "America/Costa_Rica", "America/El_Salvador",
            "America/Guatemala", "America/Regina", "America/Swift_Current", "America/Tegucigalpa",
            "Canada/Saskatchewan",
        ),
    ),
    (
        {(-300, False): "EST"},
        (
            "America/Atikokan", "America/Cayman", "America/Coral_Harbour", "America/Jamaica",
            "America/Panama", "EST", "Jamaica",
        ),
    ),
    (
        {(-180, True): "ADT", (-240, False): "AST"},
        (
            "America/Glace_Bay", "America/Goose_Bay", "America/Halifax", "America/Moncton",
            "America/Thule", "Atlantic/Bermuda", "Canada/Atlantic",
        ),
    ),
    (
        {(-480, True): "AKDT", (-540, False): "AKST"},
        (
            "America/Anchorage", "America/Juneau", "America/Nome", "America/Sitka",
            "America/Yakutat", "US/Alaska",
        ),
    ),
    (
        {(-420, False): "MST"},
        (
            "America/Creston", "America/Dawson_Creek", "America/Phoenix", "MST", "US/Arizona",
        ),
    ),
    (
        {(-300, False): "EST", (-300, True): "CDT", (-360, False): "CST"},
        (
            "America/Cancun", "America/Indiana/Knox", "America/Indiana/Tell_City",
            "America/Knox_IN", "US/Indiana-Starke",
        ),
    ),
    (
        {(-600, False): "HST"},
        (
            "HST", "Pacific/Honolulu", "Pacific/Johnston", "US/Hawaii",
        ),
    ),
    (
        {(-540, True): "HADT", (-600, False): "HAST"},
        (
            "America/Adak", "America/Atka", "US/Aleutian",
        ),
    ),
    (
        {(-300, True): "CDT", (-360, False): "CST", (-360, True): "MDT", (-420, False): "MST"},
        (
            "America/Bahia_Banderas", "America/North_Dakota/Beulah", "America/Ojinaga",
        ),
    ),
    (
        {(-480, False): "PST", (-480, True): "AKDT", (-540, False): "AKST"},
        (
            "America/Metlakatla",
        ),
    ),
    (
        {(-420, False): "MST", (-420, True): "PDT", (-480, False): "PST"},
        (
            "America/Fort_Nelson",
        ),
    ),
    (
        {(-240, False): "AST", (-240, True): "EDT", (-300, False): "EST"},
        (
            "America/Grand_Turk",
        ),
    ),
)

_NAMES_BY_ZONE: dict[str, dict[tuple[int, bool], str]] = {
    zone.lower(): names for names, zones in _EN_US_SHORT_ZONE_NAME_GROUPS for zone in zones
}


def localized_gmt_name(offset_seconds: int) -> str:
    """ICU's short localized GMT format (``GMT+3``, ``GMT-3:30``, ``GMT+0``)."""
    sign = "-" if offset_seconds < 0 else "+"
    hours, rest = divmod(abs(offset_seconds), 3600)
    minutes, seconds = divmod(rest, 60)
    name = f"GMT{sign}{hours}"
    if minutes or seconds:
        name += f":{minutes:02d}"
    if seconds:
        name += f":{seconds:02d}"
    return name


def en_us_short_time_zone_name(zone_key: str, local: datetime) -> str:
    """The ``en-US`` short ``timeZoneName`` of ``local`` (an aware datetime in ``zone_key``)."""
    offset = local.utcoffset()
    offset_seconds = int(offset.total_seconds()) if offset is not None else 0
    names = _NAMES_BY_ZONE.get(zone_key.lower())
    if names is not None and offset_seconds % 60 == 0:
        name = names.get((offset_seconds // 60, bool(local.dst())))
        if name is not None:
            return name
    return localized_gmt_name(offset_seconds)
