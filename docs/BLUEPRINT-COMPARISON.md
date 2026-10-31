# Gerichte vergelijking met de Spider-blueprint

Beoordeling: 31 oktober 2026. Uitkomst: **geen concrete overname van beschermde uitwerking aangetroffen; toestemming van de blueprintauteur is voor deze aangetroffen overeenkomsten geen onderbouwde verplichte publicatiestap**. De eerdere blokkade op alleen het ontbreken van een upstreamlicentie wordt ingetrokken. De gekozen MIT-licentie wordt toegepast op de eigen projectcode, met behoud van bronvermelding en bestaande derdepartijvermeldingen.

Dit is een technische herkomstbeoordeling met een beperkte juridische duiding, geen bindend juridisch oordeel of volledige vrijwaring voor alle mogelijke rechten. Zij betreft de hieronder geïdentificeerde bron en de huidige implementatie, niet willekeurige toekomstige kopieën of andere versies.

## Bronnen en methode

- [spider.yaml v1.18](https://github.com/Onl1ne1373/home-assistant-blueprints/blob/fbe82495e1f72ab91d62969ce863668dea0c31e0/spider.yaml), commit `fbe82495e1f72ab91d62969ce863668dea0c31e0`.
- De opgehaalde volledige bron is gecontroleerd tegen Git-blob `f3d2ce96699416e1ccd6d1687499f75237fb3f91`. SHA256: `9f4d3b856c44233588e29f189b7190da5edd327ec532154c7255a884542a2832`.
- Vergeleken met `protocol.py`, `binding.py`, `controller.py`, hun regressietests en de GUI/documentatie van deze integratie.
- Handmatige vergelijking van berichtinhoud, berekeningen, beslislogica, architectuur en tekst. Daarnaast een tekstscan over 33 bestanden: alle Python-/JSON-bron- en testbestanden plus README. Er waren geen gelijke getrimde regels van minstens 30 tekens en geen gelijke reeksen van acht alfabetische woorden. Dat zijn controlehulpmiddelen, geen bewijs van zelfstandige creatie: vertaalde of anders geformuleerde overname moet inhoudelijk worden beoordeeld.
- De blueprint zelf, zijn instructies en gebruikersvoorbeelden worden niet opgenomen in de publieke distributie. De review doet geen claim dat de blueprint nooit is geraadpleegd; die invloed staat juist expliciet in de bron.

## Vergelijking per onderdeel

| Onderdeel en blueprintverwijzing | Bevinding in deze integratie | Beoordeling |
| --- | --- | --- |
| `01FF`-inhoud ([regels 143–162](https://github.com/Onl1ne1373/home-assistant-blueprints/blob/fbe82495e1f72ab91d62969ce863668dea0c31e0/spider.yaml#L143-L162), ook 197–218) | De twee velden op byte-offsets 3 en 4 worden ingevuld; alle overige 24 bytes zijn gelijk aan het blueprintprofiel. `build_setpoint_command` in `protocol.py` bouwt het bericht met eigen validatie. | Bewuste overname van een numeriek protocol-/bedieningsprofiel. Niet presenteren als volledig onafhankelijk ontdekt. Geen overgenomen Jinja-expressie of YAML-actieblok. |
| Tweede temperatuur ([regels 107–115](https://github.com/Onl1ne1373/home-assistant-blueprints/blob/fbe82495e1f72ab91d62969ce863668dea0c31e0/spider.yaml#L107-L115)) | `build_setpoint_command` bewaart de tweede gemelde temperatuur; de blueprint berekent doel plus één. De integratie controleert beide waarden, handmatig verwarmen en verse status. | De specifieke keuze voor een berekende tweede temperatuur is juist niet overgenomen. |
| Gatewayadres en `1FC9` ([regels 110 en 120–141](https://github.com/Onl1ne1373/home-assistant-blueprints/blob/fbe82495e1f72ab91d62969ce863668dea0c31e0/spider.yaml#L110-L141)) | `address_hex` gebruikt een bitshift/OR voor type en serienummer. `gateway_accept` voegt de protocolprefix toe. `is_gateway_offer` vergelijkt volledige, waargenomen tupelprofielen en ingebedde adressen. Een expliciet tijdvenster en bevestiging begrenzen het koppelen. | Dezelfde adreswiskunde en berichtindeling. De eenvoudige gedeeltelijke packetmatch van de blueprint is niet de implementatie van de integratie. |
| Antwoord op `W/22C9` ([regels 164–195](https://github.com/Onl1ne1373/home-assistant-blueprints/blob/fbe82495e1f72ab91d62969ce863668dea0c31e0/spider.yaml#L164-L195)) | `build_local_setpoint_ack` valideert het ontvangen bericht en bewaart beide temperatuurvelden. Het antwoordtype is hetzelfde; de vaste tweede temperatuur uit de blueprint wordt niet gebruikt. | Gedeelde protocolfunctie; andere payloadopbouw en eigen validatie. |
| Herhalingen ([regels 197–218](https://github.com/Onl1ne1373/home-assistant-blueprints/blob/fbe82495e1f72ab91d62969ce863668dea0c31e0/spider.yaml#L197-L218)) | Beide hebben een grens van drie verzendingen. De integratie wacht bij directe bediening op bevestiging met een timeout van drie seconden en stopt bij succes; batterijbediening wacht op radiostatus en annuleert bij lokale wijzigingen. | Het getal drie en herhalen als betrouwbaarheidstechniek zijn gedeeld. De vaste blueprintreeks met een seconde vertraging is niet vertaald naar de controller. |
| Automatiseringsstructuur ([regels 95–105 en 219–247](https://github.com/Onl1ne1373/home-assistant-blueprints/blob/fbe82495e1f72ab91d62969ce863668dea0c31e0/spider.yaml#L95-L105)) | Geen Generic Thermostat, schedule-helper of ramses_cc-eventautomatisering. Eigen HA-platformen, protocolparser, controller, gedeelde USB-transportlaag en configuratiewizards. | Geen overeenkomstige concrete programmastructuur aangetroffen. Gemeenschappelijke verzending/ontvangst volgt de gewenste apparaatfunctie. |
| Instructies, labels en voorbeelden ([regels 1–93](https://github.com/Onl1ne1373/home-assistant-blueprints/blob/fbe82495e1f72ab91d62969ce863668dea0c31e0/spider.yaml#L1-L93)) | Eigen documentatie en formulieren; geen blueprint-instructieblokken, voorbeeldentiteiten of beschrijvende teksten aangetroffen in de distributie. Testgevallen zijn eigen tests; gedeelde verwachte bytes controleren het protocolprofiel. | Geen aangetroffen tekstuele overname van betekenis. Gewone termen zoals Spider, gateway en setpoint zijn niet doorslaggevend. |

## Het punt dat wél aandacht verdient: de vaste bytes

De overeenkomst van 24 bytes is echt en wordt niet weggepoetst. Dit zijn berichtgegevens die de thermostaat ontvangt, geen uitvoerbare code voor een Python-, YAML- of Jinja-engine. Ze leggen een functioneel bedieningsprofiel vast. De bron en herkomst van dit profiel blijven vermeld.

Niet alle velden zijn volledig verklaard. Deze review bewijst daarom niet dat iedere byte de enige technisch mogelijke waarde is of dat iedere combinatie op hardware werkt. Evenmin mag uit een numerieke vorm alleen worden afgeleid dat iets nooit auteursrechtelijk beschermd kan zijn. In deze concrete korte berichtindeling is echter geen aanwijzing voor een creatieve uitwerking aangetroffen naast de functionele parameterkeuze en protocolkennis. Het identiek houden daarvan ondersteunt compatibiliteit; willekeurig veranderen om gelijkenis te vermijden zou de technische betrouwbaarheid aantasten.

## Juridisch kader en toepassing

[Artikel 1 lid 2–3 van Richtlijn 2009/24/EG](https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX%3A32009L0024) onderscheidt de concrete uitwerking van software van de achterliggende ideeën en interfacebeginselen, en stelt oorspronkelijkheid als criterium. Dit betekent niet dat elke willekeurige kopie uit broncode toegestaan is.

In [SAS Institute/WPL, C‑406/10, punten 35–46 en 65–70](https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=celex%3A62010CJ0406) onderscheidt het Hof functionaliteit/formaten van beschermde uitwerking en bespreekt het ook overname van creatieve elementen uit documentatie. De zaak had andere feiten, waaronder ontbreken van toegang tot de oorspronkelijke broncode. Deze integratie heeft de blueprint als bron gebruikt; de uitspraak is dus geen automatische vrijbrief. De beoordeling hier berust op wat in de gerichte vergelijking daadwerkelijk overeenkomt.

Mijn toepassing van dat kader: de aangetroffen overeenkomsten zijn het protocolprofiel, adreswiskunde en algemene bedieningsfuncties. Er is geen concrete aanwijzing gevonden dat beschermde blueprintcode, tekst of een creatieve selectie/ordening is overgenomen. Alleen een ontbrekende licentie rechtvaardigt daarom niet de eerdere verplichte toestemmingsstap. Een vrijwillig bedankje of toestemmingsverzoek blijft mogelijk, maar wordt niet meer als releasevoorwaarde gesteld.

## Gevolgen

- MIT wordt toegepast op de eigen projectcode met `Copyright (c) 2026 jdezine`. Dit herlicentieert de blueprint niet en claimt geen exclusieve rechten op protocolfeiten.
- De bronvermelding naar Onl1ne1373, de vaste revisie en de bestaande ramses_rf MIT-vermelding blijven behouden. Bronvermelding zou op zichzelf geen vervanging zijn voor toestemming als later wél beschermde overname wordt aangetroffen.
- `provenance_reviewed` betekent dat deze gerichte technische beoordeling is afgerond; het is geen juridisch certificaat of bewering dat de auteur toestemming heeft gegeven.
- Geen protocol-, ID-, migratie-, configuratie- of runtimewijziging. Geen publicatie, contact met derden of wijziging van de live installatie.
- Heropen deze beoordeling wanneer een latere wijziging nieuwe upstreamcode, teksten, voorbeelden of afbeeldingen overneemt.
