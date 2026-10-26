# -*- coding: utf-8 -*-
"""Portföljvärdering – Streamlit-app. Starta lokalt med:  streamlit run app.py"""
import time

import altair as alt
import pandas as pd
import streamlit as st

import avanza
from data import hamta, sok_ticker
from storage import KOLUMNER, Lagring
from valuation import (INDEX_MAX, INDEX_MIN, STANDARD_INSTALLNINGAR, STRATEGI_NYCKLAR, STRATEGIER,
                       matchar_strategi, tillampa_strategi, vardera_portfolj)

st.set_page_config(page_title="Portföljvärdering", page_icon="📊", layout="wide")

SIGNALFARGER = {
    "Öka": ("#C6EFCE", "#006100"),
    "Minska": ("#FFC7CE", "#9C0006"),
    "Behåll": ("#EDEDED", "#3A3A3A"),
    "Granska": ("#FFEB9C", "#9C5700"),
    "För lite data": ("#FFFFFF", "#808080"),
}
TYPER = ["Aktie", "Cyklisk", "ETF", "Fond"]
CACHE_TIMMAR = 24
SIDOR = ["Översikt", "Detaljer", "Innehav", "Avanza-import", "Inställningar", "Om metoden"]


# ================================================================ resurser
def hamta_lagring():  # inte cachad – nya Secrets ska slå igenom direkt
    """Returnerar (lagring, varning). Varningen förklarar varför GitHub-sparning inte används."""
    try:
        alla = dict(st.secrets)
    except Exception:
        alla = {}
    if not alla:
        return Lagring(None), ("Inga Secrets hittades. Lägg in GitHub-uppgifterna under Settings → Secrets "
                               "i Streamlit och spara.")
    if "github" not in alla:
        hittade = ", ".join(alla.keys())
        return Lagring(None), (f"Secrets finns ({hittade}) men raden [github] saknas. "
                               "Första raden i Secrets ska vara exakt [github].")
    github = dict(alla["github"])
    saknas = [k for k in ("token", "repo") if not str(github.get(k, "")).strip()]
    if saknas:
        return Lagring(None), (f"Under [github] saknas: {', '.join(saknas)}. "
                               "Kontrollera stavningen och att värdena står inom citattecken.")
    return Lagring(github), None


@st.cache_data(ttl=CACHE_TIMMAR * 3600, show_spinner=False)
def hamta_cachad(symbol, typ, hist_ar, dra_sbc):
    data = hamta(symbol, typ, hist_ar, dra_sbc)
    time.sleep(0.3)  # skonsamt mot Yahoo; körs bara när datan inte redan finns i cachen
    return data


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def sok_cachad(isin, namn, kortnamn, typ):
    return sok_ticker(isin, namn, kortnamn, typ)


lagring, lagring_varning = hamta_lagring()
if "portfolj" not in st.session_state:
    try:
        st.session_state.portfolj, st.session_state.ar_exempel = lagring.las_portfolj()
        st.session_state.inst = lagring.las_installningar(STANDARD_INSTALLNINGAR, STRATEGI_NYCKLAR)
    except Exception as e:
        st.error(f"Kunde inte läsa sparade uppgifter ({lagring.beskrivning}): {e}")
        st.stop()
inst = st.session_state.inst


def spara_inst(ny):
    try:
        lagring.spara_installningar(ny)
        st.session_state.inst = ny
        return True
    except Exception as e:
        st.error(f"Kunde inte spara inställningarna: {e}")
        return False


# ================================================================ sidomeny
STRATEGIVAL = list(STRATEGIER) + (["Egen"] if inst.get("strategi") == "Egen" else [])


def byt_strategi():
    kod = st.session_state.strategival
    if kod in STRATEGIER and kod != inst.get("strategi"):
        spara_inst(tillampa_strategi(inst, kod))


with st.sidebar:
    st.markdown("### 📊 Portföljvärdering")
    sida = st.radio("Meny", SIDOR, label_visibility="collapsed")
    st.divider()
    st.selectbox("Strategi", STRATEGIVAL, key="strategival",
                 index=STRATEGIVAL.index(inst.get("strategi", "B")) if inst.get("strategi", "B") in STRATEGIVAL else 1,
                 format_func=lambda k: STRATEGIER[k]["namn"] if k in STRATEGIER else "Egen (justerad)",
                 on_change=byt_strategi)
    aktuell = inst.get("strategi", "B")
    st.caption(STRATEGIER[aktuell]["kort"] if aktuell in STRATEGIER else
               "Egna parametrar. Välj en strategi ovan för att återgå till förinställda värden.")
    st.caption(f"Sparas: {lagring.beskrivning}")


