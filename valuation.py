# -*- coding: utf-8 -*-
"""Värderingslogik: strategier, delindex, sammanvägt index och signal per innehav."""

# ---------------------------------------------------------------- strategier
STRATEGI_NYCKLAR = ["krav_metod", "avk_krav_fast", "erp", "fcf_bas", "fcf_premie", "p_lag", "p_hog",
                    "dcf_marginal", "dcf_ar", "tillv_term", "w_fcf", "w_pe", "w_dcf", "rev_grans", "nd_max",
                    "max_vikt", "hall_ar"]
FCF_BASER = {"senaste": "Senaste året", "snitt3": "Snitt 3 år", "norm_capex": "Normaliserad capex"}
KRAV_METODER = {"fast": "Fast avkastningskrav", "premie": "Ränta + riskpremie"}


STRATEGIER = {
    "A": {
        "namn": "A. Kvalitetstillväxt",
        "kort": "Låt vinnarna löpa – sälj bara vid tydlig övervärdering.",
        "beskrivning": ("Lägger nästan all vikt på DCF, alltså på om dagens pris förutsätter mer tillväxt än "
                        "analytikerna räknar med. FCF-måttet är avstängt eftersom det nästan alltid säger dyrt "
                        "om amerikansk tech när räntan är hög. Breda P/E-band och stor säkerhetsmarginal ger få "
                        "signaler. Passar en portfölj med kvalitetsbolag som Magnificent 7."),
        "param": {"krav_metod": "fast", "avk_krav_fast": 0.08, "erp": 0.04, "fcf_bas": "senaste", "fcf_premie": 0.02, "p_lag": 10, "p_hog": 90, "dcf_marginal": 0.30,
                  "dcf_ar": 10, "tillv_term": 0.03, "w_fcf": 0.0, "w_pe": 0.5, "w_dcf": 2.0,
                  "rev_grans": -0.15, "nd_max": 3.0, "max_vikt": 0.25, "hall_ar": 5},
    },
    "B": {
        "namn": "B. Balanserad",
        "kort": "Mellanväg mellan tillväxt och värdedisciplin.",
        "beskrivning": ("Alla tre mått används, med störst vikt på DCF och minst på FCF-yield. "
                        "Måttligt med signaler. Ett rimligt standardval."),
        "param": {"krav_metod": "fast", "avk_krav_fast": 0.085, "erp": 0.045, "fcf_bas": "senaste", "fcf_premie": 0.03, "p_lag": 20, "p_hog": 80, "dcf_marginal": 0.20,
                  "dcf_ar": 10, "tillv_term": 0.025, "w_fcf": 0.5, "w_pe": 1.0, "w_dcf": 1.5,
                  "rev_grans": -0.10, "nd_max": 3.0, "max_vikt": 0.15, "hall_ar": 5},
    },
    "C": {
        "namn": "C. Värdedisciplin",
        "kort": "Köp när det är billigt mot egen historik, sälj vid toppar.",
        "beskrivning": ("Störst vikt på P/E mot bolagets egen historik och snävare band, så att signalerna "
                        "kommer oftare. Fungerar bra i svängiga marknader, men kan sälja bolag som "
                        "förtjänar en högre värdering än förr."),
        "param": {"krav_metod": "fast", "avk_krav_fast": 0.09, "erp": 0.05, "fcf_bas": "snitt3", "fcf_premie": 0.035,
                  "p_lag": 25, "p_hog": 75, "dcf_marginal": 0.15, "dcf_ar": 8, "tillv_term": 0.025, "w_fcf": 1.0, "w_pe": 1.5, "w_dcf": 1.0,
                  "rev_grans": -0.10, "nd_max": 2.5, "max_vikt": 0.15, "hall_ar": 4},
    },
    "D": {
        "namn": "D. Försiktig",
        "kort": "Skydda kapitalet och minska koncentrationen.",
        "beskrivning": ("Högt avkastningskrav, känslig spärr och låg maxvikt per aktie. Säljer tidigt och "
                        "köper sällan. Passar om du främst vill minska risken i en koncentrerad portfölj."),
        "param": {"krav_metod": "fast", "avk_krav_fast": 0.095, "erp": 0.055, "fcf_bas": "snitt3", "fcf_premie": 0.04, "p_lag": 20, "p_hog": 70, "dcf_marginal": 0.25,
                  "dcf_ar": 7, "tillv_term": 0.02, "w_fcf": 1.0, "w_pe": 1.0, "w_dcf": 1.0,
                  "rev_grans": -0.05, "nd_max": 2.0, "max_vikt": 0.10, "hall_ar": 3},
    },
}
STANDARD_STRATEGI = "B"

