# ERM Zapad Outage Check for Home Assistant

[![Validate](https://github.com/mharizanov/ha-erm-zapad/actions/workflows/validate.yml/badge.svg)](https://github.com/mharizanov/ha-erm-zapad/actions/workflows/validate.yml)

A Home Assistant custom integration that reads the planned-outage list published
daily by **ERM Zapad / Electrohold** (Електроразпределителни мрежи Запад, western
Bulgaria) and notifies you the evening before when your settlement or district
is on it.

Unofficial. Not affiliated with or endorsed by ERM Zapad or Electrohold.

<img src="custom_components/erm_zapad/brand/icon.png" width="96" alt="Electrohold logo">

## How it works

ERM Zapad publishes one PDF per day with the next day's planned works, one line
per area:

```text
Част от ИХТИМАН 14.11.2026 08:30 14.11.2026 16:30
```

Every evening at the configured time (default 21:15) the integration:

1. Downloads tomorrow's PDF from the public
   [planned-outage page](https://info.ermzapad.bg/webint/vok/avplan.php) and
   extracts its text with [`pypdf`](https://pypi.org/project/pypdf/).
2. Checks the date in the PDF header (`Планирани прекъсвания за DD.MM.YYYY`)
   against tomorrow's date.
3. Looks for your keyword as a whole word, case-insensitive, and pulls the start
   and end time from every matching line.
4. Updates `sensor.erm_zapad_next_outage` and sends the matched lines to the
   `notify.*` services you selected.

The PDF says "part of" (`Част от`) a settlement: a listed outage may not reach
your street, and outages that are not planned are not in the PDF at all. For an
address-level answer ERM Zapad offers a check by customer number on the same page.

## Requirements

- Home Assistant **2026.3** or newer.
- Internet access from Home Assistant to `info.ermzapad.bg`.
- For push notifications: at least one `notify.*` service, e.g. the
  [Companion app](https://companion.home-assistant.io/) (`notify.mobile_app_<phone>`).

## Installation

### HACS (custom repository)

1. HACS → ⋮ (top right) → **Custom repositories**.
2. Repository: `https://github.com/mharizanov/ha-erm-zapad`, type **Integration** → **Add**.
3. Search HACS for **ERM Zapad Outage Check** → **Download**.
4. Restart Home Assistant.

### Manual

1. Download the [latest release](https://github.com/mharizanov/ha-erm-zapad/releases)
   (or clone the repository).
2. Copy `custom_components/erm_zapad/` to `<config>/custom_components/erm_zapad/`.
3. Restart Home Assistant.

## Setup

1. **Settings → Devices & Services → + Add Integration → ERM Zapad Outage Check.**
2. **Settlement or district**: the name as it is written in the PDF, without the
   prefix. For `Част от КВ.ОБЕЛЯ` enter `Обеля`; for `Част от ИХТИМАН` enter
   `Ихтиман`. Upper/lower case does not matter. To see how your area is spelled,
   open a recent PDF from the [planned-outage page](https://info.ermzapad.bg/webint/vok/avplan.php)
   and search it.
3. **Notification targets**: pick one or more `notify.*` services. Leave empty if
   you only want the sensor and the event.
4. **Daily check time**: keep 21:15 unless you have a reason to change it. Submit.
5. Optional: run the action **ERM Zapad Outage Check: Check for outages**
   (`erm_zapad.check`) from **Developer tools → Actions** to test it right away.
   The sensor should change to `no outage` or to an outage line. Note that a test
   run also sends any outage or failure notification.

The setup form asks only for these three. Everything else, including the
calibration, has working defaults and can be changed later with **Configure**
on the integration card.

The first three settings are in the setup form; the others only under **Configure**.

| Setting | Meaning | Default |
| --- | --- | --- |
| Settlement or district (`keyword`) | Word(s) to look for, matched as a whole word | required |
| Notification targets (`notify_services`) | `notify.*` services to alert | none |
| Daily check time (`check_time`) | Local time of the daily check | `21:15:00` |
| Calibration date (`base_date`) | Anchor date for computing the daily `doc_id` | `2025-11-18` |
| Calibration doc_id (`base_doc_id`) | `doc_id` paired with the calibration date | `1481` |
| doc_id search window (`drift_window`) | How many ids either side of the computed one to try | `3` |
| Notification title (`notification_title`) | Title of the outage notification | `Електрохолд планирани спирания` |
| Endpoint (`endpoint`) | ERM Zapad PDF endpoint | `https://info.ermzapad.bg/webint/vok/avplan.php` |
| Outage line regex (`regex`) | Advanced, see below | built in |
| Sensor entity ID (`sensor_entity_id`) | Entity ID of the status sensor | `sensor.erm_zapad_next_outage` |

Only one instance can be configured.

## What you get

### Sensor `sensor.erm_zapad_next_outage`

| State | Meaning |
| --- | --- |
| an outage line, e.g. `Част от ИХТИМАН 14.11.2026 08:30 14.11.2026 16:30` | Your area is listed for tomorrow (first match if there are several) |
| `no outage` | Tomorrow's PDF was read and your area is not in it |
| `keyword without regex match` | The keyword is in the PDF, but no line with times could be parsed: check manually |
| `retrying` | A download failed; the check retries twice, 4 minutes apart |
| `calibration error` | No PDF dated tomorrow was found around the expected `doc_id` |
| `unknown` | No check has run since Home Assistant started |

Attributes: `outage_start`, `outage_end` (first match, `DD.MM.YYYY HH:MM`),
`outages` (all matches: `area`, `start`, `end`), `checked_at`, `pdf_date`,
`expected_pdf_date`, `doc_id`, `doc_id_drift`, `tried` (on failures).

The sensor is created by the integration on each start and is not a
registry entity, so it cannot be renamed in the UI. Use `sensor_entity_id`
if you need a different entity ID.

### Notifications

At most one per daily run:

- **Outage scheduled**: the matched line(s) with the time window.
- **Check failed**: no PDF for tomorrow could be found (site down, documents renumbered).
- **Outage found but not parsed**: the keyword is in the PDF but the times are not.
- **Check did not run**: a watchdog 10 minutes after the check time alerts if the
  sensor was not refreshed.

### Event `erm_zapad_checked`

Fired after every successful read. `match` is `true`, `false` or `"partial"`;
on a match the event also carries `match_line`, `outage_start`, `outage_end`,
`outages` and `doc_id`.

Example: a persistent notification on a match.

```yaml
automation:
  - alias: "Planned power outage tomorrow"
    triggers:
      - trigger: event
        event_type: erm_zapad_checked
        event_data:
          match: true
    actions:
      - action: persistent_notification.create
        data:
          title: "Planned power outage"
          message: "{{ trigger.event.data.outages | join('\n') }}"
```

## Calibration and troubleshooting

Normally you never touch the calibration. ERM Zapad numbers the daily PDFs with
a `doc_id` that grows by one per day. The integration computes today's id as
`base_doc_id + (today − base_date)`, checks the date printed in the PDF, and
tries the neighbouring ids if it does not match. The `doc_id_drift` attribute
shows the offset that worked. While it stays within `drift_window` (±3) nothing
needs to be done. Between November 2025 and November 2026 ERM skipped one day
(25.12.2025), and the drift has been 0 since then.

If the sensor shows `calibration error` for several days:

1. Find tomorrow's PDF by hand. This downloads `doc_id` 1900 (change the number
   and open the file to read the date in its header):

   ```sh
   curl -s -X POST -F action=showdocid -F doc_id=1900 \
     https://info.ermzapad.bg/webint/vok/avplan.php -o 1900.pdf
   ```

2. When you find the id whose PDF is dated **tomorrow**, set **Calibration date**
   to **today** and **Calibration doc_id** to that id in **Configure**.

Other checks:

- Debug logs: add `custom_components.erm_zapad: debug` under `logger:` → `logs:`.
- `keyword without regex match`: compare the line in the PDF with the regex. If
  ERM changed the layout, please open an issue with the line text.
- A run at the time ERM rewrites the next-day PDF (around 21:00) can fail once;
  the retries cover that.

### Custom regex

The default pattern is:

```text
([^\n]*?{keyword}[^\n]*?)\s+(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})\s+(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})
```

`{keyword}` is replaced by your keyword (escaped, whole word, spaces matching any
whitespace) and the pattern is case-insensitive. Groups: 1 area, 2 start, 3 end.
A pattern without `{keyword}` is used as written.

## Development

```sh
pip install pypdf pytest
pytest
```

The parsing code (`custom_components/erm_zapad/parser.py`) has no Home Assistant
imports and is covered by `tests/`. CI runs `hassfest`, the HACS validation and
the tests.

## На български

Неофициална интеграция за Home Assistant. Всяка вечер изтегля PDF файла с
планираните прекъсвания за следващия ден от сайта на ERM Запад (Електрохолд),
търси в него вашето населено място или квартал и ви изпраща известие с часовете.

Инсталация: HACS → Custom repositories → `https://github.com/mharizanov/ha-erm-zapad`
(тип Integration) → Download → рестарт. След това Settings → Devices & Services →
Add Integration → ERM Zapad Outage Check. Въведете името както е изписано в PDF
файла (за „Част от КВ.ОБЕЛЯ“ въведете „Обеля“) и изберете устройствата за известия.
Останалите полета оставете по подразбиране.

## License

[MIT](LICENSE). The Electrohold name and logo belong to their owner and are used
only to identify the data source.