# ================================================================ hjälpfunktioner
def innehav_lista(df):
    rader = []
    for _, r in df.iterrows():
        tk = str(r["ticker"]).strip().upper() if pd.notna(r["ticker"]) else ""
        if not tk:
            continue
        pct = lambda v: None if pd.isna(v) else float(v) / 100
        rader.append({
            "ticker": tk,
            "namn": r["namn"] if pd.notna(r.get("namn")) else None,
            "typ": r["typ"] if pd.notna(r["typ"]) and r["typ"] else None,
            "antal": None if pd.isna(r["antal"]) else float(r["antal"]),
            "tillvaxt": pct(r["tillvaxt_pct"]),
            "malvikt": pct(r["malvikt_pct"]),
            "manuell_kurs_sek": None if pd.isna(r["manuell_kurs_sek"]) else float(r["manuell_kurs_sek"]),
        })
    return rader


def hamta_all_data(lista):
    data = {}
    if not lista:
        return data
    rad = st.progress(0.0, text="Hämtar data…")
    for i, h in enumerate(lista, 1):
        rad.progress(i / len(lista), text=f"Hämtar {h['ticker']} ({i}/{len(lista)})")
        try:
            data[h["ticker"]] = hamta_cachad(h["ticker"], h["typ"], int(inst["hist_ar"]), bool(inst["dra_sbc"]))
        except Exception as e:
            data[h["ticker"]] = {"ok": False, "notering": f"Fel vid hämtning: {e}"}
    rad.empty()
    return data


def kr(v):
    return "–" if v is None or pd.isna(v) else f"{v:,.0f} kr".replace(",", " ")


def indexfarg(v):
    """Grönt under 100, vitt runt 100, rött över 100."""
    if v is None or pd.isna(v):
        return ""
    t = max(-1.0, min(1.0, (v - 100) / 30))
    if t < 0:
        r, g, b = (int(255 + (99 - 255) * -t), int(255 + (190 - 255) * -t), int(255 + (123 - 255) * -t))
    else:
        r, g, b = (int(255 + (248 - 255) * t), int(255 + (105 - 255) * t), int(255 + (107 - 255) * t))
    return f"background-color: rgb({r},{g},{b}); font-weight: 600"


def signalstil(v):
    bg, fg = SIGNALFARGER.get(v, ("", ""))
    return f"background-color: {bg}; color: {fg}; font-weight: 700" if bg else ""


def berakna():
    lista = innehav_lista(st.session_state.portfolj)
    data = hamta_all_data(lista)
    return data, pd.DataFrame(vardera_portfolj(lista, data, inst))


