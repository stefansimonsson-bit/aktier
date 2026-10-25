# -*- coding: utf-8 -*-
"""Värderingslogik: delindex, sammanvägt index och signal per innehav."""

STANDARD_INSTALLNINGAR = {
    "rantor": {"SEK": 0.033, "USD": 0.051},  # 10-åriga statsobligationer – uppdatera vid behov
    "rf_standard": 0.035,   # riskfri ränta för valutor som saknas ovan
    "erp": 0.05,            # aktieriskpremie: avkastningskrav = ränta + erp
    "fcf_premie": 0.035,    # rimlig FCF-yield = ränta + premie
    "p_lag": 20,            # P/E-percentil för "billig"
    "p_hog": 80,            # P/E-percentil för "dyr"
    "dcf_marginal": 0.20,   # säkerhetsmarginal mot DCF-värdet
    "dcf_ar": 10,           # år med din förväntade tillväxt
    "tillv_term": 0.025,    # evig tillväxt därefter
    "rev_grans": -0.10,     # spärr: vinstprognos sänkt mer än så på 90 dagar
    "nd_max": 3.0,          # spärr: max nettoskuld/EBITDA
    "rebal_band": 0.05,     # ETF/fond: tillåten avvikelse från målvikt
    "w_fcf": 0.5, "w_pe": 1.0, "w_dcf": 1.5,
    "hist_ar": 5,           # år P/E-historik
    "dra_sbc": True,        # dra av aktieersättningar från FCF
}

INDEX_MIN, INDEX_MAX = 50, 200


def _klamp(v):
    return max(INDEX_MIN, min(INDEX_MAX, v))


def _tal(v):
    try:
        f = float(v)
        return None if f != f else f  # NaN -> None
    except (TypeError, ValueError):
        return None


def dcf_varde(fcf, g, r, n, gt):
    """Tvåstegs-DCF: tillväxt g i n år, därefter evig tillväxt gt, diskonterat med r."""
    a = (1 + g) / (1 + r)
    s = n if abs(a - 1) < 1e-9 else a * (1 - a ** n) / (1 - a)
    tv = (1 + g) ** n * (1 + gt) / (r - gt) / (1 + r) ** n
    return fcf * (s + tv)


def implicit_tillvaxt(borsvarde, fcf, r, n, gt):
    """Tillväxten under n år som gör DCF-värdet lika med börsvärdet."""
    if not borsvarde or not fcf or fcf <= 0 or r is None or r <= gt + 0.005:
        return None
    lag, hog = -0.5, 1.0
    if dcf_varde(fcf, lag, r, n, gt) > borsvarde or dcf_varde(fcf, hog, r, n, gt) < borsvarde:
        return None
    for _ in range(80):
        mitt = (lag + hog) / 2
        if dcf_varde(fcf, mitt, r, n, gt) < borsvarde:
            lag = mitt
        else:
            hog = mitt
    return (lag + hog) / 2