STANDARD_INSTALLNINGAR = {
    "strategi": STANDARD_STRATEGI,
    "rantor": {"SEK": 0.033, "USD": 0.051},  # 10-åriga statsobligationer – uppdatera vid behov
    "rf_standard": 0.035,   # riskfri ränta för valutor som saknas ovan
    "rebal_band": 0.05,     # ETF/fond: tillåten avvikelse från målvikt
    "hist_ar": 5,           # år P/E-historik
    "dra_sbc": True,        # dra av aktieersättningar från FCF
    **STRATEGIER[STANDARD_STRATEGI]["param"],
}

INDEX_MIN, INDEX_MAX = 50, 200
KATEGORI = {"Aktie": "Aktier", "Cyklisk": "Aktier", "Fond": "Fonder", "ETF": "ETF:er"}


def tillampa_strategi(inst, kod):
    ny = dict(inst)
    ny.update(STRATEGIER[kod]["param"])
    ny["strategi"] = kod
    return ny


def matchar_strategi(inst):
    """Returnerar strategikoden om parametrarna exakt motsvarar en strategi, annars 'Egen'."""
    for kod, s in STRATEGIER.items():
        def lika(a, b):
            if isinstance(b, str):
                return a == b
            try:
                return abs(float(a) - float(b)) < 1e-9
            except (TypeError, ValueError):
                return False
        if all(lika(inst.get(k), v) for k, v in s["param"].items()):
            return kod
    return "Egen"


# ---------------------------------------------------------------- hjälpfunktioner
def _klamp(v):
    return max(INDEX_MIN, min(INDEX_MAX, v))


def _tal(v):
    try:
        f = float(v)
        return None if f != f else f  # NaN -> None
    except (TypeError, ValueError):
        return None


def dcf_varde(fcf, g0, r, n, gt, hall=0):
    """DCF där tillväxten g0 hålls i 'hall' år och sedan avtar linjärt till gt fram till år n,
    därefter evig tillväxt gt."""
    n = max(int(n), int(hall) + 1)
    pv, cf = 0.0, fcf
    for t in range(1, n + 1):
        if t <= hall:
            g = g0
        else:
            steg = n - hall
            g = g0 + (gt - g0) * (t - hall) / steg if steg > 0 else gt
        cf *= 1 + g
        pv += cf / (1 + r) ** t
    return pv + cf * (1 + gt) / (r - gt) / (1 + r) ** n


def implicit_tillvaxt(borsvarde, fcf, r, n, gt, hall=0):
    """Den tillväxt (med samma bana som prognosen) som gör DCF-värdet lika med dagens börsvärde."""
    if not borsvarde or not fcf or fcf <= 0 or r is None or r <= gt + 0.005:
        return None
    lag, hog = -0.5, 2.0
    if dcf_varde(fcf, lag, r, n, gt, hall) > borsvarde or dcf_varde(fcf, hog, r, n, gt, hall) < borsvarde:
        return None
    for _ in range(80):
        mitt = (lag + hog) / 2
        if dcf_varde(fcf, mitt, r, n, gt, hall) < borsvarde:
            lag = mitt
        else:
            hog = mitt
    return (lag + hog) / 2


def avkastningskrav(inst, rf):
    if inst.get("krav_metod", "fast") == "fast":
        return inst["avk_krav_fast"]
    return rf + inst["erp"]