# ================================================================ Översikt
def sida_oversikt():
    data, res = berakna()
    if st.session_state.get("ar_exempel"):
        st.info("Det här är exempelinnehav. Importera från Avanza eller lägg in dina egna under **Innehav**.")
    if res.empty:
        st.write("Inga innehav ännu – importera från Avanza eller lägg till under **Innehav**.")
        return
    if lagring_varning:
        st.warning("⚠️ Innehaven sparas bara tillfälligt. " + lagring_varning)

    totalt = res["varde_sek"].sum(skipna=True)
    summa = {k: res.loc[res["kategori"] == k, "varde_sek"].sum(skipna=True) for k in ["Aktier", "Fonder", "ETF:er"]}
    andel = lambda v: f"{v / totalt:.0%} av totalt" if totalt else None
    k = st.columns(4)
    k[0].metric("Totalt värde", kr(totalt))
    for col, (namn, v) in zip(k[1:], summa.items()):
        col.metric(namn, kr(v), andel(v), delta_color="off")

    s = st.columns([1, 1, 1, 2])
    s[0].metric("Öka", int((res["signal"] == "Öka").sum()))
    s[1].metric("Minska", int((res["signal"] == "Minska").sum()))
    s[2].metric("Granska", int((res["signal"] == "Granska").sum()))
    with s[3]:
        aldst = min((d.get("hamtad") for d in data.values() if d.get("hamtad")), default="–")
        st.caption(f"Data hämtad {aldst}. Hämtas automatiskt en gång per dygn.")
        if st.button("🔄 Hämta ny data nu"):
            hamta_cachad.clear()
            st.rerun()

    pct = "{:.1%}"
    # ---------- Aktier
    aktier = res[res["kategori"] == "Aktier"].sort_values("varde_sek", ascending=False, na_position="last")
    st.subheader(f"Aktier · {kr(summa['Aktier'])}")
    if aktier.empty:
        st.caption("Inga aktier.")
    else:
        t = aktier[["ticker", "namn", "signal", "index", "orsak", "varde_sek", "vikt", "implicit_tillvaxt",
                    "forvantad_tillvaxt", "g_kalla", "riktkurs_uppsida", "fcf_yield", "pe_nu", "pe_pct",
                    "notering"]].rename(columns={
            "ticker": "Ticker", "namn": "Namn", "signal": "Signal", "index": "Index", "orsak": "Orsak",
            "varde_sek": "Värde (SEK)", "vikt": "Vikt", "implicit_tillvaxt": "Prisets tillväxt",
            "forvantad_tillvaxt": "Förväntad tillväxt", "g_kalla": "Källa", "riktkurs_uppsida": "Till riktkurs",
            "fcf_yield": "FCF-yield", "pe_nu": "P/E", "pe_pct": "P/E-percentil", "notering": "Notering"})
        st.dataframe(t.style.map(signalstil, subset=["Signal"]).map(indexfarg, subset=["Index"])
                     .format({"Index": "{:.0f}", "Värde (SEK)": "{:,.0f}", "Vikt": pct, "Prisets tillväxt": pct,
                              "Förväntad tillväxt": pct, "Till riktkurs": "{:+.0%}", "FCF-yield": pct,
                              "P/E": "{:.1f}", "P/E-percentil": "{:.0f}"}, na_rep="–"),
                     hide_index=True, width="stretch")
        st.caption("Index: 100 = rimligt värderad, under 100 = undervärderad, över 100 = övervärderad. "
                   "**Prisets tillväxt** är den tillväxt i fritt kassaflöde som dagens kurs förutsätter. "
                   "**Förväntad tillväxt** är analytikernas (eller historisk). Ligger prisets klart över den "
                   "förväntade är aktien dyr mot förväntningarna.")

    # ---------- Fonder och ETF:er
    for kat in ["Fonder", "ETF:er"]:
        df = res[res["kategori"] == kat].sort_values("varde_sek", ascending=False, na_position="last")
        st.subheader(f"{kat} · {kr(summa[kat])}")
        if df.empty:
            st.caption(f"Inga {kat.lower()}.")
            continue
        df = df.assign(avvikelse=df["vikt"] - df["malvikt"])
        t = df[["ticker", "namn", "signal", "orsak", "varde_sek", "vikt", "malvikt", "avvikelse", "kurs_sek",
                "notering"]].rename(columns={
            "ticker": "Ticker", "namn": "Namn", "signal": "Signal", "orsak": "Orsak", "varde_sek": "Värde (SEK)",
            "vikt": "Vikt", "malvikt": "Målvikt", "avvikelse": "Avvikelse", "kurs_sek": "Kurs (SEK)",
            "notering": "Notering"})
        st.dataframe(t.style.map(signalstil, subset=["Signal"])
                     .format({"Värde (SEK)": "{:,.0f}", "Vikt": pct, "Målvikt": pct, "Avvikelse": "{:+.1%}",
                              "Kurs (SEK)": "{:,.2f}"}, na_rep="–"),
                     hide_index=True, width="stretch")
    st.caption("Fonder och ETF:er värderas inte – signalen bygger på avvikelse från målvikten "
               f"(±{inst['rebal_band']:.0%}). Ange målvikt under **Innehav**.")

    graf = aktier[aktier["index"].notna()][["ticker", "index", "signal"]] if not aktier.empty else pd.DataFrame()
    if not graf.empty:
        st.subheader("Värderingsindex per aktie")
        staplar = alt.Chart(graf).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("ticker:N", sort="x", title=None),
            x=alt.X("index:Q", title="Index (100 = rimligt värderad)", scale=alt.Scale(domain=[INDEX_MIN, INDEX_MAX])),
            color=alt.Color("signal:N", title="Signal", scale=alt.Scale(
                domain=list(SIGNALFARGER), range=["#2E9E5B", "#D64545", "#9E9E9E", "#E0A100", "#CCCCCC"])),
            tooltip=["ticker", alt.Tooltip("index:Q", format=".0f"), "signal"])
        linje = alt.Chart(pd.DataFrame({"x": [100]})).mark_rule(strokeDash=[4, 4], color="#555").encode(x="x:Q")
        st.altair_chart((staplar + linje).properties(height=max(120, 34 * len(graf))), width="stretch")