def vardera(innehav, data, inst):
    """innehav: dict med ticker, typ, antal, tillvaxt (andel), malvikt (andel), manuell_kurs_sek.
    data: resultat från data.hamta. inst: inställningar. Returnerar en dict med alla mått.
    Vikt och ETF-signal räknas i vardera_portfolj eftersom de kräver hela portföljen."""
    typ = innehav.get("typ") or data.get("typ") or "Aktie"
    valuta = data.get("valuta")
    rf = inst["rantor"].get((valuta or "").upper(), inst["rf_standard"])
    r = rf + inst["erp"]
    g = _tal(innehav.get("tillvaxt"))
    manuell = _tal(innehav.get("manuell_kurs_sek"))
    kurs_sek = manuell if manuell else data.get("kurs_sek")
    antal = _tal(innehav.get("antal"))

    res = {
        "ticker": innehav.get("ticker"), "typ": typ, "namn": data.get("namn"),
        "valuta": valuta, "kurs": data.get("kurs"), "kurs_sek": kurs_sek,
        "varde_sek": antal * kurs_sek if antal is not None and kurs_sek else None,
        "riskfri": rf, "avk_krav": r, "notering": data.get("notering") or "",
        "fcf_yield": None, "implicit_tillvaxt": None,
        "index_fcf": None, "index_pe": None, "index_dcf": None,
        "billiga": None, "dyra": None, "sparr": None, "index": None, "signal": None,
        "pe_nu": data.get("pe_nu"), "pe_median": data.get("pe_median"), "pe_pct": data.get("pe_pct"),
        "hist_ar": data.get("hist_ar"), "eps_rev": data.get("eps_rev"), "nd_ebitda": data.get("nd_ebitda"),
        "borsvarde_mn": data.get("borsvarde_mn"), "fcf_mn": data.get("fcf_mn"),
        "tillvaxt": g, "malvikt": _tal(innehav.get("malvikt")),
    }
    if typ in ("ETF", "Fond"):
        return res
    if not data.get("ok", True) and kurs_sek is None:
        res["signal"] = "För lite data"
        return res

    mcap, fcf = data.get("borsvarde_mn"), data.get("fcf_mn")
    pe_nu, pe_med, pe_pct = data.get("pe_nu"), data.get("pe_median"), data.get("pe_pct")

    if mcap and mcap > 0 and fcf is not None:
        res["fcf_yield"] = fcf / mcap
    fy = res["fcf_yield"]
    if fy is not None and fy > 0:
        res["index_fcf"] = _klamp((rf + inst["fcf_premie"]) / fy * 100)
    if pe_nu is not None and pe_med:
        res["index_pe"] = _klamp(pe_nu / pe_med * 100)
    if g is not None and fcf and fcf > 0 and mcap and r > inst["tillv_term"] + 0.005:
        res["index_dcf"] = _klamp(mcap / dcf_varde(fcf, g, r, inst["dcf_ar"], inst["tillv_term"]) * 100)
    if mcap and fcf:
        res["implicit_tillvaxt"] = implicit_tillvaxt(mcap, fcf, r, inst["dcf_ar"], inst["tillv_term"])

    marg = inst["dcf_marginal"] * 100
    billig = [
        fy is not None and fy > 0 and fy >= rf + inst["fcf_premie"],
        pe_pct is not None and pe_pct <= inst["p_lag"],
        res["index_dcf"] is not None and res["index_dcf"] <= 100 - marg,
    ]
    dyr = [
        fy is not None and fy > 0 and fy <= rf,
        pe_pct is not None and pe_pct >= inst["p_hog"],
        res["index_dcf"] is not None and res["index_dcf"] >= 100 + marg,
    ]
    res["billiga"], res["dyra"] = sum(billig), sum(dyr)
    rev, nd = data.get("eps_rev"), data.get("nd_ebitda")
    res["sparr"] = bool((rev is not None and rev <= inst["rev_grans"]) or (nd is not None and nd > inst["nd_max"]))

    delar = [(res["index_fcf"], inst["w_fcf"]), (res["index_pe"], inst["w_pe"]), (res["index_dcf"], inst["w_dcf"])]
    tillg = [(v, w) for v, w in delar if v is not None]
    vikt_summa = sum(w for _, w in tillg)
    if tillg and vikt_summa > 0:
        res["index"] = sum(v * w for v, w in tillg) / vikt_summa

    if len(tillg) < 2:
        res["signal"] = "För lite data"
    elif res["dyra"] >= 2:
        res["signal"] = "Minska"
    elif res["sparr"]:
        res["signal"] = "Granska"
    elif res["billiga"] >= 2:
        res["signal"] = "Öka"
    else:
        res["signal"] = "Behåll"
    return res


def vardera_portfolj(innehav_lista, data_per_ticker, inst):
    """Värderar alla innehav, räknar vikter och sätter ETF/fond-signaler."""
    rader = [vardera(h, data_per_ticker.get(h["ticker"], {}), inst) for h in innehav_lista]
    total = sum(r["varde_sek"] for r in rader if r["varde_sek"])
    for r in rader:
        r["vikt"] = r["varde_sek"] / total if total and r["varde_sek"] else None
        if r["typ"] in ("ETF", "Fond"):
            mal, vikt = r["malvikt"], r["vikt"]
            if mal is None:
                r["signal"] = "Behåll"
            elif vikt is None:
                r["signal"] = "För lite data"
            elif vikt < mal - inst["rebal_band"]:
                r["signal"] = "Öka"
            elif vikt > mal + inst["rebal_band"]:
                r["signal"] = "Minska"
            else:
                r["signal"] = "Behåll"
    return rader
