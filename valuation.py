# -*- coding: utf-8 -*-
"""Värderingsramverk v2.

Tillväxtbolag: PEG och PEG-trend. Mogna och cykliska bolag: P/E mot egen historik.
Analytikernas revideringar fungerar som filter. Fonder och ETF:er: ombalansering mot målvikt.
"""

STANDARD_INSTALLNINGAR = {
    "tillvaxt_grans": 0.10,     # förväntad vinsttillväxt för att räknas som tillväxtbolag
    "peg_rimlig": 1.5,          # index 100
    "peg_billig": 1.2,
    "peg_dyr": 2.0,
    "peg_dyr_stigande": 1.7,    # dyr redan här om PEG stiger
    "peg_trend_grans": 0.05,    # ±5 % på 90 dagar räknas som stigande/fallande
    "pe_lag": 20,               # percentil för billig
    "pe_hog": 80,               # percentil för dyr
    "pe_ar": 10,                # år P/E-historik
    "rev_grans": -0.05,         # estimat sänkta mer än så på 90 dagar stoppar köpsignal
    "max_vikt": 0.0,            # maxvikt per aktie, 0 = av
    "rebal_band": 0.05,         # fond/ETF: tillåten avvikelse från målvikt
}

KLASSER = ["Tillväxt", "Mogen", "Cyklisk", "Investmentbolag"]
KATEGORI = {"Tillväxt": "Aktier", "Mogen": "Aktier", "Cyklisk": "Aktier", "Investmentbolag": "Aktier",
            "Aktie": "Aktier", "Fond": "Fonder", "ETF": "ETF:er"}
INDEX_MIN, INDEX_MAX = 25, 300