# ================================================================ Detaljer
def sida_detaljer():
    data, res = berakna()
    aktier = (res[res["kategori"] == "Aktier"].sort_values("varde_sek", ascending=False)["ticker"].tolist()
              if not res.empty else [])
    if not aktier:
        st.write("Inga aktier att visa.")
        return
    val = st.selectbox("Välj aktie", aktier,
                       format_func=lambda tk: f"{tk} – {res.loc[res['ticker'] == tk, 'namn'].iloc[0] or ''}")
    r = res[res["ticker"] == val].iloc[0]
    d = data.get(val, {})
    fmt = lambda v, f: "–" if v is None or pd.isna(v) else f.format(v)
    st.subheader(r["namn"] or val)
    c = st.columns(5)
    c[0].metric("Signal", r["signal"] or "–")
    c[1].metric("Index", fmt(r["index"], "{:.0f}"))
    c[2].metric("Index FCF", fmt(r["index_fcf"], "{:.0f}") + ("" if inst["w_fcf"] > 0 else " (av)"))
    c[3].metric("Index P/E", fmt(r["index_pe"], "{:.0f}") + ("" if inst["w_pe"] > 0 else " (av)"))
    c[4].metric("Index DCF", fmt(r["index_dcf"], "{:.0f}") + ("" if inst["w_dcf"] > 0 else " (av)"))
    st.markdown(f"**Orsak:** {r['orsak'] or '–'}")

    def status(namn):
        if namn not in r["billig"]:
            return "⚫ används inte" if inst[{"FCF": "w_fcf", "P/E": "w_pe", "DCF": "w_dcf"}[namn]] == 0 else "⚪ data saknas"
        return "🟢 billigt" if r["billig"][namn] else ("🔴 dyrt" if r["dyr"][namn] else "⚪ neutralt")

    rf = r["riskfri"]
    rader = [
        f"**Tillväxt:** dagens pris förutsätter **{fmt(r['implicit_tillvaxt'], '{:.1%}')}** tillväxt i fritt kassaflöde "
        f"första året (avtagande mot {inst['tillv_term']:.1%} på {int(inst['dcf_ar'])} år). Förväntat: "
        f"**{fmt(r['forvantad_tillvaxt'], '{:.1%}')}** ({r['g_kalla'] or 'saknas'}) → {status('DCF')}",
        f"**FCF-yield** {fmt(r['fcf_yield'], '{:.1%}')} mot ränta {rf:.1%} och rimlig nivå "
        f"{rf + inst['fcf_premie']:.1%} → {status('FCF')}",
        f"**P/E** {fmt(r['pe_nu'], '{:.1f}')} mot median {fmt(r['pe_median'], '{:.1f}')} "
        f"({fmt(r['hist_ar'], '{:.1f}')} års historik), percentil {fmt(r['pe_pct'], '{:.0f}')} → {status('P/E')}",
        f"**Spärr:** vinstrevidering 90 d {fmt(r['eps_rev'], '{:+.1%}')}, nettoskuld/EBITDA "
        f"{fmt(r['nd_ebitda'], '{:.1f}')} → " + ("⚠️ spärr" if r["sparr"] else "OK"),
        f"**Analytikernas riktkurs:** {fmt(r['riktkurs_uppsida'], '{:+.0%}')} från dagens kurs"
        + (f" ({int(r['antal_analytiker'])} analytiker)" if pd.notna(r["antal_analytiker"]) else "")
        + " – visas som information, påverkar inte signalen",
        f"**Vikt i portföljen:** {fmt(r['vikt'], '{:.1%}')}"
        + (f" (maxvikt {inst['max_vikt']:.0%})" if inst["max_vikt"] else ""),
    ]
    st.markdown("\n".join(f"- {x}" for x in rader))
    g_delar = [("Analytiker 5 år", d.get("g_analytiker_5ar")), ("Analytiker 1–2 år", d.get("g_analytiker_kort")),
               ("Historisk omsättning", d.get("g_historisk"))]
    st.caption("Tillväxtkällor: " + " · ".join(f"{n} {fmt(v, '{:.1%}')}" for n, v in g_delar)
               + ". Den första som finns används, begränsad till −5 % – 30 %. Egen tillväxt under Innehav går före.")
    if isinstance(r["notering"], str) and r["notering"]:
        st.caption(f"Notering: {r['notering']}")

    g1, g2 = st.columns(2)
    if d.get("pe_serie"):
        pe = pd.DataFrame(d["pe_serie"], columns=["datum", "P/E"])
        pe["datum"] = pd.to_datetime(pe["datum"])
        lager = [alt.Chart(pe).mark_line(color="#1F3864").encode(
            x=alt.X("datum:T", title=None), y=alt.Y("P/E:Q", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("datum:T"), alt.Tooltip("P/E:Q", format=".1f")])]
        if pd.notna(r["pe_median"]):
            lager.append(alt.Chart(pd.DataFrame({"y": [r["pe_median"]]}))
                         .mark_rule(strokeDash=[4, 4], color="#888").encode(y="y:Q"))
        if pd.notna(r["pe_nu"]):
            lager.append(alt.Chart(pd.DataFrame({"y": [r["pe_nu"]]})).mark_rule(color="#D64545").encode(y="y:Q"))
        g1.markdown("**P/E över tid** (röd = idag, streckad = median)")
        g1.altair_chart(alt.layer(*lager).properties(height=260), width="stretch")
    if d.get("fcf_ar"):
        fc = pd.DataFrame(d["fcf_ar"], columns=["år", "FCF (mn)"])
        g2.markdown(f"**Fritt kassaflöde per år** (mn {r['valuta']})")
        g2.altair_chart(alt.Chart(fc).mark_bar(color="#2E6DB4").encode(
            x=alt.X("år:O", title=None), y="FCF (mn):Q",
            tooltip=["år", alt.Tooltip("FCF (mn):Q", format=",.0f")]).properties(height=260), width="stretch")


