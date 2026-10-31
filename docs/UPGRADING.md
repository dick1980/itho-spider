# Bijwerken van 0.4.0 en terugvallen

Publicatie en installatie zijn afzonderlijke handelingen. Voer geen verwijderwizard uit en voeg geen vervangende configuraties toe. Koppel niet opnieuw. Verander geen radio-ID, seriële poort, naam of batterijoptie om bij voorbeelden in de README te passen.

## Voorbereiden

1. Maak een volledige Home Assistant-back-up en download die naar een veilige eigen locatie. Bewaar daarnaast de daadwerkelijk geïnstalleerde map `custom_components/itho_spider` buiten `custom_components`. Bewaar de bestaande 0.4.0-installatie-ZIP met checksum.
2. Noteer per configuratie entry_id, unique_id, versie, titel, gegevens en opties. Noteer apparaat-ID's/identifiers/via-device en alle entity_id's/unique_id's, inclusief uitgeschakelde entiteiten. Bewaar lokale kopieën van de configuratie-, apparaat- en entiteitsregisters uit de back-up; deel ze niet publiek.
3. Bewaar dashboards (zowel YAML als `.storage/lovelace*`), automatiseringen, scripts en overige configuratie. Noteer eventuele afwijkende bestandslocaties. Een code-update hoeft deze bestanden niet te wijzigen.
4. Controleer het gekozen releasebestand en de SHA256-checksum. Het installatiearchief bevat uitsluitend `custom_components/itho_spider/…`. Het bronarchief bevat ook tests en documentatie en is geen extra integratie.
5. Wacht tot geen temperatuuropdracht of koppel-/verwijderwizard actief is. Noteer de werkelijk gemelde modus en doeltemperatuur; start geen testopdracht. Een herstart annuleert een nog wachtende batterijopdracht.

## Handmatige update

1. Pak het gecontroleerde installatiearchief uit in een stagingmap buiten `custom_components`.
2. Stop Home Assistant Core voor een consistente bestandswissel. Op HA OS kan dit vanuit de Terminal/SSH-add-on met `ha core stop`; gebruik de passende beheerprocedure bij Container.
3. Bewaar de oude componentmap buiten `custom_components` en zet de volledige nieuwe map op exact `custom_components/itho_spider`. Voeg geen suffix aan domein of map toe. Laat `.storage`, YAML en databases ongemoeid. Voorkom een extra mapniveau zoals `itho_spider/itho_spider`.
4. Start Core (`ha core start` op HA OS). Controleer de logboeken en de versie in het manifest. Een algemene Home Assistant-update is hiervoor niet nodig.
5. Behoud alle bestaande configuraties. Wacht op verse radiostatus; bij batterijvoeding kan dit ongeveer tien minuten duren. Niet beschikbaar direct na herstart is geen reden om opnieuw te koppelen.

## Overname door HACS

Voeg alleen `https://github.com/dick1980/itho-spider` toe als custom repository van type Integration en kies de bedoelde release. Download/overschrijf de bestanden van dezelfde componentmap en herstart Core. HACS registreert de download afzonderlijk van de bestaande Home Assistant-configuraties. Verwijder niets uit Apparaten & diensten. Als HACS een onverwachte map of tweede domein aanbiedt, stop de overstap en gebruik de handmatige route. Deze HACS-overname is nog niet live getest.

## Controleren zonder bediening

- Vergelijk entry_id, configuratie-unique_id, versie 2, data en alle opties exact met vooraf.
- Vergelijk apparaat-ID's, entity_id's, unique_id's, koppelingen, gebieden, eigen namen en uitgeschakelde/verborgen entiteiten. Gebruik aantallen alleen als extra controle: gelijke aantallen bewijzen geen gelijke identificaties.
- Controleer bestaande dashboardkaarten en automatiseringsdoelen op ontbrekende referenties zonder acties uit te voeren. Vergelijk opgeslagen dashboard- en automatiseringsbestanden met de back-up.
- Controleer passief USB-status, verse gemeten waarden, gemelde doeltemperatuur/modus, batterijwachtstand en foutmeldingen. Een fysieke relaiskoppeling wordt hiermee niet bewezen; voer voor deze software-overstap geen afmelding, fabrieksreset of relaisaanmelding uit.

## Terugval

Bij ontbrekende/gewijzigde identificaties, verloren opties, aanhoudende verbindingsfouten of onverwacht gedrag: stop Core, verplaats de kandidaatcomponent naar een aparte map buiten `custom_components` en plaats de bewaarde 0.4.0-component terug op het oorspronkelijke pad. Start Core en herhaal de passieve controles. Laat de configuratie- en entiteitsregisters staan: 0.4.1 gebruikt hetzelfde schema als 0.4.0. Een reguliere code-terugval vereist dus geen herstel van een volledige back-up en geen herkoppeling.

Als er buiten deze procedure toch configuraties verwijderd of registers gewijzigd zijn, kan code-terugval dat niet herstellen. Stop dan en herstel de bijpassende volledige Home Assistant-back-up via de gebruikelijke herstelprocedure. Bewerk nooit losse `.storage`-bestanden terwijl Core draait. Kies bij HACS zo nodig de vorige release via opnieuw downloaden; als die nog niet publiek bestaat, gebruik de eigen 0.4.0-back-up en voorkom dat een automatische update die direct weer vervangt.