# ---------------------------------------------------------------- värdering per innehav
def vardera(innehav, data, inst):
    """Värderar ett innehav. Vikt, maxvikt och ETF/fond-signal sätts i vardera_portfolj."""
    typ = innehav.get("typ") or data.get("typ") or "Aktie"
    valuta = data.get("valuta")
    rf = inst["rantor"].get((valuta or "").upper(), inst["rf_standard"])
    r = avkastningskrav(inst, rf)
    egen_g = _tal(innehav.get("tillvaxt"))
    g = egen_g if egen_g is not None else data.get("g_ref")
    g_kalla = "Egen" if egen_g is not None else data.get("g_kalla")
    manuell = _tal(innehav.get("manuell_kurs_sek"))
    kurs_sek = manuell if manuell else data.get("kurs_sek")
    antal = _tal(innehav.get("antal"))

    res = {
        "ticker": innehav.get("ticker"), "typ": typ, "kategori": KATEGORI.get(typ, "Aktier"),
        "namn": data.get("namn") or innehav.get("namn"), "valuta": valuta, "kurs": data.get("kurs"),
        "kurs_sek": kurs_sek, "varde_sek": antal * kurs_sek if antal is not None and kurs_sek else None,
        "riskfri": rf, "avk_krav": r, "notering": data.get("notering") or "",
        "fcf_yield": None, "implicit_tillvaxt": None, "forvantad_tillvaxt": g, "g_kalla": g_kalla,
        "index_fcf": None, "index_pe": None, "index_dcf": None,
        "sparr": None, "index": None, "signal": None, "orsak": "",
        "pe_nu": data.get("pe_nu"), "pe_median": data.get("pe_median"), "pe_pct": data.get("pe_pct"),
        "hist_ar": data.get("hist_ar"), "eps_rev": data.get("eps_rev"), "nd_ebitda": data.get("nd_ebitda"),
        "borsvarde_mn": data.get("borsvarde_mn"), "fcf_mn": data.get("fcf_mn"),
        "riktkurs_uppsida": data.get("riktkurs_uppsida"), "antal_analytiker": data.get("antal_analytiker"),
        "malvikt": _tal(innehav.get("malvikt")), "billig": {}, "dyr": {},
    }
    if typ in ("ETF", "Fond"):
        return res

    mcap = data.get("borsvarde_mn")
    bas = inst.get("fcf_bas", "senaste")
    fcf = data.get(f"fcf_{bas}_mn")
    if fcf is None:  # reserv om vald bas saknas
        fcf = data.get("fcf_senaste_mn") if data.get("fcf_senaste_mn") is not None else data.get("fcf_mn")
    res["fcf_mn"], res["fcf_bas"] = fcf, bas
    hall = int(inst.get("hall_ar", 5))  # samma oavsett källa till prognosen
    res["hall_ar"] = hall
    pe_nu, pe_med, pe_pct = data.get("pe_nu"), data.get("pe_median"), data.get("pe_pct")

    # Delindex (100 = rimligt värderad)
    if mcap and mcap > 0 and fcf is not None:
        res["fcf_yield"] = fcf / mcap
    fy = res["fcf_yield"]
    if fy is not None and fy > 0:
        res["index_fcf"] = _klamp((rf + inst["fcf_premie"]) / fy * 100)
    if pe_nu is not None and pe_med:
        res["index_pe"] = _klamp(pe_nu / pe_med * 100)
    if g is not None and fcf and fcf > 0 and mcap and r > inst["tillv_term"] + 0.005:
        res["index_dcf"] = _klamp(mcap / dcf_varde(fcf, g, r, int(inst["dcf_ar"]), inst["tillv_term"], hall) * 100)
    if mcap and fcf:
        res["implicit_tillvaxt"] = implicit_tillvaxt(mcap, fcf, r, int(inst["dcf_ar"]), inst["tillv_term"], hall)

    # Billigt / dyrt per mått (None = data saknas)
    marg = inst["dcf_marginal"] * 100
    idcf = res["index_dcf"]
    matt = {
        "FCF": (None if fy is None else (fy > 0 and fy >= rf + inst["fcf_premie"]),
                None if fy is None else (fy > 0 and fy <= rf), inst["w_fcf"], res["index_fcf"]),
        "P/E": (None if pe_pct is None else pe_pct <= inst["p_lag"],
                None if pe_pct is None else pe_pct >= inst["p_hog"], inst["w_pe"], res["index_pe"]),
        "DCF": (None if idcf is None else idcf <= 100 - marg,
                None if idcf is None else idcf >= 100 + marg, inst["w_dcf"], idcf),
    }
    total_w = sum(w for _, _, w, _ in matt.values() if w > 0)
    tillg = {k: v for k, v in matt.items() if v[2] > 0 and v[0] is not None}
    tillg_w = sum(v[2] for v in tillg.values())
    res["billig"] = {k: v[0] for k, v in tillg.items()}
    res["dyr"] = {k: v[1] for k, v in tillg.items()}

    # Index: viktat snitt av tillgängliga delindex med vikt > 0
    idx = [(v[3], v[2]) for v in matt.values() if v[2] > 0 and v[3] is not None]
    if idx and sum(w for _, w in idx) > 0:
        res["index"] = sum(i * w for i, w in idx) / sum(w for _, w in idx)

    # Spärr
    rev, nd = data.get("eps_rev"), data.get("nd_ebitda")
    sparr_orsak = []
    if rev is not None and rev <= inst["rev_grans"]:
        sparr_orsak.append(f"vinstprognos {rev:+.0%} på 90 d")
    if nd is not None and nd > inst["nd_max"]:
        sparr_orsak.append(f"nettoskuld/EBITDA {nd:.1f}")
    res["sparr"] = bool(sparr_orsak)

    # Signal: viktad majoritet (> 50 %) av de mått som har data och vikt > 0
    if total_w == 0 or tillg_w < 0.5 * total_w - 1e-9 or not tillg:
        res["signal"] = "För lite data"
        res["orsak"] = "För få mått med data"
        return res
    billig_andel = sum(v[2] for v in tillg.values() if v[0]) / tillg_w
    dyr_andel = sum(v[2] for v in tillg.values() if v[1]) / tillg_w
    billiga = [k for k, v in tillg.items() if v[0]]
    dyra = [k for k, v in tillg.items() if v[1]]
    if dyr_andel > 0.5:
        res["signal"], res["orsak"] = "Minska", "Dyr: " + ", ".join(dyra)
    elif res["sparr"]:
        res["signal"], res["orsak"] = "Granska", "Spärr: " + ", ".join(sparr_orsak)
    elif billig_andel > 0.5:
        res["signal"], res["orsak"] = "Öka", "Billig: " + ", ".join(billiga)
    else:
        res["signal"] = "Behåll"
        delar = ([f"billig: {', '.join(billiga)}"] if billiga else []) + ([f"dyr: {', '.join(dyra)}"] if dyra else [])
        res["orsak"] = ("Blandat – " + "; ".join(delar)) if delar else "Neutralt värderad"
    return res


def vardera_portfolj(innehav_lista, data_per_ticker, inst):
    """Värderar alla innehav, räknar vikter, maxvikt och ETF/fond-signaler."""
    rader = [vardera(h, data_per_ticker.get(h["ticker"], {}), inst) for h in innehav_lista]
    total = sum(r["varde_sek"] for r in rader if r["varde_sek"])
    max_vikt = inst.get("max_vikt") or 0
    for r in rader:
        r["vikt"] = r["varde_sek"] / total if total and r["varde_sek"] else None
        vikt = r["vikt"]
        if r["typ"] in ("ETF", "Fond"):
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
            elif r["signal"] == "Granska":
                r["orsak"] = f"{r['orsak']}; {text}"
            else:
                r["signal"] = "Minska"
                r["orsak"] = f"{text[0].upper()}{text[1:]}" + (f"; {r['orsak']}" if r["orsak"] else "")
    return rader