# ================================================================ Innehav
def sida_innehav():
    st.write("Redigera dina innehav. Tickers enligt Yahoo Finance: USA t.ex. `MSFT`, Sverige t.ex. `VOLV-B.ST`, "
             "fonder har koder som `0P0000XXXX.ST`. Enklast är att importera från Avanza.")
    if lagring_varning:
        st.warning("⚠️ Innehaven sparas bara tillfälligt och försvinner när appen startas om. " + lagring_varning)
    redigerad = st.data_editor(
        st.session_state.portfolj, num_rows="dynamic", width="stretch", hide_index=True, key="redigerare",
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", required=True),
            "namn": st.column_config.TextColumn("Namn"),
            "typ": st.column_config.SelectboxColumn(
                "Typ", options=TYPER, help="Cyklisk = verkstad, råvaror, halvledare m.m. Tomt = automatiskt."),
            "antal": st.column_config.NumberColumn("Antal", min_value=0, format="%.2f"),
            "tillvaxt_pct": st.column_config.NumberColumn(
                "Egen tillväxt %", format="%.1f %%",
                help="Valfritt. Lämna tomt för att använda analytikernas förväntning. Fyll bara i om du vill "
                     "överstyra, t.ex. för bolag där prognoserna är orimliga."),
            "malvikt_pct": st.column_config.NumberColumn("Målvikt %", format="%.1f %%",
                                                         help="Styr signalen för fonder och ETF:er."),
            "manuell_kurs_sek": st.column_config.NumberColumn(
                "Manuell kurs (SEK)", format="%.2f", help="Om Yahoo saknar kursen. Fylls i av Avanza-importen."),
            "isin": st.column_config.TextColumn("ISIN"),
        },
        column_order=KOLUMNER,
    )
    if st.button("💾 Spara innehav", type="primary"):
        try:
            lagring.spara_portfolj(redigerad)
            st.session_state.portfolj, st.session_state.ar_exempel = lagring.las_portfolj()
            st.success("Sparat.")
            st.rerun()
        except Exception as e:
            st.error(f"Kunde inte spara: {e}")


