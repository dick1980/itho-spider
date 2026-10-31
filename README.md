# Itho Spider voor Home Assistant

Custom integratie voor meerdere Itho Spiders die één rechtstreeks aangesloten evofw3 USB-gateway delen. Iedere Spider krijgt een eigen configuratie en thermostaat. De integratie leest de thermostaatstatus en kan de gewenste temperatuur aanpassen wanneer de Spider in **handmatig verwarmen** staat.

Een onafhankelijke community-integratie voor Home Assistant. De broncode is beschikbaar onder de [MIT-licentie](LICENSE).

## Hardware en vereisten

- Home Assistant **2026.10.4**; dit is de conservatieve ondergrens in de distributiemetadata én de geteste versie. Andere versies zijn niet geverifieerd.
- Een Itho Spider met het ondersteunde RAMSES-radio-/gatewayprofiel en een rechtstreeks aangesloten, compatibele evofw3 USB-radio. Het geteste firmwareprofiel is evofw3 0.7.1. Deze integratie levert of flasht geen firmware. Een willekeurige USB-seriële adapter is geen geschikte radio.
- Een lokaal POSIX-serieel apparaat onder `/dev/`, toegankelijk voor Home Assistant; USB-doorgifte bij VM/container. Bij voorkeur een stabiel `/dev/serial/by-id/`-pad. Windows COM-poorten en netwerkproxies worden niet ondersteund.
- Je eigen gatewayadres (`18:nnnnnn`) en Spideradres (`21:nnnnnn`). Gebruik bestaande configuratiegegevens of eerder vastgestelde apparaat-ID's; voorbeelden hieronder zijn fictief. Er is geen algemene RF-ontdekking. Seriële monitors mogen niet gelijktijdig dezelfde poort bezetten.
- De Spider blijft verantwoordelijk voor de bestaande verwarming-/OpenTherm-/relaisinstallatie. Een bestaande Honeywell BDR91-koppeling staat los van de gatewaykoppeling en moet intact blijven.

## Installeren

1. Sluit de evofw3 USB-gateway aan op de computer waarop Home Assistant draait. Bij een virtuele machine of container moet het USB-apparaat aan die omgeving worden doorgegeven.
2. Kopieer de map `custom_components/itho_spider` naar de configuratiemap van Home Assistant. De uiteindelijke structuur moet zijn:

   ```text
   /config/custom_components/itho_spider/__init__.py
   /config/custom_components/itho_spider/manifest.json
   /config/custom_components/itho_spider/translations/nl.json
   ```

3. Herstart Home Assistant.
4. Ga naar **Instellingen → Apparaten & diensten → Integratie toevoegen → Itho Spider**.
5. Vul het lokale USB-poortpad en de apparaat-ID's in.

| Instelling | Betekenis |
| --- | --- |
| USB-poort | Het pad op de Home Assistant-host, bij voorkeur `/dev/serial/by-id/...` |
| Gateway-ID | Je eigen `18:`-adres; geen vooringevulde waarde |
| Spider-ID | Je eigen `21:`-adres; geen vooringevulde waarde |
| Naam | Zelfgekozen naam, standaard `Itho Spider` |
| Bediening inschakelen | Standaard aan; uitzetten laat de integratie alleen luisteren |

Het poortpad van een andere computer, zoals `/dev/cu.usbmodem...` op een Mac, is niet automatisch het juiste pad op de Home Assistant-host. Gebruik daar het daadwerkelijk aangesloten apparaat. Netwerkpoorten, `socket://` en `rfc2217://` worden niet ondersteund.

De configuratie controleert met de lokale opdracht `!I` of het gateway-ID klopt. Dat is geen radiobericht. De toevoegwizard laat je kiezen tussen een nieuwe radiokoppeling en toevoegen zonder koppelen. Alleen wanneer je de koppelprocedure start, wordt een venster van drie minuten geopend. Er wordt geen firmware geflasht en er worden geen gateway-instellingen gewijzigd.

De poort mag maar door één toepassing tegelijk worden gebruikt. Schakel het gebruik van dezelfde USB-gateway door bijvoorbeeld `ramses_cc`, een add-on of een seriële monitor uit voordat je deze integratie start.

### HACS

