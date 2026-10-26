# -*- coding: utf-8 -*-
"""Hämtar kurs- och bokslutsdata från Yahoo Finance via yfinance.

Allt som returneras är vanliga Python-typer (dict/list/float) så att det kan cachas.
"""
import time

import pandas as pd
import yfinance as yf

RAPPORTFORDROJNING_DAGAR = 75  # en årsvinst antas vara känd ~2,5 mån efter räkenskapsårets slut


# ---------------------------------------------------------------- hjälpfunktioner
def _sakert(fn, standard=None):
    try:
        v = fn()
        return standard if v is None else v
    except Exception:
        return standard


def _tal(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except Exception:
        return None


def _utan_tz(ts):
    ts = pd.Timestamp(ts)
    return ts.tz_localize(None) if ts.tzinfo else ts


def _rad(df, namn_lista):
    """Första matchande rad ur en yfinance-tabell, nyast först."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    for n in namn_lista:
        if n in df.index:
            s = pd.to_numeric(df.loc[n], errors="coerce").dropna()
            if not s.empty:
                s.index = [_utan_tz(i) for i in s.index]
                return s.sort_index(ascending=False)
    return None


def _normalisera_valuta(valuta, varde):
    if valuta == "GBp":
        return "GBP", (varde / 100 if varde is not None else None)
    if valuta == "ZAc":
        return "ZAR", (varde / 100 if varde is not None else None)
    return valuta, varde


def valutakurs(fran, till="SEK"):
    """Kurs för att räkna om 1 enhet 'fran' till 'till'. None om den inte går att hämta."""
    if not fran or not till or fran == till:
        return 1.0
    h = _sakert(lambda: yf.Ticker(f"{fran}{till}=X").history(period="10d"))
    if isinstance(h, pd.DataFrame) and not h.empty and "Close" in h:
        return _tal(h["Close"].dropna().iloc[-1])
    return None


# ---------------------------------------------------------------- P/E-historik
def _pe_historik(manad_kurs, borsvarde, vinster, aktiefaktor, cyklisk, hist_ar, ttm_vinst):
    """P/E utan att påverkas av aktiesplittar:
    börsvärde_t ≈ dagens börsvärde × (kurs_t / dagens kurs); P/E_t = börsvärde_t / årsvinst.
    Årsvinsterna justeras för förändrat antal aktier (återköp/nyemission)."""
    ut = {"pe_nu": None, "pe_median": None, "pe_pct": None, "hist_ar": None, "pe_serie": []}
    if borsvarde is None or vinster is None or vinster.empty:
        return ut

    justerad = {d: (v / aktiefaktor.get(d, 1.0)) for d, v in vinster.items()}

    if cyklisk:
        nam = sum(justerad.values()) / len(justerad)
    else:
        nam = ttm_vinst if ttm_vinst is not None else vinster.iloc[0]
    if nam is not None and nam > 0:
        ut["pe_nu"] = borsvarde / nam

    if manad_kurs is None or manad_kurs.empty:
        return ut
    sista_kurs = manad_kurs.iloc[-1]
    start = pd.Timestamp.now() - pd.DateOffset(years=int(hist_ar))
    datum = sorted(justerad)
    serie = []
    for t, kurs in manad_kurs.items():
        if t < start:
            continue
        kanda = [d for d in datum if d + pd.Timedelta(days=RAPPORTFORDROJNING_DAGAR) <= t]
        if not kanda:
            continue
        nam_t = (sum(justerad[d] for d in kanda) / len(kanda)) if cyklisk else justerad[kanda[-1]]
        if nam_t is None or nam_t <= 0:
            continue
        serie.append((t, borsvarde * (kurs / sista_kurs) / nam_t))

    if len(serie) >= 6 and ut["pe_nu"] is not None:
        varden = pd.Series([p for _, p in serie])
        ut["pe_median"] = float(varden.median())
        ut["pe_pct"] = float((varden <= ut["pe_nu"]).mean() * 100)
        ut["hist_ar"] = round((serie[-1][0] - serie[0][0]).days / 365.25, 1)
    ut["pe_serie"] = [(t.strftime("%Y-%m-%d"), float(p)) for t, p in serie]
    return ut


# ---------------------------------------------------------------- förväntad tillväxt
G_MIN, G_MAX = -0.05, 0.30  # rimlighetsgränser för startårets tillväxt


def _forvantad_tillvaxt(t, inc):
    """Analytikernas förväntade årliga tillväxt. I första hand femårsprognosen, därefter snittet av
    prognoserna för i år och nästa år, sist bolagets historiska omsättningstillväxt."""
    g_5ar = g_kort = g_hist = None
    ge = _sakert(lambda: t.growth_estimates)
    if isinstance(ge, pd.DataFrame) and not ge.empty:
        kol = "stockTrend" if "stockTrend" in ge.columns else ge.columns[0]
        if "+5y" in ge.index:
            g_5ar = _tal(ge.loc["+5y", kol])
        kort = [_tal(ge.loc[p, kol]) for p in ("0y", "+1y") if p in ge.index]
        kort = [k for k in kort if k is not None]
        if kort:
            g_kort = sum(kort) / len(kort)
    if g_kort is None:
        ee = _sakert(lambda: t.earnings_estimate)
        if isinstance(ee, pd.DataFrame) and not ee.empty and "growth" in ee.columns:
            kort = [_tal(ee.loc[p, "growth"]) for p in ("0y", "+1y") if p in ee.index]
            kort = [k for k in kort if k is not None]
            if kort:
                g_kort = sum(kort) / len(kort)
    oms = _rad(inc, ["Total Revenue", "Operating Revenue"])
    if oms is not None and len(oms) >= 3 and oms.iloc[0] > 0 and oms.iloc[-1] > 0:
        ar = (oms.index[0] - oms.index[-1]).days / 365.25
        if ar > 1:
            g_hist = (oms.iloc[0] / oms.iloc[-1]) ** (1 / ar) - 1

    if g_5ar is not None:
        g_ref, kalla = g_5ar, "Analytiker, 5 år"
    elif g_kort is not None:
        g_ref, kalla = g_kort, "Analytiker, 1–2 år"
    elif g_hist is not None:
        g_ref, kalla = g_hist, "Historisk omsättning"
    else:
        g_ref, kalla = None, None
    if g_ref is not None:
        g_ref = max(G_MIN, min(G_MAX, g_ref))
    return {"g_ref": g_ref, "kalla": kalla, "g_5ar": g_5ar, "g_kort": g_kort, "g_hist": g_hist}


# ---------------------------------------------------------------- tickersök
def sok_ticker(isin=None, namn=None, kortnamn=None, typ=None):
    """Föreslår en Yahoo-ticker. Returnerar (ticker, status)."""
    onskad = {"Aktie": "EQUITY", "Cyklisk": "EQUITY", "ETF": "ETF", "Fond": "MUTUALFUND"}.get(typ)
    for fraga in [q for q in (isin, namn) if q]:
        res = _sakert(lambda: yf.Search(fraga, max_results=8, news_count=0).quotes, []) or []
        kandidater = [q for q in res if q.get("symbol")]
        if not kandidater:
            continue
        def poang(q):
            p = 0
            if onskad and q.get("quoteType") == onskad:
                p += 2
            if isin and isin.upper().startswith("SE") and q["symbol"].upper().endswith(".ST"):
                p += 3
            if isin and isin.upper().startswith("US") and "." not in q["symbol"]:
                p += 3
            if kortnamn:  # skiljer t.ex. VOLV-A och VOLV-B åt
                rent = lambda x: "".join(ch for ch in str(x).upper() if ch.isalnum())
                if rent(q["symbol"].split(".")[0]) == rent(kortnamn):
                    p += 4
            return p
        basta = max(kandidater, key=poang)
        return basta["symbol"].upper(), ("Hittad via ISIN" if fraga == isin else "Hittad via namn")
    # Gissning från kortnamnet
    if kortnamn:
        k = str(kortnamn).strip().upper().replace(" ", "-")
        if isin and isin.upper().startswith("SE"):
            return f"{k}.ST", "Gissad"
        return k, "Gissad"
    return None, "Ej hittad"


# ---------------------------------------------------------------- huvudfunktion
def hamta(symbol, typ=None, hist_ar=5, dra_sbc=True):
    """Hämtar allt verktyget behöver för en ticker. Returnerar alltid en dict."""
    symbol = symbol.strip().upper()
    t = yf.Ticker(symbol)
    info = _sakert(lambda: t.info, {}) or {}
    noter = []
    hamtad = time.strftime("%Y-%m-%d %H:%M")

    quote_type = (info.get("quoteType") or "").upper()
    if not typ:
        typ = {"ETF": "ETF", "MUTUALFUND": "Fond"}.get(quote_type, "Aktie")

    historik = _sakert(lambda: t.history(period=f"{max(int(hist_ar), 1) + 2}y", interval="1mo",
                                         auto_adjust=False))
    manad_kurs = None
    if isinstance(historik, pd.DataFrame) and not historik.empty and "Close" in historik:
        manad_kurs = historik["Close"].dropna()
        manad_kurs.index = [_utan_tz(i) for i in manad_kurs.index]

    kurs = (_tal(info.get("regularMarketPrice")) or _tal(info.get("currentPrice"))
            or _tal(info.get("navPrice")))
    if kurs is None and manad_kurs is not None and not manad_kurs.empty:
        kurs = _tal(manad_kurs.iloc[-1])
    if kurs is None:
        return {"symbol": symbol, "typ": typ, "hamtad": hamtad, "ok": False,
                "notering": "Hittades inte på Yahoo Finance. Svenska aktier slutar på .ST (t.ex. VOLV-B.ST)."}

    ra_valuta = info.get("currency")
    kurs_ra = kurs
    valuta, kurs = _normalisera_valuta(ra_valuta, kurs)
    if manad_kurs is not None and ra_valuta in ("GBp", "ZAc"):
        manad_kurs = manad_kurs / 100
    fx_sek = valutakurs(valuta, "SEK")
    if fx_sek is None:
        noter.append(f"Växelkurs {valuta}/SEK saknas")

    ut = {
        "symbol": symbol, "typ": typ, "hamtad": hamtad, "ok": True,
        "namn": info.get("longName") or info.get("shortName") or symbol,
        "valuta": valuta, "kurs": kurs, "kurs_sek": kurs * fx_sek if fx_sek else None,
        "kurs_serie": ([(d.strftime("%Y-%m-%d"), float(v)) for d, v in manad_kurs.items()]
                       if manad_kurs is not None else []),
    }
    if typ in ("ETF", "Fond"):
        ut["notering"] = "; ".join(noter)
        return ut

    # ---------- aktier
    borsvarde = _tal(info.get("marketCap")) or _tal(_sakert(lambda: t.fast_info["market_cap"]))
    fin_valuta, _ = _normalisera_valuta(info.get("financialCurrency") or valuta, None)
    fx_fin = valutakurs(fin_valuta, valuta)
    if fx_fin is None:
        noter.append(f"Växelkurs {fin_valuta}/{valuta} saknas, räknar 1:1")
        fx_fin = 1.0

    # Fritt kassaflöde – tre varianter: snitt 3 år, senaste året och normaliserad capex
    cf = _sakert(lambda: t.cashflow)
    ocf = _rad(cf, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
    fcf = _rad(cf, ["Free Cash Flow"])
    if fcf is None:
        capex = _rad(cf, ["Capital Expenditure"])
        if ocf is not None and capex is not None:
            fcf = (ocf + capex).dropna().sort_index(ascending=False)
    sbc = _rad(cf, ["Stock Based Compensation"]) if dra_sbc else None
    avskr = _rad(cf, ["Depreciation And Amortization", "Depreciation Amortization Depletion",
                      "Depreciation"])
    fcf_snitt = fcf_senaste = fcf_norm = None
    fcf_ar = []
    if fcf is not None and not fcf.empty:
        justerad_fcf = fcf - sbc.reindex(fcf.index).fillna(0) if sbc is not None else fcf
        justerad_fcf = justerad_fcf * fx_fin
        senaste = justerad_fcf.iloc[:3]
        fcf_snitt = float(senaste.mean())
        fcf_senaste = float(justerad_fcf.iloc[0])
        if len(senaste) < 3:
            noter.append(f"FCF-snitt bygger på {len(senaste)} år")
        fcf_ar = [(d.strftime("%Y"), float(v) / 1e6) for d, v in justerad_fcf.sort_index().items()]
    else:
        noter.append("FCF saknas")
    if ocf is not None and avskr is not None:
        # Normaliserad capex: investeringar = avskrivningar, dvs. bara underhåll – tillväxtinvesteringar räknas bort
        d0 = ocf.index[0]
        if d0 in avskr.index:
            norm = ocf.loc[d0] - abs(avskr.loc[d0])
            if sbc is not None and d0 in sbc.index:
                norm -= sbc.loc[d0]
            fcf_norm = float(norm) * fx_fin

    # Vinster och antal aktier
    inc = _sakert(lambda: t.income_stmt)
    vinster = _rad(inc, ["Net Income Common Stockholders", "Net Income",
                         "Net Income From Continuing Operation Net Minority Interest"])
    aktier = _rad(inc, ["Diluted Average Shares", "Basic Average Shares"])
    aktiefaktor = {}
    if vinster is not None:
        vinster = vinster * fx_fin
        if aktier is not None and not aktier.empty:
            nu = aktier.iloc[0]
            for d, a in aktier.items():
                f = a / nu if nu else 1.0
                aktiefaktor[d] = f if 0.67 <= f <= 1.5 else 1.0  # stora hopp = split/datafel

    ttm = None
    q_vinst = _rad(_sakert(lambda: t.quarterly_income_stmt),
                   ["Net Income Common Stockholders", "Net Income"])
    if q_vinst is not None and len(q_vinst) >= 4:
        ttm = float(q_vinst.iloc[:4].sum()) * fx_fin

    pe = _pe_historik(manad_kurs, borsvarde, vinster, aktiefaktor, typ == "Cyklisk", hist_ar, ttm)
    if pe["pe_nu"] is None:
        noter.append("Negativ eller saknad vinst – inget P/E")
    elif pe["pe_median"] is None:
        noter.append("För kort P/E-historik")

    # Rörelsemarginal per år (för kvalitetsbedömningen)
    marginaler = []
    rorelse = _rad(inc, ["Operating Income", "EBIT", "Total Operating Income As Reported"])
    oms_m = _rad(inc, ["Total Revenue", "Operating Revenue"])
    if rorelse is not None and oms_m is not None:
        for d in rorelse.index:
            if d in oms_m.index and oms_m.loc[d] > 0:
                marginaler.append(float(rorelse.loc[d] / oms_m.loc[d]))

    # Förväntad tillväxt: analytikernas konsensus, med historisk omsättningstillväxt som reserv
    tillv = _forvantad_tillvaxt(t, inc)

    # Analytikernas riktkurs
    riktkurs_uppsida, antal_analytiker = None, _tal(info.get("numberOfAnalystOpinions"))
    pt = _sakert(lambda: t.analyst_price_targets, {}) or {}
    snitt = _tal(pt.get("mean")) if isinstance(pt, dict) else None
    if snitt is None:
        snitt = _tal(info.get("targetMeanPrice"))
    if snitt and kurs_ra:
        riktkurs_uppsida = snitt / kurs_ra - 1

    # Spärr: vinstrevideringar och skuldsättning
    eps_rev = None
    trend = _sakert(lambda: t.eps_trend)
    if isinstance(trend, pd.DataFrame) and not trend.empty:
        for period in ("+1y", "0y"):
            if period in trend.index and {"current", "90daysAgo"} <= set(trend.columns):
                nu_v, da_v = _tal(trend.loc[period, "current"]), _tal(trend.loc[period, "90daysAgo"])
                if nu_v is not None and da_v and da_v > 0:
                    eps_rev = nu_v / da_v - 1
                    break
    nd_ebitda = None
    skuld, kassa, ebitda = _tal(info.get("totalDebt")), _tal(info.get("totalCash")), _tal(info.get("ebitda"))
    if skuld is not None and ebitda and ebitda > 0:
        nd_ebitda = (skuld - (kassa or 0)) / ebitda

    ut.update({
        "borsvarde_mn": borsvarde / 1e6 if borsvarde else None,
        "fcf_mn": fcf_snitt / 1e6 if fcf_snitt is not None else None,
        "fcf_snitt3_mn": fcf_snitt / 1e6 if fcf_snitt is not None else None,
        "fcf_senaste_mn": fcf_senaste / 1e6 if fcf_senaste is not None else None,
        "fcf_norm_capex_mn": fcf_norm / 1e6 if fcf_norm is not None else None,
        "fcf_ar": fcf_ar,
        "pe_nu": pe["pe_nu"], "pe_median": pe["pe_median"], "pe_pct": pe["pe_pct"],
        "hist_ar": pe["hist_ar"], "pe_serie": pe["pe_serie"],
        "eps_rev": eps_rev, "nd_ebitda": nd_ebitda,
        "g_ref": tillv["g_ref"], "g_kalla": tillv["kalla"],
        "g_analytiker_5ar": tillv["g_5ar"], "g_analytiker_kort": tillv["g_kort"], "g_historisk": tillv["g_hist"],
        "riktkurs_uppsida": riktkurs_uppsida, "antal_analytiker": antal_analytiker,
        "marginaler": marginaler,
        "notering": "; ".join(noter),
    })
    return ut