# ================================================================ Avanza-import
def sida_import():
    st.write("Exportera dina innehav från Avanza (under **Innehav**, välj exportera till fil) och ladda upp filen här. "
             "Samma värdepapper på flera konton slås ihop.")
    fil = st.file_uploader("Avanza-export", type=["csv", "txt", "xlsx", "xls"])
    if fil is None:
        st.session_state.pop("import_forslag", None)
        return
    try:
        rad = avanza.las_fil(fil.getvalue(), fil.name)
    except Exception as e:
        st.error(f"Kunde inte läsa filen: {e}")
        return
    if rad.empty:
        st.error("Filen innehåller inga rader.")
        return

    gissning = avanza.gissa_kolumner(rad)
    with st.expander("Kolumner i filen", expanded=not (gissning.get("antal") and (gissning.get("isin") or gissning.get("namn")))):
        st.caption("Kontrollera att rätt kolumn används för varje uppgift.")
        val = ["(saknas)"] + list(rad.columns)
        kolumner = {}
        cols = st.columns(4)
        for i, (falt, etikett) in enumerate(avanza.FALT.items()):
            standard = gissning.get(falt)
            kolumner[falt] = cols[i % 4].selectbox(etikett, val, index=val.index(standard) if standard in val else 0,
                                                   key=f"kol_{falt}")
        kolumner = {k: (None if v == "(saknas)" else v) for k, v in kolumner.items()}
        st.dataframe(rad.head(5), hide_index=True, width="stretch")
    if not kolumner.get("antal") or not (kolumner.get("isin") or kolumner.get("namn")):
        st.error("Välj åtminstone kolumnerna för antal och ISIN eller namn.")
        return

    tolkad = avanza.tolka(rad, kolumner)
    if tolkad.empty:
        st.error("Hittade inga innehav i filen. Kontrollera kolumnvalen ovan.")
        return
    st.markdown(f"**{len(tolkad)} värdepapper** hittades, totalt {kr(tolkad['varde_sek'].sum(min_count=1))}.")

    nyckel = (fil.name, fil.size, tuple(sorted((k, v or "") for k, v in kolumner.items())))
    if st.session_state.get("import_nyckel") != nyckel:
        st.session_state.pop("import_forslag", None)
        st.session_state.import_nyckel = nyckel

    if "import_forslag" not in st.session_state:
        if st.button("🔍 Föreslå Yahoo-tickers", type="primary"):
            forslag = []
            prog = st.progress(0.0)
            for i, r in tolkad.iterrows():
                prog.progress((i + 1) / len(tolkad), text=f"Söker {r['namn'] or r['isin']}")
                tk, status = sok_cachad(r["isin"], r["namn"], r["kortnamn"], r["typ"])
                antal, varde = r["antal"], r["varde_sek"]
                manuell = varde / antal if (varde and antal and status in ("Ej hittad", "Gissad")) else None
                forslag.append({"Importera": True, "Namn": r["namn"], "ISIN": r["isin"], "Antal": antal,
                                "Värde (SEK)": varde, "Typ": r["typ"], "Ticker": tk or r["isin"] or r["namn"],
                                "Status": status, "Manuell kurs (SEK)": manuell})
            prog.empty()
            st.session_state.import_forslag = pd.DataFrame(forslag)
            st.rerun()
        st.dataframe(tolkad.drop(columns=["typ_avanza"]), hide_index=True, width="stretch")
        return

    st.markdown("Kontrollera tickers och typ. **Gissad** och **Ej hittad** bör du dubbelkolla – för dem fylls "
                "en manuell kurs i från Avanzas värde så att portföljvärdet stämmer ändå.")
    granskad = st.data_editor(
        st.session_state.import_forslag, hide_index=True, width="stretch", key="import_editor",
        disabled=["Namn", "ISIN", "Antal", "Värde (SEK)", "Status"],
        column_config={
            "Importera": st.column_config.CheckboxColumn(),
            "Typ": st.column_config.SelectboxColumn(options=TYPER),
            "Värde (SEK)": st.column_config.NumberColumn(format="%.0f"),
            "Manuell kurs (SEK)": st.column_config.NumberColumn(format="%.2f"),
        })
    satt = st.radio("Hur ska importen göras?",
                    ["Uppdatera mina innehav (behåll egen tillväxt, målvikt och typ)", "Ersätt alla innehav"])
    ersatt = satt.startswith("Ersätt")
    ta_bort = False if ersatt else st.checkbox("Ta bort innehav som inte finns i filen", value=True)
    if st.button("📥 Importera", type="primary"):
        valda = granskad[granskad["Importera"]]
        imp = pd.DataFrame({
            "ticker": valda["Ticker"].astype(str).str.strip().str.upper(), "namn": valda["Namn"],
            "typ": valda["Typ"], "antal": valda["Antal"], "isin": valda["ISIN"],
            "manuell_kurs_sek": valda["Manuell kurs (SEK)"]})
        ny = avanza.sla_ihop(st.session_state.portfolj if not st.session_state.get("ar_exempel") else None,
                             imp, ersatt=ersatt or st.session_state.get("ar_exempel", False), ta_bort_saknade=ta_bort)
        try:
            lagring.spara_portfolj(ny.reindex(columns=KOLUMNER))
            st.session_state.portfolj, st.session_state.ar_exempel = lagring.las_portfolj()
            st.session_state.pop("import_forslag", None)
            st.success(f"Importerade {len(imp)} innehav. Gå till **Översikt** för att se värderingen.")
        except Exception as e:
            st.error(f"Kunde inte spara: {e}")


