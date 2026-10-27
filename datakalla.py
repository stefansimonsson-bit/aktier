# -*- coding: utf-8 -*-
"""Hämtar kurser, fundamenta och analytikerestimat från EODHD.

Allt som returneras är vanliga Python-typer så att det kan cachas.
EODHD:s fältnamn tolkas försiktigt – saknas något blir värdet None och det noteras.
"""
import datetime as dt
import math
import time

import requests

BAS = "https://eodhd.com/api"
RAPPORT_LAG_KVARTAL = 45   # dagar efter kvartalets slut innan siffrorna antas vara kända
RAPPORT_LAG_AR = 75        # dagar efter räkenskapsårets slut


class EodhdFel(Exception):
    pass


# ---------------------------------------------------------------- hjälpfunktioner
def _tal(v):
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _datum(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _get(endpoint, nyckel, params=None, timeout=40):
    p = {"api_token": nyckel, "fmt": "json"}
    p.update(params or {})
    r = requests.get(f"{BAS}/{endpoint}", params=p, timeout=timeout)
    if r.status_code in (401, 403):
        raise EodhdFel("EODHD godkände inte nyckeln, eller så ingår datan inte i abonnemanget.")
    if r.status_code == 402:
        raise EodhdFel("Abonnemanget saknar åtkomst till den här datan.")
    if r.status_code == 429:
        raise EodhdFel("Dagens anropskvot hos EODHD är slut.")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return None


def _poster(d):
    """EODHD lagrar ofta tidsserier som {datum: {...}} eller {"0": {...}}. Returnerar [(datum, post)] nyast först."""
    if not isinstance(d, dict):
        return []
    ut = []
    for k, v in d.items():
        if not isinstance(v, dict):
            continue
        dd = _datum(v.get("date") or v.get("dateFormatted") or k)
        if dd:
            ut.append((dd, v))
    return sorted(ut, key=lambda x: x[0], reverse=True)


# ---------------------------------------------------------------- tickers
# Yahoo-ändelse -> EODHD-börskod
YAHOO_TILL_EODHD = {
    "DE": "XETRA", "L": "LSE", "AX": "AU", "T": "TSE", "TO": "TO", "V": "V", "HK": "HK", "SW": "SW",
    "PA": "PA", "AS": "AS", "MI": "MI", "MC": "MC", "BR": "BR", "LS": "LS", "VI": "VI", "IR": "IR",
    "HE": "HE", "CO": "CO", "OL": "OL", "ST": "ST", "IC": "IC", "F": "F",
}
EODHD_BORSER = set(YAHOO_TILL_EODHD.values()) | {"US", "EUFUND", "FOREX", "INDX", "NASDAQ", "NYSE"}
LAND_TILL_BORS = {"SE": "ST", "US": "US", "NO": "OL", "DK": "CO", "FI": "HE", "DE": "XETRA", "GB": "LSE"}


def till_eodhd(ticker):
    """Översätter en ticker (Yahoo- eller EODHD-format) till EODHD-format, t.ex. MSFT -> MSFT.US."""
    t = str(ticker).strip().upper()
    if "." in t:
        bas, suf = t.rsplit(".", 1)
        if suf in EODHD_BORSER:
            return t
        if suf in YAHOO_TILL_EODHD:
            return f"{bas}.{YAHOO_TILL_EODHD[suf]}"
        return t
    return f"{t}.US"


def sok(fraga, nyckel, isin=None, typ=None):
    """Söker värdepapper hos EODHD. Returnerar (ticker, status)."""
    if not fraga:
        return None, "Ej hittad"
    res = _get(f"search/{requests.utils.quote(str(fraga))}", nyckel, {"limit": 15}) or []
    if not isinstance(res, list) or not res:
        return None, "Ej hittad"
    land = (isin or "")[:2].upper()
    onskad_bors = LAND_TILL_BORS.get(land)

    def poang(q):
        p = 0
        if isin and str(q.get("ISIN", "")).upper() == isin.upper():
            p += 5
        if onskad_bors and q.get("Exchange") == onskad_bors:
            p += 3
        qt = str(q.get("Type", "")).lower()
        if typ == "ETF" and "etf" in qt:
            p += 2
        if typ == "Fond" and "fund" in qt:
            p += 2
        if typ not in ("ETF", "Fond") and "stock" in qt:
            p += 1
        return p

    basta = max(res, key=poang)
    if not basta.get("Code") or not basta.get("Exchange"):
        return None, "Ej hittad"
    return f"{basta['Code']}.{basta['Exchange']}".upper(), "Hittad via ISIN" if isin and fraga == isin else "Hittad via namn"


# ---------------------------------------------------------------- kurser och valuta
def kurser(ticker, nyckel, fran, period="d"):
    """[(datum, close, adjusted_close)] äldst först."""
    data = _get(f"eod/{ticker}", nyckel, {"from": fran.isoformat(), "period": period}) or []
    ut = []
    for r in data if isinstance(data, list) else []:
        d, c = _datum(r.get("date")), _tal(r.get("close"))
        if d and c:
            ut.append((d, c, _tal(r.get("adjusted_close")) or c))
    return sorted(ut)


def _normalisera_valuta(valuta):
    """Pence -> pund. Returnerar (valuta, faktor)."""
    if valuta in ("GBX", "GBp"):
        return "GBP", 0.01
    if valuta in ("ZAc", "ZAC"):
        return "ZAR", 0.01
    return valuta, 1.0


_fx_cache = {}


def valutakurs(fran, till, nyckel):
    """Kurs för 1 enhet 'fran' i 'till'. None om den inte går att få fram (då räknas inget värde ut)."""
    if not fran or not till:
        return None
    if fran == till:
        return 1.0
    traff = _fx_cache.get((fran, till))
    if traff and time.time() - traff[1] < 3600:
        return traff[0]
    kurs = None
    fran_dag = dt.date.today() - dt.timedelta(days=14)
    for par, omvand in ((f"{fran}{till}.FOREX", False), (f"{till}{fran}.FOREX", True)):
        try:
            k = kurser(par, nyckel, fran_dag)
        except Exception:
            k = []
        if k:
            kurs = 1 / k[-1][1] if omvand else k[-1][1]
            break
    if not kurs:
        try:  # reserv: ECB-kurser via frankfurter.app (gratis, ingen nyckel)
            r = requests.get("https://api.frankfurter.app/latest", params={"from": fran, "to": till}, timeout=20)
            kurs = _tal(r.json().get("rates", {}).get(till)) if r.ok else None
        except Exception:
            kurs = None
    if kurs:
        _fx_cache[(fran, till)] = (kurs, time.time())
    return kurs


# ---------------------------------------------------------------- beräkningar
def _ttm_nettovinst(kvartal, ar, vid):
    """Nettovinst rullande 12 månader känd vid datum 'vid'. kvartal/ar: [(datum, värde)] nyast först."""
    kanda = [v for d, v in kvartal if d + dt.timedelta(days=RAPPORT_LAG_KVARTAL) <= vid and v is not None]
    if len(kanda) >= 4:
        return sum(kanda[:4])
    kanda_ar = [v for d, v in ar if d + dt.timedelta(days=RAPPORT_LAG_AR) <= vid and v is not None]
    return kanda_ar[0] if kanda_ar else None


def _snitt_nettovinst(ar, vid, antal=10):
    kanda = [v for d, v in ar if d + dt.timedelta(days=RAPPORT_LAG_AR) <= vid and v is not None][:antal]
    return sum(kanda) / len(kanda) if len(kanda) >= 3 else None


def _aktier_vid(aktier, vid):
    for d, a in aktier:  # nyast först
        if d + dt.timedelta(days=RAPPORT_LAG_KVARTAL) <= vid:
            return a
    return aktier[-1][1] if aktier else None


def _cagr(serie, ar=5):
    """Årlig tillväxt mellan senaste värdet och värdet ~'ar' år tidigare. serie: [(datum, v)] nyast först."""
    if len(serie) < 3:
        return None
    ny_d, ny_v = serie[0]
    gammal = [(d, v) for d, v in serie if (ny_d - d).days >= 365 * min(ar, len(serie) - 1) - 60]
    if not gammal:
        return None
    g_d, g_v = gammal[0]
    aar = (ny_d - g_d).days / 365.25
    if not ny_v or not g_v or ny_v <= 0 or g_v <= 0 or aar < 1:
        return None
    return (ny_v / g_v) ** (1 / aar) - 1


def _pe_historik(manad, aktier, kvartal, ar, mcap_nu, cyklisk, pe_ar):
    """Månatlig P/E-serie. Börsvärde = kurs × antal aktier vid tidpunkten. Om kurser och aktieantal
    inte hänger ihop (t.ex. vid split) används justerad kurs i förhållande till dagens börsvärde."""
    if not manad or not mcap_nu:
        return [], "saknas"
    idag = dt.date.today()
    start = idag.replace(year=idag.year - int(pe_ar))
    rader = [(d, c, a) for d, c, a in manad if d >= start]
    if not rader:
        return [], "saknas"

    metod = "kurs × aktier"
    bv = []
    for d, c, a in rader:
        n = _aktier_vid(aktier, d)
        bv.append(c * n if n else None)
    # Kontroll: följer börsvärdet den justerade kursen? Annars justerad metod.
    ok = all(v is not None for v in bv)
    if ok:
        for i in range(1, len(rader)):
            k_bv = bv[i] / bv[i - 1] if bv[i - 1] else 1
            k_adj = rader[i][2] / rader[i - 1][2] if rader[i - 1][2] else 1
            if k_adj and abs(math.log(max(k_bv, 1e-9) / k_adj)) > math.log(1.6):
                ok = False
                break
        if ok and abs(math.log(bv[-1] / mcap_nu)) > math.log(1.35):
            ok = False
    if not ok:
        metod = "justerad kurs"
        sista_adj = rader[-1][2]
        bv = [mcap_nu * a / sista_adj for _, _, a in rader]

    serie = []
    for (d, _, _), b in zip(rader, bv):
        vinst = _snitt_nettovinst(ar, d) if cyklisk else _ttm_nettovinst(kvartal, ar, d)
        if vinst and vinst > 0 and b:
            serie.append((d.isoformat(), b / vinst))
    return serie, metod


def _trend(earnings):
    """Analytikernas estimat per period ('0y', '+1y', '+5y' ...)."""
    trend = earnings.get("Trend") if isinstance(earnings, dict) else None
    ut = {}
    for d, post in _poster(trend):
        per = post.get("period")
        if per and per not in ut:
            ut[per] = dict(post, _slut=d)
    return ut


# ---------------------------------------------------------------- huvudfunktion
def hamta(ticker, nyckel, typ_hint=None, pe_ar=10):
    """Hämtar allt ramverket behöver för en ticker. Returnerar alltid en dict."""
    tk = till_eodhd(ticker)
    hamtad = time.strftime("%Y-%m-%d %H:%M")
    noter = []
    f = _get(f"fundamentals/{tk}", nyckel)
    gen = (f or {}).get("General") or {}
    if not gen and not tk.endswith(".EUFUND"):
        return {"ok": False, "eodhd_ticker": tk, "hamtad": hamtad,
                "notering": f"Hittades inte hos EODHD ({tk}). Kontrollera tickern eller importera via ISIN."}

    typ_eod = str(gen.get("Type") or "").lower()
    if typ_hint in ("ETF", "Fond"):
        typ = typ_hint
    elif "etf" in typ_eod:
        typ = "ETF"
    elif "fund" in typ_eod or tk.endswith(".EUFUND"):
        typ = "Fond"
    else:
        typ = "Aktie"

    idag = dt.date.today()
    dag = kurser(tk, nyckel, idag - dt.timedelta(days=130))
    kurs = dag[-1][1] if dag else None
    if kurs is None and typ == "Fond":
        kurs = _tal(((f or {}).get("MutualFund_Data") or {}).get("Nav"))
    if kurs is None:
        return {"ok": False, "eodhd_ticker": tk, "hamtad": hamtad, "typ": typ,
                "namn": gen.get("Name"), "notering": f"Ingen kurs från EODHD för {tk}."}
    kurs_90 = next((c for d, c, _ in reversed(dag) if d <= idag - dt.timedelta(days=90)), None)

    valuta, faktor = _normalisera_valuta(gen.get("CurrencyCode") or "")
    kurs, kurs_90 = kurs * faktor, (kurs_90 * faktor if kurs_90 else None)
    if not valuta:
        noter.append("Valuta saknas hos EODHD")
    fx_sek = valutakurs(valuta, "SEK", nyckel) if valuta else None
    if valuta and fx_sek is None:
        noter.append(f"Växelkurs {valuta}/SEK saknas – värde räknas inte ut")

    ut = {"ok": True, "eodhd_ticker": tk, "hamtad": hamtad, "typ": typ, "namn": gen.get("Name") or tk,
          "valuta": valuta, "kurs": kurs, "kurs_sek": kurs * fx_sek if fx_sek else None,
          "sektor": gen.get("Sector"), "bransch": gen.get("Industry")}
    if typ in ("ETF", "Fond"):
        ut["notering"] = "; ".join(noter)
        return ut

    hl = f.get("Highlights") or {}
    val = f.get("Valuation") or {}
    ar_rek = f.get("AnalystRatings") or {}
    fin = f.get("Financials") or {}
    inc = fin.get("Income_Statement") or {}
    bal = fin.get("Balance_Sheet") or {}
    fin_valuta, fin_faktor = _normalisera_valuta(inc.get("currency_symbol") or gen.get("CurrencyCode") or valuta)
    fx_fin = (valutakurs(fin_valuta, valuta, nyckel) if fin_valuta and valuta else 1.0) or None
    if fx_fin is None:
        noter.append(f"Växelkurs {fin_valuta}/{valuta} saknas, räknar 1:1")
        fx_fin = 1.0
    fx_fin *= fin_faktor

    # Resultat i handelsvalutan
    kvartal = [(d, _tal(p.get("netIncome")) * fx_fin if _tal(p.get("netIncome")) is not None else None)
               for d, p in _poster(inc.get("quarterly"))]
    ar = [(d, _tal(p.get("netIncome")) * fx_fin if _tal(p.get("netIncome")) is not None else None)
          for d, p in _poster(inc.get("yearly"))]
    oms_ar = [(d, _tal(p.get("totalRevenue"))) for d, p in _poster(inc.get("yearly")) if _tal(p.get("totalRevenue"))]
    rorelse_ar = [(d, _tal(p.get("operatingIncome"))) for d, p in _poster(inc.get("yearly"))]

    # Antal aktier över tid
    aktier = []
    for d, p in _poster((f.get("outstandingShares") or {}).get("quarterly")):
        n = _tal(p.get("shares")) or ((_tal(p.get("sharesMln")) or 0) * 1e6) or None
        if n:
            aktier.append((d, n))
    if not aktier:
        for d, p in _poster(bal.get("quarterly")):
            n = _tal(p.get("commonStockSharesOutstanding"))
            if n:
                aktier.append((d, n))
    aktier_nu = _tal((f.get("SharesStats") or {}).get("SharesOutstanding")) or (aktier[0][1] if aktier else None)

    mcap = _tal(hl.get("MarketCapitalization"))
    if mcap and faktor != 1.0 and aktier_nu and abs(math.log(mcap / (kurs * aktier_nu))) > math.log(20):
        mcap *= faktor  # börsvärde angivet i pence
    if not mcap and aktier_nu:
        mcap = kurs * aktier_nu

    # P/E nu och historik
    cyklisk = typ_hint == "Cyklisk"
    vinst_nu = _snitt_nettovinst(ar, idag) if cyklisk else _ttm_nettovinst(kvartal, ar, idag)
    pe_nu = mcap / vinst_nu if mcap and vinst_nu and vinst_nu > 0 else None
    manad = kurser(tk, nyckel, idag.replace(year=idag.year - int(pe_ar) - 1), "m")
    pe_serie, pe_metod = _pe_historik(manad, aktier, kvartal, ar, mcap, cyklisk, pe_ar)
    pe_median = pe_pct = hist_ar = None
    if len(pe_serie) >= 12 and pe_nu:
        varden = sorted(p for _, p in pe_serie)
        pe_median = varden[len(varden) // 2]
        pe_pct = sum(1 for p in varden if p <= pe_nu) / len(varden) * 100
        hist_ar = round((_datum(pe_serie[-1][0]) - _datum(pe_serie[0][0])).days / 365.25, 1)
    elif pe_nu:
        noter.append("För kort P/E-historik")
    if pe_nu is None:
        noter.append("Negativ eller saknad vinst – inget P/E")

    # Analytikernas estimat
    tr = _trend(f.get("Earnings") or {})
    t0, t1, t5 = tr.get("0y", {}), tr.get("+1y", {}), tr.get("+5y", {})
    eps0 = _tal(t0.get("epsTrendCurrent")) or _tal(t0.get("earningsEstimateAvg")) or _tal(hl.get("EPSEstimateCurrentYear"))
    eps1 = _tal(t1.get("epsTrendCurrent")) or _tal(t1.get("earningsEstimateAvg")) or _tal(hl.get("EPSEstimateNextYear"))
    eps0_90, eps1_90 = _tal(t0.get("epsTrend90daysAgo")), _tal(t1.get("epsTrend90daysAgo"))
    g0 = _tal(t0.get("growth"))
    g5 = _tal(t5.get("growth"))
    fy_slut = t0.get("_slut")
    eps_skala = fx_fin  # estimat anges per aktie i rapportvalutan -> räknas om till handelsvalutan

    def ntm(e0, e1, vid):
        if e0 is None or e1 is None:
            return e1 or e0
        if not fy_slut:
            return e1
        andel = max(0.0, min(1.0, (fy_slut - vid).days / 365))
        return andel * e0 + (1 - andel) * e1

    bas_eps = eps0 / (1 + g0) if eps0 and g0 is not None and g0 > -0.9 else None
    if bas_eps is None:
        senaste = _poster((f.get("Earnings") or {}).get("Annual"))
        bas_eps = _tal(senaste[0][1].get("epsActual")) if senaste else None

    def tvaarstillvaxt(e1):
        if e1 and bas_eps and e1 > 0 and bas_eps > 0:
            return (e1 / bas_eps) ** 0.5 - 1
        return None

    g2 = tvaarstillvaxt(eps1)
    eps_hist = []
    for (d, v) in ar:
        n = _aktier_vid(aktier, d + dt.timedelta(days=RAPPORT_LAG_KVARTAL)) if aktier else None
        if v and n:
            eps_hist.append((d, v / n))
    g_hist_eps = _cagr(eps_hist, 5)
    g_hist_oms = _cagr(oms_ar, 5)
    if g2 is not None:
        g, g_kalla = g2, "Analytiker, 2 år"
    elif g5 is not None:
        g, g_kalla = g5, "Analytiker, 5 år"
    elif g_hist_eps is not None:
        g, g_kalla = g_hist_eps, "Historisk vinst, 5 år"
    else:
        g, g_kalla = None, None

    ntm_nu = ntm(eps0, eps1, idag)
    fwd_pe = kurs / (ntm_nu * eps_skala) if ntm_nu and ntm_nu > 0 else (_tal(val.get("ForwardPE")) or None)
    peg = fwd_pe / (g * 100) if fwd_pe and g and g > 0 else None

    peg_90 = rev = None
    ntm_90 = ntm(eps0_90, eps1_90, idag - dt.timedelta(days=90))
    if ntm_90 and ntm_90 > 0 and ntm_nu:
        rev = ntm_nu / ntm_90 - 1
        g_90 = tvaarstillvaxt(eps1_90) if g_kalla == "Analytiker, 2 år" else g
        if kurs_90 and g_90 and g_90 > 0:
            peg_90 = kurs_90 / (ntm_90 * eps_skala) / (g_90 * 100)
    peg_trend = peg / peg_90 - 1 if peg and peg_90 else None

    upp = sum(_tal(t.get("epsRevisionsUpLast30days")) or 0 for t in (t0, t1))
    ned = sum(_tal(t.get("epsRevisionsDownLast30days")) or 0 for t in (t0, t1))
    antal_anal = _tal(t1.get("earningsEstimateNumberOfAnalysts")) or _tal(t0.get("earningsEstimateNumberOfAnalysts"))
    riktkurs = _tal(ar_rek.get("TargetPrice")) or _tal(hl.get("WallStreetTargetPrice"))
    if riktkurs and faktor != 1.0 and riktkurs > kurs * 20:
        riktkurs *= faktor

    marginaler = []
    oms_dict = dict(oms_ar)
    for d, v in rorelse_ar:
        if v is not None and oms_dict.get(d):
            marginaler.append(v / oms_dict[d])

    ut.update({
        "borsvarde_mn": mcap / 1e6 if mcap else None,
        "pe_nu": pe_nu, "pe_median": pe_median, "pe_pct": pe_pct, "hist_ar": hist_ar,
        "pe_serie": pe_serie, "pe_metod": pe_metod, "cyklisk_berakning": cyklisk,
        "eps0": eps0, "eps1": eps1, "eps0_90": eps0_90, "eps1_90": eps1_90, "eps_ntm": ntm_nu,
        "fy_slut": fy_slut.isoformat() if fy_slut else None,
        "fwd_pe": fwd_pe, "g_forvantad": g, "g_kalla": g_kalla, "g_2ar": g2, "g_5ar": g5,
        "g_hist_eps": g_hist_eps, "g_hist_oms": g_hist_oms,
        "peg": peg, "peg_90": peg_90, "peg_trend": peg_trend, "peg_eodhd": _tal(hl.get("PEGRatio")),
        "rev_90": rev, "rev_upp_30": upp, "rev_ned_30": ned, "antal_analytiker": antal_anal,
        "riktkurs_uppsida": riktkurs / kurs - 1 if riktkurs and kurs else None,
        "rek": {k: _tal(ar_rek.get(k)) for k in ("StrongBuy", "Buy", "Hold", "Sell", "StrongSell")},
        "rek_betyg": _tal(ar_rek.get("Rating")),
        "marginaler": marginaler[:6],
        "notering": "; ".join(noter),
    })
    return ut


def diagnos(ticker, nyckel):
    """Rådata för testsidan: vilka avsnitt och fält EODHD levererar för en ticker."""
    tk = till_eodhd(ticker)
    f = _get(f"fundamentals/{tk}", nyckel) or {}
    idag = dt.date.today()
    dag = kurser(tk, nyckel, idag - dt.timedelta(days=10))
    manad = kurser(tk, nyckel, idag.replace(year=idag.year - 11), "m")
    inc = (f.get("Financials") or {}).get("Income_Statement") or {}
    tr = _trend(f.get("Earnings") or {})
    return {
        "eodhd_ticker": tk,
        "avsnitt": sorted(f.keys()),
        "general": {k: (f.get("General") or {}).get(k) for k in ("Name", "Type", "Exchange", "CurrencyCode",
                                                                 "CountryISO", "ISIN", "Sector", "Industry")},
        "highlights": f.get("Highlights"),
        "valuation": f.get("Valuation"),
        "analyst_ratings": f.get("AnalystRatings"),
        "trend": {p: {k: v for k, v in post.items() if k != "_slut"} for p, post in tr.items()},
        "inkomst_valuta": inc.get("currency_symbol"),
        "antal_ar": len(_poster(inc.get("yearly"))),
        "antal_kvartal": len(_poster(inc.get("quarterly"))),
        "senaste_kvartal": dict(_poster(inc.get("quarterly"))[0][1]) if _poster(inc.get("quarterly")) else None,
        "antal_aktieposter": len(_poster((f.get("outstandingShares") or {}).get("quarterly"))),
        "dagskurser": [(d.isoformat(), c, a) for d, c, a in dag[-3:]],
        "manadskurser_antal": len(manad),
        "manadskurser_forsta": manad[0][0].isoformat() if manad else None,
    }
