# -*- coding: utf-8 -*-
"""Läser Avanzas export av innehav (CSV eller Excel) och slår ihop den med appens innehav.

Avanzas kolumnnamn har ändrats över tid, så kolumnerna matchas på namn med flera alternativ
och kan rättas för hand i appen.
"""
import csv
import io
import re
import unicodedata

import pandas as pd

FALT = {
    "namn": "Namn",
    "kortnamn": "Kortnamn / ticker",
    "isin": "ISIN",
    "antal": "Antal / volym",
    "varde": "Marknadsvärde (SEK)",
    "valuta": "Valuta",
    "typ": "Typ av värdepapper",
}
ALIAS = {
    "namn": ["namn", "vardepapper", "instrument", "name", "vardepappersnamn", "beskrivning"],
    "kortnamn": ["kortnamn", "ticker", "symbol", "kortnamnticker"],
    "isin": ["isin", "isinkod"],
    "antal": ["volym", "antal", "quantity", "innehav", "antalandelar"],
    "varde": ["marknadsvarde", "marknadsvardesek", "marknadsvardeisek", "varde", "vardesek",
              "marketvalue", "aktuelltvarde"],
    "valuta": ["valuta", "currency", "handelsvaluta"],
    "typ": ["typ", "vardepapperstyp", "instrumenttyp", "type", "typavvardepapper"],
}
INTE_VARDEPAPPER = ("likvida medel", "kassa", "saldo", "summa", "totalt")


def _norm(text):
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", t.lower())


def las_fil(innehall, filnamn=""):
    """Läser bytes från en uppladdad fil till en DataFrame med originalkolumnerna (som text)."""
    if filnamn.lower().endswith((".xlsx", ".xls")) or innehall[:2] == b"PK":
        return pd.read_excel(io.BytesIO(innehall), dtype=str)
    text = None
    for kod in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = innehall.decode(kod)
            if "\x00" in text:
                continue
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Kunde inte läsa filens teckenkodning.")
    forsta = text.splitlines()[0] if text.splitlines() else ""
    try:
        sep = csv.Sniffer().sniff(forsta, delimiters=";,\t").delimiter
    except csv.Error:
        sep = ";" if forsta.count(";") >= forsta.count(",") else ","
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def gissa_kolumner(df):
    """Föreslår vilken kolumn i filen som motsvarar varje fält."""
    normade = {c: _norm(c) for c in df.columns}
    forslag = {}
    for falt, alias in ALIAS.items():
        traff = next((c for c, n in normade.items() if n in alias), None)
        if traff is None:
            traff = next((c for c, n in normade.items() if any(n.startswith(a) for a in alias)), None)
        if falt == "varde" and traff is None:
            traff = next((c for c, n in normade.items() if "marknadsvarde" in n), None)
        forslag[falt] = traff
    # Samma kolumn ska inte användas till två fält
    anvanda = set()
    for falt in ["isin", "antal", "varde", "namn", "kortnamn", "valuta", "typ"]:
        if forslag.get(falt) in anvanda:
            forslag[falt] = None
        elif forslag.get(falt):
            anvanda.add(forslag[falt])
    return forslag


def _tal(v):
    if v is None:
        return None
    s = str(v).strip().replace(" ", "").replace(" ", "").replace("−", "-")
    s = re.sub(r"[^0-9,.\-]", "", s)
    if not s or s in ("-", ".", ","):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def tolka_typ(v):
    t = _norm(v)
    if not t:
        return None
    if "exchangetraded" in t or "etf" in t or "borshandlad" in t:
        return "ETF"
    if "fond" in t or "fund" in t:
        return "Fond"
    if any(k in t for k in ("aktie", "stock", "share", "equity")):
        return "Aktie"
    return None


def tolka(df, kolumner):
    """Gör om exporten till en rad per värdepapper. Samma värdepapper på flera konton slås ihop."""
    def kol(falt):
        c = kolumner.get(falt)
        return df[c] if c and c in df.columns else pd.Series([None] * len(df), index=df.index)

    ut = pd.DataFrame({
        "namn": kol("namn").astype(str).str.strip().replace({"None": None, "": None}),
        "kortnamn": kol("kortnamn").astype(str).str.strip().replace({"None": None, "": None}),
        "isin": kol("isin").astype(str).str.strip().str.upper().replace({"NONE": None, "": None}),
        "antal": kol("antal").map(_tal),
        "varde_sek": kol("varde").map(_tal),
        "valuta": kol("valuta").astype(str).str.strip().replace({"None": None, "": None}),
        "typ_avanza": kol("typ").astype(str).str.strip().replace({"None": None, "": None}),
    })
    ut["typ"] = ut["typ_avanza"].map(tolka_typ)
    namn_lagre = ut["namn"].fillna("").str.lower()
    ut = ut[~namn_lagre.str.startswith(INTE_VARDEPAPPER)]
    ut = ut[(ut["antal"].fillna(0) > 0) & (ut["namn"].notna() | ut["isin"].notna())]
    if ut.empty:
        return ut.reset_index(drop=True)
    ut["nyckel"] = ut["isin"].fillna(ut["namn"])
    grupp = ut.groupby("nyckel", sort=False).agg({
        "namn": "first", "kortnamn": "first", "isin": "first", "antal": "sum",
        "varde_sek": lambda s: s.sum(min_count=1), "valuta": "first", "typ_avanza": "first", "typ": "first"})
    return grupp.reset_index(drop=True)


def sla_ihop(nuvarande, import_df, ersatt=False, ta_bort_saknade=False):
    """nuvarande: appens innehav (storage.KOLUMNER). import_df: kolumner ticker, namn, typ, antal,
    isin, manuell_kurs_sek. Vid sammanslagning behålls egen tillväxt, målvikt och typ."""
    imp = import_df.copy()
    if ersatt or nuvarande is None or nuvarande.empty:
        return imp.reindex(columns=nuvarande.columns if nuvarande is not None else imp.columns)
    nu = nuvarande.copy()
    nu["_isin"] = nu["isin"].fillna("").astype(str).str.upper()
    nu["_tk"] = nu["ticker"].fillna("").astype(str).str.upper()
    traffade = set()
    nya = []
    for _, r in imp.iterrows():
        isin, tk = str(r.get("isin") or "").upper(), str(r.get("ticker") or "").upper()
        m = nu.index[(nu["_isin"] == isin) & (isin != "")].tolist() or nu.index[(nu["_tk"] == tk) & (tk != "")].tolist()
        if m:
            i = m[0]
            traffade.add(i)
            nu.at[i, "antal"] = r["antal"]
            nu.at[i, "manuell_kurs_sek"] = r.get("manuell_kurs_sek")
            for k in ("isin", "namn"):
                if r.get(k) and (pd.isna(nu.at[i, k]) or not nu.at[i, k]):
                    nu.at[i, k] = r[k]
            if (pd.isna(nu.at[i, "typ"]) or not nu.at[i, "typ"]) and r.get("typ"):
                nu.at[i, "typ"] = r["typ"]
        else:
            nya.append(r)
    if ta_bort_saknade:
        nu = nu.loc[sorted(traffade)]
    nu = nu.drop(columns=["_isin", "_tk"])
    if nya:
        nu = pd.concat([nu, pd.DataFrame(nya).reindex(columns=nu.columns)], ignore_index=True)
    return nu.reset_index(drop=True)