# ================================================================ Inställningar
def sida_installningar():
    kod = inst.get("strategi", "B")
    st.markdown(f"**Aktiv strategi:** {STRATEGIER[kod]['namn'] if kod in STRATEGIER else 'Egen (justerad)'}")
    if kod in STRATEGIER:
        st.caption(STRATEGIER[kod]["beskrivning"])
    st.caption("Byt strategi i sidomenyn. Ändrar du parametrarna nedan blir strategin 'Egen'.")
    with st.form("installningar"):
        st.markdown("##### Räntor och allmänt")
        rantor = pd.DataFrame([{"Valuta": k, "Ränta %": v * 100} for k, v in inst["rantor"].items()])
        rantor_ny = st.data_editor(rantor, num_rows="dynamic", hide_index=True, key="rantor")
        a, b, c = st.columns(3)
        ny = dict(inst)
        ny["rf_standard"] = a.number_input("Ränta för övriga valutor %", value=inst["rf_standard"] * 100, step=0.1) / 100
        ny["rebal_band"] = b.number_input("Fond/ETF: tillåten avvikelse (procentenheter)",
                                          value=inst["rebal_band"] * 100, step=1.0) / 100
        ny["hist_ar"] = c.number_input("År P/E-historik", value=int(inst["hist_ar"]), min_value=2, max_value=10,
                                       help="Yahoo har oftast 4–5 års bokslut.")
        ny["dra_sbc"] = st.checkbox("Dra av aktieersättningar från FCF (rekommenderas för tech)", value=bool(inst["dra_sbc"]))

        st.markdown("##### Strategiparametrar")
        a, b, c = st.columns(3)
        ny["erp"] = a.number_input("Aktieriskpremie %", value=inst["erp"] * 100, step=0.5,
                                   help="Avkastningskrav = ränta + aktieriskpremie") / 100
        ny["fcf_premie"] = b.number_input("FCF-premie över räntan %", value=inst["fcf_premie"] * 100, step=0.5) / 100
        ny["max_vikt"] = c.number_input("Maxvikt per aktie % (0 = av)", value=inst["max_vikt"] * 100, step=1.0,
                                        min_value=0.0) / 100
        ny["p_lag"] = a.number_input("P/E-percentil för billig", value=int(inst["p_lag"]), min_value=0, max_value=100)
        ny["p_hog"] = b.number_input("P/E-percentil för dyr", value=int(inst["p_hog"]), min_value=0, max_value=100)
        ny["dcf_marginal"] = c.number_input("Säkerhetsmarginal DCF %", value=inst["dcf_marginal"] * 100, step=5.0) / 100
        ny["dcf_ar"] = a.number_input("År innan tillväxten planat ut", value=int(inst["dcf_ar"]), min_value=2, max_value=20)
        ny["tillv_term"] = b.number_input("Långsiktig tillväxt därefter %", value=inst["tillv_term"] * 100, step=0.5) / 100
        ny["rev_grans"] = c.number_input("Spärr: vinstrevidering %", value=inst["rev_grans"] * 100, step=1.0) / 100
        ny["nd_max"] = a.number_input("Spärr: max nettoskuld/EBITDA", value=float(inst["nd_max"]), step=0.5)
        ny["w_fcf"] = b.number_input("Vikt FCF (0 = av)", value=float(inst["w_fcf"]), step=0.5, min_value=0.0)
        ny["w_pe"] = c.number_input("Vikt P/E (0 = av)", value=float(inst["w_pe"]), step=0.5, min_value=0.0)
        ny["w_dcf"] = a.number_input("Vikt DCF (0 = av)", value=float(inst["w_dcf"]), step=0.5, min_value=0.0)
        if st.form_submit_button("💾 Spara inställningar", type="primary"):
            ny["rantor"] = {str(rw["Valuta"]).strip().upper(): float(rw["Ränta %"]) / 100
                            for _, rw in rantor_ny.iterrows()
                            if pd.notna(rw["Valuta"]) and str(rw["Valuta"]).strip() and pd.notna(rw["Ränta %"])}
            ny["strategi"] = matchar_strategi(ny)
            if spara_inst(ny):
                st.session_state.pop("strategival", None)
                st.success("Sparat.")
                st.rerun()
    if kod not in STRATEGIER or matchar_strategi(inst) != kod:
        if st.button("Återställ till strategi B (Balanserad)"):
            if spara_inst(tillampa_strategi(inst, "B")):
                st.session_state.pop("strategival", None)
                st.rerun()

    st.markdown("##### Jämför strategierna")
    etiketter = {"erp": ("Aktieriskpremie", "{:.1%}"), "fcf_premie": ("FCF-premie", "{:.1%}"),
                 "p_lag": ("P/E-percentil billig", "{:.0f}"), "p_hog": ("P/E-percentil dyr", "{:.0f}"),
                 "dcf_marginal": ("DCF-marginal", "{:.0%}"), "dcf_ar": ("År innan tillväxten planat ut", "{:.0f}"),
                 "tillv_term": ("Långsiktig tillväxt", "{:.1%}"), "w_fcf": ("Vikt FCF", "{:.1f}"),
                 "w_pe": ("Vikt P/E", "{:.1f}"), "w_dcf": ("Vikt DCF", "{:.1f}"),
                 "rev_grans": ("Spärr vinstrevidering", "{:.0%}"), "nd_max": ("Spärr nettoskuld/EBITDA", "{:.1f}"),
                 "max_vikt": ("Maxvikt per aktie", "{:.0%}")}
    jmf = pd.DataFrame({s["namn"]: {etiketter[k][0]: etiketter[k][1].format(v) for k, v in s["param"].items()}
                        for s in STRATEGIER.values()})
    st.dataframe(jmf, width="stretch")


