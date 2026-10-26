# Portföljvärdering

En webbapp som värderar dina innehav och ger en färgkodad signal (Öka / Behåll / Minska / Granska) och ett
index där 100 = rimligt värderad. Innehaven visas i tre listor – aktier, fonder och ETF:er – sorterade efter värde.

- **Aktier** bedöms med tre mått: tillväxten som dagens pris förutsätter jämfört med analytikernas förväntade
  tillväxt (DCF), FCF-yield mot räntan och P/E mot egen historik. Hur måtten vägs styrs av vald strategi (A–D),
  som väljs i sidomenyn och sparas.
- **Fonder och ETF:er** får en ombalanseringssignal mot målvikt.
- **Avanza-import:** ladda upp Avanzas export av innehav, så föreslår appen Yahoo-tickers via ISIN.

Data hämtas från Yahoo Finance och cachas i 24 timmar.

## Filer

| Fil | Innehåll |
|---|---|
| `app.py` | Själva appen (gränssnittet) |
| `data.py` | Hämtar data från Yahoo Finance |
| `valuation.py` | Värderingslogiken och strategierna A–D |
| `storage.py` | Sparar innehav och inställningar (GitHub eller lokalt) |
| `avanza.py` | Läser Avanzas export av innehav |
| `requirements.txt` | Python-paket som behövs |
| `.streamlit/config.toml` | Utseende (valfri) |
| `.streamlit/secrets.toml.exempel` | Mall för GitHub-nyckeln (se steg 4) |

## Lägga ut appen på Streamlit Community Cloud (gratis)

**1. Lägg koden på GitHub**
- Skapa ett konto på github.com om du inte har ett.
- Skapa ett nytt repo, t.ex. `aktie-app`, och välj **Private**.
- Klicka *Add file → Upload files* och dra in alla filer och mappen `.streamlit`. Klicka *Commit changes*.
  (Mappen `.streamlit` är dold på vissa datorer – dra och släpp fungerar. Den är valfri.)

**2. Skapa appen**
- Gå till share.streamlit.io och logga in med ditt GitHub-konto.
- Klicka *Create app*, välj ditt repo, grenen `main` och filen `app.py`. Klicka *Deploy*.
- Första starten tar några minuter medan paketen installeras.

**3. Gör appen privat**
- I appens meny: *Settings → Sharing*. Välj att bara inbjudna kan se appen och lägg till din e-postadress.
  Gratisnivån tillåter en privat app.

**4. Spara innehaven permanent (viktigt)**

Streamlit Cloud har ingen permanent disk, så utan detta steg försvinner innehaven när appen startas om.
Appen sparar dem i stället i en egen gren (`data`) i ditt repo.
- På GitHub: *Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token*.
- Under *Repository access*: välj bara ditt `aktie-app`-repo.
- Under *Permissions → Contents*: välj **Read and write**. Skapa nyckeln och kopiera den.
- I Streamlit: *Settings → Secrets*. Klistra in följande (med din nyckel och ditt användarnamn):

```toml
[github]
token = "github_pat_..."
repo = "ditt-anvandarnamn/aktie-app"
branch = "data"
```

Appen visar under fliken *Innehav* var den sparar, så du kan kontrollera att det står GitHub.

## Köra appen på din egen dator

```
pip install -r requirements.txt
streamlit run app.py
```

Utan GitHub-inställning sparas innehaven i mappen `sparat/` bredvid appen.

## Bra att veta

- **Tickers enligt Yahoo:** USA `MSFT`, Sverige `VOLV-B.ST`, ETF:er t.ex. `VWCE.DE`. Svenska fonder har koder som
  `0P0000XXXX.ST` – sök på fondens namn på finance.yahoo.com. Saknas en kurs kan du fylla i den manuellt.
- **Cachning:** data hämtas högst en gång per dygn per innehav. Knappen *Hämta ny data* tvingar fram en ny hämtning.
  Hämta inte för ofta – Yahoo kan blockera tillfälligt vid många anrop.
- **Om Yahoo blockerar från molnet:** byt datakälla (t.ex. EODHD) – det är bara `data.py` som behöver ändras –
  eller kör appen på din egen dator.
- **Begränsningar:** Yahoo är gratis men inofficiellt. P/E-historiken räcker oftast 4–5 år. Banker och
  försäkringsbolag passar dåligt för FCF-måttet. Verktyget är ett beslutsstöd, inte investeringsrådgivning.
