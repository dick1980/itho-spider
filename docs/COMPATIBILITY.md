# Compatibiliteitscontract vanaf 0.4.0

Een repositorynaam is geen Home Assistant-identiteit. Deze uitgave verandert alleen distributie, documentatie, testgegevens en standaardwaarden voor nieuwe invoer.

| Onderdeel | Vast contract |
| --- | --- |
| Domein / componentmap | `itho_spider` / `custom_components/itho_spider` |
| Configuratieversie | `VERSION = 2`, minorversie ongewijzigd |
| Configuratie unique_id | Het opgeslagen `spider_id` |
| Configuratiegegevens | `port`, `gateway_id`, `spider_id`, `name`, titel en entry_id behouden |
| Opties | `enable_control`, `wait_for_wakeup` en eventuele overige bestaande sleutels behouden |
| Gatewayapparaat | Identifier `("itho_spider", gateway_id)` |
| Spiderapparaat | Identifier `("itho_spider", spider_id)`, bestaande gateway als via-device |
| Entiteit | Platform + `itho_spider` + `<spider_id>_<key>` |

De 13 sleutels per Spider blijven: `climate`, `command_status`, `temperature`, `target_temperature`, `heating_demand`, `battery`, `operating_mode`, `program_mode`, `last_seen`, `gateway_connected`, `control_ready`, `battery_low`, `pair_gateway`.

De bestaande v1→v2-migratie blijft aanwezig: alleen configuratie-unique_id wordt het Spideradres en de configuratieversie wordt 2. Voor v2 is migratie een no-op. Hogere onbekende versies worden geweigerd zonder herschrijven. Een versienummer in `manifest.json` is onafhankelijk van de opgeslagen configuratieversie.

Tests zaaien 26 bestaande entiteiten en drie apparaten vóór setup, met aangepaste entity_id's, namen, gebieden en verborgen/uitgeschakelde entiteiten. Setup en volledig unload/setup moeten dezelfde register-ID's en opties houden. De echte gedeelde gatewaylaag gebruikt een gesimuleerde USB-transportlaag. Starten verstuurt geen temperatuur-, koppel- of relaisopdracht. De migratietests gebruiken de structuur van 0.4.0 met fictieve adressen, geen geëxporteerde gebruikersconfiguratie.

Dit beschermt de referenties die dashboards en automatiseringen gebruiken. Het test niet elk dashboard of elke gebruikersautomatisering. Vergelijk daarom ook de eigen registers en configuratiebestanden tijdens de echte overstap. Home Assistant bewaart gebruikersnamen en entity_id's in zijn [entiteitsregister](https://contributors.home-assistant.io/core/integrations/entity-registry/); de integratie schrijft die niet opnieuw.

USB-deling, de gezamenlijke grens van 12 radio-opdrachten per minuut, batterijwachtstand (maximaal 11 minuten / 3 verzendingen), strikte koppelprofielen, expliciete gateway-identificatie en alle beperkingen van het schrijfprofiel blijven intact. Een update opent geen koppelvenster. Normale statusantwoorden kunnen na ontvangen verkeer wel automatisch worden verzonden wanneer bediening aanstaat, zoals in 0.4.0.