def _tal(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _klamp(v):
    return max(INDEX_MIN, min(INDEX_MAX, v))


def klassificera(vald, data, inst):
    """Returnerar (klass, motivering)."""
    if vald in KLASSER:
        return vald, "vald av dig"
    g, hist = data.get("g_forvantad"), data.get("g_hist_oms")
    grans = inst["tillvaxt_grans"]
    if g is None:
        return "Mogen", "ingen tillväxtprognos – räknas som moget"
    if g >= grans and (hist is None or hist >= grans / 2):
        return "Tillväxt", f"förväntad vinsttillväxt {g:.0%}" + (f", historisk omsättningstillväxt {hist:.0%}" if hist is not None else "")
    if g >= grans:
        return "Mogen", f"prognos {g:.0%} men historisk omsättningstillväxt bara {hist:.0%}"
    return "Mogen", f"förväntad vinsttillväxt {g:.0%}, under {grans:.0%}"


def trendord(peg_trend, inst):
    if peg_trend is None:
        return None
    if peg_trend > inst["peg_trend_grans"]:
        return "stigande"
    if peg_trend < -inst["peg_trend_grans"]:
        return "fallande"
    return "stabil"


def vardera(innehav, data, inst):
    vald = innehav.get("typ")
    typ = vald if vald in ("ETF", "Fond") else (data.get("typ") if data.get("typ") in ("ETF", "Fond") else None)
    manuell = _tal(innehav.get("manuell_kurs_sek"))
    kurs_sek = manuell if manuell else data.get("kurs_sek")
    antal = _tal(innehav.get("antal"))
    res = {
        "ticker": innehav.get("ticker"), "namn": data.get("namn") or innehav.get("namn"),
        "eodhd_ticker": data.get("eodhd_ticker"), "valuta": data.get("valuta"), "kurs": data.get("kurs"),
        "kurs_sek": kurs_sek, "varde_sek": antal * kurs_sek if antal is not None and kurs_sek else None,
        "malvikt": _tal(innehav.get("malvikt")), "notering": data.get("notering") or "",
        "signal": None, "orsak": "", "index": None, "klass": None, "klass_motivering": "",
        "peg_trend_ord": None, "revfilter": False,
    }
    for k in ("fwd_pe", "g_forvantad", "g_kalla", "peg", "peg_90", "peg_trend", "pe_nu", "pe_median", "pe_pct",
              "hist_ar", "rev_90", "rev_upp_30", "rev_ned_30", "riktkurs_uppsida", "antal_analytiker",
              "g_hist_oms", "g_hist_eps", "peg_eodhd", "borsvarde_mn"):
        res[k] = data.get(k)
    if typ:
        res["klass"], res["kategori"] = typ, KATEGORI[typ]
        return res
    res["kategori"] = "Aktier"
    if not data.get("ok", True) and kurs_sek is None:
        res["klass"], res["signal"], res["orsak"] = vald or "–", "För lite data", data.get("notering") or "Data saknas"
        return res

    klass, motiv = klassificera(vald, data, inst)
    res["klass"], res["klass_motivering"] = klass, motiv

    if klass == "Investmentbolag":
        res["signal"], res["orsak"] = "Behåll", "Värderas inte – substansrabatt finns inte i datan"
        return res

    if klass == "Tillväxt":
        peg = data.get("peg")
        trend = trendord(data.get("peg_trend"), inst)
        res["peg_trend_ord"] = trend
        if peg is None:
            res["signal"], res["orsak"] = "För lite data", "PEG kunde inte räknas (estimat eller tillväxt saknas)"
            return res
        res["index"] = _klamp(peg / inst["peg_rimlig"] * 100)
        ttxt = f", {trend} PEG" if trend else ""
        if peg >= inst["peg_dyr"]:
            res["signal"], res["orsak"] = "Minska", f"PEG {peg:.2f} ≥ {inst['peg_dyr']}{ttxt}"
        elif trend == "stigande" and peg >= inst["peg_dyr_stigande"]:
            res["signal"], res["orsak"] = "Minska", f"PEG {peg:.2f} och stigande"
        elif peg <= inst["peg_billig"] and trend != "stigande":
            res["signal"], res["orsak"] = "Öka", f"PEG {peg:.2f} ≤ {inst['peg_billig']}{ttxt}"
        elif peg <= inst["peg_billig"]:
            res["signal"], res["orsak"] = "Behåll", f"PEG {peg:.2f} är lågt men stigande"
        else:
            res["signal"], res["orsak"] = "Behåll", f"PEG {peg:.2f}, mellan billig och dyr{ttxt}"
    else:  # Mogen eller Cyklisk
        pct, pe, med = data.get("pe_pct"), data.get("pe_nu"), data.get("pe_median")
        if pct is None or not med:
            res["signal"] = "För lite data"
            res["orsak"] = "P/E eller P/E-historik saknas" + (" (cyklisk: räknas på snittvinst)" if klass == "Cyklisk" else "")
            return res
        res["index"] = _klamp(pe / med * 100)
        bas = "P/E på 10 års snittvinst" if klass == "Cyklisk" else "P/E"
        if pct <= inst["pe_lag"]:
            res["signal"], res["orsak"] = "Öka", f"{bas} {pe:.1f} – lägsta {pct:.0f} % av historiken"
        elif pct >= inst["pe_hog"]:
            res["signal"], res["orsak"] = "Minska", f"{bas} {pe:.1f} – högre än {pct:.0f} % av historiken"
        else:
            res["signal"], res["orsak"] = "Behåll", f"{bas} {pe:.1f} mot median {med:.1f}"

    # Revideringsfilter
    rev = data.get("rev_90")
    if res["signal"] == "Öka" and rev is not None and rev <= inst["rev_grans"]:
        res["signal"], res["revfilter"] = "Behåll", True
        res["orsak"] += f", men estimaten sänkta {rev:.0%} på 90 dagar"
    return res


def vardera_portfolj(innehav_lista, data_per_ticker, inst):
    rader = [vardera(h, data_per_ticker.get(h["ticker"], {}), inst) for h in innehav_lista]
    total = sum(r["varde_sek"] for r in rader if r["varde_sek"])
    max_vikt = inst.get("max_vikt") or 0
    for r in rader:
        r["vikt"] = r["varde_sek"] / total if total and r["varde_sek"] else None
        vikt = r["vikt"]
        if r["klass"] in ("ETF", "Fond"):
            mal = r["malvikt"]
            if mal is None:
                r["signal"], r["orsak"] = "Behåll", "Ingen målvikt angiven"
            elif vikt is None:
                r["signal"], r["orsak"] = "För lite data", "Värde saknas"
            elif vikt < mal - inst["rebal_band"]:
                r["signal"], r["orsak"] = "Öka", f"Under målvikt ({vikt:.0%} mot {mal:.0%})"
            elif vikt > mal + inst["rebal_band"]:
                r["signal"], r["orsak"] = "Minska", f"Över målvikt ({vikt:.0%} mot {mal:.0%})"
            else:
                r["signal"], r["orsak"] = "Behåll", f"Nära målvikt ({vikt:.0%} mot {mal:.0%})"
        elif max_vikt > 0 and vikt is not None and vikt > max_vikt:
            text = f"över maxvikt ({vikt:.1%} mot {max_vikt:.0%})"
            if r["signal"] == "Öka":
                r["signal"], r["orsak"] = "Behåll", f"{r['orsak']}, men {text}"
            else:
                r["signal"] = "Minska"
                r["orsak"] = f"{text[0].upper()}{text[1:]}" + (f"; {r['orsak']}" if r["orsak"] else "")
    return rader