Voeg `https://github.com/dick1980/itho-spider` toe als **Custom repository → Integration** in HACS en download Itho Spider. Herstart Home Assistant. Voeg daarna via **Instellingen → Apparaten & diensten** de integratie toe. De repository staat niet in de HACS-standaardcatalogus; installatie via de HACS-client is nog niet end-to-end getest. Kies een gepubliceerde release; de beschikbare versies staan op de [releasepagina](https://github.com/dick1980/itho-spider/releases).

## Spider toevoegen en gateway koppelen

Kies **Voeg hub toe** op de integratiepagina. Vul dezelfde poort en hetzelfde gatewayadres in voor een extra Spider, maar diens eigen Spideradres en naam. Kies bij een Spider die uitsluitend op batterijen werkt de batterijoptie; laat deze uit voor de OpenTherm-gevoede Spider.

1. Kies **Nieuwe radiokoppeling maken**, of **Toevoegen zonder koppelen** als de Spider al gekoppeld is of je later wilt koppelen.
2. Noteer de huidige doeltemperatuur en ga naar de Spider. Start dan het koppelvenster met **Verzend**. De wizard toont de instructies en wacht maximaal drie minuten op radiobevestiging.
3. Plaats de batterijen opnieuw, activeer binnen twee minuten het scherm en houd het logo circa vijf seconden vast.
4. Tik uitsluitend op het **knipperende HUISJE**, zodat de andere symbolen verdwijnen, en bevestig met het logo. Wacht op signaalsterkte 1–5. Laat de BDR91 en de temperatuur-/ketelmodulekeuze ongemoeid.
5. Na de radiobevestiging vraagt de wizard je de genoteerde doeltemperatuur te controleren en zo nodig te herstellen. Bevestig deze controle om de configuratie af te ronden.
6. Bij een time-out kun je opnieuw proberen of later koppelen. Sluiten annuleert het open venster; een reeds voltooide fysieke koppeling blijft bestaan.

Een bestaande Spider beheer je via **Configureren → Gateway koppelen / verbinding controleren**. Als deze sinds het verbinden al status aan de gateway heeft gestuurd, opent direct het bevestigingsscherm. De bestaande knop **Gateway koppelen (3 minuten)** blijft beschikbaar. Bediening wacht altijd op actuele thermostaatgegevens en handmatig verwarmen.

## Spider verwijderen

Ga bij de bedoelde Spider naar **Configureren → Spider verwijderen**. Er zijn twee afzonderlijke procedures:

- **Alleen uit Home Assistant verwijderen:** na je expliciete bevestiging verwijdert Home Assistant deze configuratie en haar entiteiten. De gatewaykoppeling op de Spider blijft bestaan.
- **Gateway afmelden en daarna uit Home Assistant verwijderen:** de wizard pauzeert eerst de bediening van alleen deze Spider, maximaal tien minuten. Hij begeleidt je bij het fysiek afmelden via het **permanent brandende HUISJE**. Pas na jouw bevestiging van die controle verschijnt een tweede bevestiging voor verwijderen uit Home Assistant.

Home Assistant kan de fysieke afmelding niet automatisch bewijzen. De wizard vraagt daarom wat je op de Spider hebt gecontroleerd. Gebruik geen fabrieksreset en raak de BDR91, TEMPERATUUR en VENTILATIE niet aan. Herstel zo nodig de genoteerde doeltemperatuur.

Bij annuleren blijft de configuratie bestaan; na de afmeldinstructies vereist bediening opnieuw status aan de gateway. Een al uitgevoerde fysieke afmelding wordt niet teruggedraaid. Na tien minuten verloopt de procedure en moet je haar opnieuw openen. Een lopende temperatuuropdracht blokkeert het starten van de fysieke afmeldprocedure.

Andere Spiders blijven dezelfde USB-verbinding gebruiken. Ook als je de eerst toegevoegde Spider verwijdert, blijft het gedeelde gateway-apparaat voor de overige configuraties behouden. Controleer zelf dashboard- en automatiseringsverwijzingen naar entiteiten die je verwijdert. De standaard Home Assistant-actie **Verwijderen** meldt de gateway niet fysiek af; gebruik bovenstaande wizard voor de begeleide procedure.

## Gedeelde gateway

De gateway- en ketelmodule-aanmelding zijn afzonderlijke procedures; raadpleeg de [Itho Spider-handleiding, §5.2.3](https://ithodaalderop.compano.com/Data/Environments/000001/Attachment/Bijlage/A07_Regelapparatuur/A07_01_01_01_Thermostaten/B01_05_MAN/01-00244-007%20Handleiding%20Spider%20Connect%20NLBE.pdf). De integratie kan behoud van de fysieke relaiswerking niet softwarematig bewijzen.

De gateway bewaakt een gezamenlijke grens van twaalf radio-opdrachten per minuut. Herladen of uitschakelen van één configuratie sluit de USB-poort alleen als geen andere Spider deze gebruikt. Een USB-onderbreking maakt alle gekoppelde configuraties tijdelijk onbeschikbaar; de verbinding wordt gedeeld hersteld.

## Wat verschijnt in Home Assistant?

- Een knop om de gateway-aanmelding voor precies deze Spider drie minuten toe te staan.
- Een climate-entiteit voor de Spider, met de gemeten en gewenste temperatuur.
- Sensoren voor gemeten temperatuur, gewenste temperatuur, warmtevraag, bedrijfsmodus, programmamodus, batterijpercentage en het laatste ontvangen bericht.
- Diagnostische binaire sensoren voor USB-verbinding, gereedheid voor bediening en lage batterijspanning.

Een meetwaarde blijft onbekend totdat de Spider die rapporteert. Er wordt bij opstarten geen temperatuur zoals 18 °C aangenomen of teruggestuurd. De integratie wacht op actuele berichten en toont na verlies van de verbinding of te lang uitblijven van berichten dat de thermostaat niet beschikbaar is.

De gemelde stand kan verwarmen, koelen of uit zijn. Home Assistant toont die gemelde stand; omschakelen tussen deze standen gebeurt op de Spider zelf. Ook het klokprogramma en tijdelijke programma-instellingen worden alleen weergegeven.

## Temperatuur bedienen

Een Spider die alleen op batterijen werkt, luistert niet voortdurend. Kies bij **Configureren → Bedieningsinstellingen → Wachten op batterijgevoede thermostaat** voor deze Spider de wachtstand. Schakel deze optie in bij uitsluitend batterijvoeding; laat haar uit bij OpenTherm-voeding. Bestaande opgeslagen opties worden bij een update niet aangepast.

In de wachtstand wordt een opdracht één keer direct aangeboden en daarna maximaal elf minuten bewaard voor de volgende statusvraag van de Spider. Die kan ongeveer elke tien minuten komen. Home Assistant toont **Opdrachtstatus: Wachten op thermostaat** en het attribuut `pending_temperature`; de weergegeven doeltemperatuur verandert pas na bevestiging. Een nieuwe keuze vervangt de vorige. Een lokale temperatuur- of moduswijziging, verbindingsverlies, herladen of verlopen van de wachttijd annuleert de wachtende opdracht. Er worden maximaal drie radio-opdrachten voor één keuze verstuurd; er wordt geen opdracht op schijf bewaard of na herstart opnieuw afgespeeld.

Zet de Spider zelf op **handmatig verwarmen**. Zodra de gateway geïdentificeerd is en actuele statusberichten van de gekoppelde Spider zijn ontvangen, wordt **Gereed voor bediening** ingeschakeld.

Je kunt dan de gewenste temperatuur instellen tussen **5 en 30 °C**, in stappen van **0,5 °C**. De integratie wacht op een nieuw statusbericht van de Spider dat de ingestelde temperatuur bevestigt. Een USB-echo van het verzonden bericht telt niet als bevestiging. Directe bediening probeert maximaal drie keer en meldt bij uitblijven van bevestiging een fout. In de wachtstand toont de opdrachtstatus na de begrensde wachttijd **Niet bevestigd**. Controleer dan de werkelijke stand op het scherm van de Spider voordat je opnieuw probeert.

Bij een lokale temperatuurwijziging op de Spider neemt Home Assistant de gemelde waarde over. Een afwijkende lokale wijziging krijgt voorrang op een nog lopende opdracht vanuit Home Assistant. Een geldige directe `W/22C9`-terugmelding die overeenkomt met de gevraagde temperatuur geldt als bevestiging; hetzelfde berichttype kan dus ook het antwoord op een opdracht zijn.

Als bediening is ingeschakeld en de actuele status handmatig verwarmen aangeeft, beantwoordt de integratie ook geldige `RQ/01FF`-statusvragen. Een directe lokale `W/22C9`-temperatuurwijziging voor verwarmen kan meteen worden bevestigd door de gecontroleerde berichtinhoud terug te sturen, ook voordat alle overige status beschikbaar is. Dit zijn automatische radioberichten, ook wanneer je zelf geen temperatuuractie in Home Assistant start. Via **Configureren** bij de integratie kun je bediening uitschakelen; dan worden geen radioberichten verzonden.

De integratie schrijft geen aan/uit- of koelmodus, klokprogramma, tijd of presets. De bestaande bekabelde aansluiting op de verwarmingsinstallatie of pomp blijft zelfstandig werken; deze integratie bedient geen apart pomprelais. Warmtevraag is de door de Spider gemelde vraag, geen meting van het elektrische verbruik van de pomp.

## Grenzen van deze versie

- Meerdere Spiders kunnen één gateway delen. Andere thermostaten of Autotemp-relaties worden niet aangestuurd.
- Het gebruikte `01FF`-schrijfprofiel is gebaseerd op een bestaand Spider-profiel. Een deel van de velden is nog niet volledig verklaard; behoud van iedere apparaatinstelling kan niet worden gegarandeerd.
- De tweede gemelde temperatuur wordt behouden in opdrachten. De Spider kan dit veld in zijn antwoord aanpassen. De integratie neemt die geldige terugmelding over; er wordt geen vaste afstand tussen de twee velden afgedwongen. De betekenis en acceptatie van alle mogelijke combinaties zijn niet op hardware vastgesteld.
- De gateway-identiteit wordt bij iedere verbinding opnieuw gecontroleerd. Na een onderbreking zijn opnieuw actuele Spider-berichten nodig voordat bediening mogelijk is.
- Er is geen automatische koppeling, geen herstel van een oude gewenste temperatuur bij opstarten en geen algemene interface om willekeurige gateway-opdrachten te sturen.

## Problemen onderzoeken

**De gateway kan niet worden geopend:** controleer het USB-pad, USB-doorgifte naar Home Assistant en of een andere toepassing de poort bezet houdt.

**Het gateway-ID komt niet overeen:** de configuratie meldt welk ID daadwerkelijk is ontvangen. Controleer of de bedoelde gateway is aangesloten en of het ingestelde ID klopt.

**USB verbonden, maar nog geen temperatuur:** de gateway is bereikbaar, maar er is nog geen bruikbaar bericht van de ingestelde Spider ontvangen. Controleer het Spider-ID, de bestaande koppeling en het radiobereik.

**Wel temperatuur, maar bediening niet gereed:** controleer of de Spider handmatig verwarmt. Bediening vereist actuele status én beide geldige gemelde temperatuurvelden. Alleen een temperatuurmeting is onvoldoende.

**Een opdracht is niet bevestigd:** de gemelde temperatuur wordt niet alvast aangepast. Controleer de thermostaat zelf en bekijk de attributen `control_ready`, `pending_temperature` en `last_command_result` van de climate-entiteit.

Via het integratiemenu kun je diagnostiek downloaden. Die bevat verbindingsstatus, tellers en de laatste relevante `01FF`-status; configuratie-identificaties en het seriële poortpad worden geredigeerd. Het Home Assistant-logboek geeft verdere fouten onder `custom_components.itho_spider`.

## Ontwikkeling en tests

Zie [CONTRIBUTING.md](CONTRIBUTING.md) voor ontwikkeling en tests en [CHANGELOG.md](CHANGELOG.md) voor wijzigingen.

De seriële verbinding gebruikt 115200 baud, 8N1 en CRLF, met exclusieve toegang. De integratie gebruikt geen 1200-baud-reset en pulst de modemlijnen niet; DTR wordt bij openen actief gezet voor de USB-console. De protocoltests werken met gesynthetiseerde radioadressen. Transporttests gebruiken mocks en een software-PTY, nooit fysieke hardware.

Diagnostiek redigeert de vaste configuratievelden, maar foutteksten en gedeelde logs kunnen alsnog adressen of paden bevatten. Controleer bestanden vóór je ze deelt. Upload geen Home Assistant-back-up, `.storage`, tokens, complete radio-opnamen of screenshots met persoonlijke gegevens. Zie [SECURITY.md](SECURITY.md).