# ================================================================ Om metoden
def sida_om():
    st.markdown(f"""
**Tre mått** bedöms som billigt, neutralt eller dyrt för varje aktie:

1. **DCF – prisets tillväxt mot förväntad tillväxt.** Appen räknar ut vilken tillväxt i fritt kassaflöde som
   dagens kurs förutsätter (tillväxten antas avta jämnt till {inst['tillv_term']:.1%} på {int(inst['dcf_ar'])} år,
   diskonterat med ränta + {inst['erp']:.1%}). Den jämförs med analytikernas förväntade tillväxt – i första hand
   femårsprognosen, annars prognosen för i år och nästa år, och sist bolagets historiska omsättningstillväxt.
   Billigt om priset ligger minst {inst['dcf_marginal']:.0%} under värdet med den förväntade tillväxten.
2. **FCF-yield mot räntan.** Snitt av fritt kassaflöde de senaste tre åren delat med börsvärdet. Billigt över
   räntan + {inst['fcf_premie']:.1%}, dyrt under räntan.
3. **P/E mot egen historik.** Billigt bland de lägsta {inst['p_lag']} %, dyrt bland de högsta {100 - inst['p_hog']} %.

**Signal:** måtten röstar med sina vikter (vikt 0 = röstar inte). *Minska* om mer än hälften av vikten säger dyrt.
*Granska* om spärren slår till (vinstprognos sänkt mer än {abs(inst['rev_grans']):.0%} på 90 dagar eller nettoskuld
över {inst['nd_max']:.1f} × EBITDA). *Öka* om mer än hälften säger billigt. Annars *Behåll*. Om mått motsvarande
minst hälften av vikten saknar data visas *För lite data*.

**Maxvikt:** en aktie som väger mer än {inst['max_vikt']:.0%} av portföljen får *Minska*, och en köpsignal blir
*Behåll*. Sätt maxvikt till 0 för att stänga av.

**Index:** viktat snitt av delindexen, vart och ett begränsat till {INDEX_MIN}–{INDEX_MAX}. 100 = rimligt värderad.

**Fonder och ETF:er** värderas inte. Signalen bygger på ombalansering mot målvikten (±{inst['rebal_band']:.0%}).

**Analytikernas riktkurs** visas som information men påverkar inte signalen, eftersom riktkurser ofta följer kursen.

**Begränsningar:** Yahoo Finance är gratis men inofficiellt, och analytikerprognoser är ofta för optimistiska om
tillväxtbolag. P/E-historiken räcker oftast 4–5 år. Banker och försäkringsbolag passar dåligt för FCF-måttet.
Verktyget är ett beslutsstöd, inte investeringsrådgivning.
""")


{"Översikt": sida_oversikt, "Detaljer": sida_detaljer, "Innehav": sida_innehav, "Avanza-import": sida_import,
 "Inställningar": sida_installningar, "Om metoden": sida_om}[sida]()
