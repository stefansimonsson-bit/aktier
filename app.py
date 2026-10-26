# -*- coding: utf-8 -*-
"""Portföljvärdering – Streamlit-app. Starta lokalt med:  streamlit run app.py"""
import time

import altair as alt
import pandas as pd
import streamlit as st

from data import hamta
from storage import KOLUMNER, Lagring
from valuation import INDEX_MAX, INDEX_MIN, STANDARD_INSTALLNINGAR, vardera_portfolj

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


lagring, lagring_varning = hamta_lagring()
if "portfolj" not in st.session_state:
    try:
        st.session_state.portfolj, st.session_state.ar_exempel = lagring.las_portfolj()
        st.session_state.inst = lagring.las_installningar(STANDARD_INSTALLNINGAR)
    except Exception as e:
        st.error(f"Kunde inte läsa sparade uppgifter ({lagring.beskrivning}): {e}")
        st.stop()

inst = st.session_state.inst


def innehav_lista(df):
    rader = []
    for _, r in df.iterrows():
        tk = str(r["ticker"]).strip().upper() if pd.notna(r["ticker"]) else ""
        if not tk:
            continue
        pct = lambda v: None if pd.isna(v) else float(v) / 100
        rader.append({
            "ticker": tk,
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


# ================================================================ data
lista = innehav_lista(st.session_state.portfolj)
data = hamta_all_data(lista)
rader = vardera_portfolj(lista, data, inst)
res = pd.DataFrame(rader)

# ================================================================ sidhuvud
st.title("📊 Portföljvärdering")
if st.session_state.get("ar_exempel"):
    st.info("Det här är exempelinnehav. Lägg in dina egna under fliken **Innehav** och spara.")

flikar = st.tabs(["Översikt", "Innehav", "Detaljer", "Inställningar", "Om metoden"])

# ================================================================ Översikt
with flikar[0]:
    if res.empty:
        st.write("Inga innehav ännu – lägg till under fliken **Innehav**.")
    else:
        k1, k2, k3, k4, k5 = st.columns(5)
        totalt = res["varde_sek"].sum(skipna=True)
        k1.metric("Portföljvärde", f"{totalt:,.0f} kr".replace(",", " "))
        k2.metric("Öka", int((res["signal"] == "Öka").sum()))
        k3.metric("Minska", int((res["signal"] == "Minska").sum()))
        k4.metric("Granska", int((res["signal"] == "Granska").sum()))
        aldst = min((d.get("hamtad") for d in data.values() if d.get("hamtad")), default="–")
        k5.metric("Data hämtad", aldst)

        if st.button("🔄 Hämta ny data", help=f"Data cachas i {CACHE_TIMMAR} timmar för att inte belasta Yahoo."):
            hamta_cachad.clear()
            st.rerun()

        tabell = res[["ticker", "namn", "typ", "signal", "index", "vikt", "varde_sek", "fcf_yield",
                      "pe_nu", "pe_pct", "implicit_tillvaxt", "tillvaxt", "notering"]].rename(columns={
            "ticker": "Ticker", "namn": "Namn", "typ": "Typ", "signal": "Signal", "index": "Index",
            "vikt": "Vikt", "varde_sek": "Värde (SEK)", "fcf_yield": "FCF-yield", "pe_nu": "P/E",
            "pe_pct": "P/E-percentil", "implicit_tillvaxt": "Marknadens tillväxt",
            "tillvaxt": "Din tillväxt", "notering": "Notering"})
        stil = (tabell.style
                .map(signalstil, subset=["Signal"])
                .map(indexfarg, subset=["Index"])
                .format({"Index": "{:.0f}", "Vikt": "{:.1%}", "Värde (SEK)": "{:,.0f}", "FCF-yield": "{:.1%}",
                         "P/E": "{:.1f}", "P/E-percentil": "{:.0f}", "Marknadens tillväxt": "{:.1%}",
                         "Din tillväxt": "{:.1%}"}, na_rep="–"))
        st.dataframe(stil, hide_index=True, width="stretch")
        st.caption("Index: 100 = rimligt värderad, under 100 = undervärderad, över 100 = övervärderad. "
                   "Marknadens tillväxt = den årliga FCF-tillväxt som dagens pris förutsätter de närmaste "
                   f"{inst['dcf_ar']} åren. ETF:er och fonder har ingen värdering – deras signal bygger på målvikt.")

        graf = res[res["index"].notna()][["ticker", "index", "signal"]]
        if not graf.empty:
            st.subheader("Värderingsindex per innehav")
            bas = alt.Chart(graf)
            staplar = bas.mark_bar(cornerRadiusEnd=3).encode(
                y=alt.Y("ticker:N", sort="x", title=None),
                x=alt.X("index:Q", title="Index (100 = rimligt värderad)",
                        scale=alt.Scale(domain=[INDEX_MIN, INDEX_MAX])),
                color=alt.Color("signal:N", title="Signal",
                                scale=alt.Scale(domain=list(SIGNALFARGER),
                                                range=["#2E9E5B", "#D64545", "#9E9E9E", "#E0A100", "#CCCCCC"])),
                tooltip=["ticker", alt.Tooltip("index:Q", format=".0f"), "signal"])
            linje = alt.Chart(pd.DataFrame({"x": [100]})).mark_rule(strokeDash=[4, 4], color="#555").encode(x="x:Q")
            st.altair_chart((staplar + linje).properties(height=max(120, 34 * len(graf))),
                            width="stretch")

# ================================================================ Innehav
with flikar[1]:
    st.write("Fyll i dina innehav. Tillväxt och målvikt anges i procent. "
             "Tickers enligt Yahoo Finance: USA t.ex. `MSFT`, Sverige t.ex. `VOLV-B.ST`, "
             "fonder har koder som `0P0000XXXX.ST` (sök på finance.yahoo.com).")
    redigerad = st.data_editor(
        st.session_state.portfolj, num_rows="dynamic", width="stretch", hide_index=True,
        key="redigerare",
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", required=True),
            "typ": st.column_config.SelectboxColumn("Typ", options=TYPER,
                                                    help="Cyklisk = verkstad, råvaror, halvledare m.m. Tomt = automatiskt."),
            "antal": st.column_config.NumberColumn("Antal", min_value=0, format="%.2f"),
            "tillvaxt_pct": st.column_config.NumberColumn(
                "Förv. FCF-tillväxt %/år", format="%.1f %%",
                help=f"Din bedömning av årlig tillväxt i fritt kassaflöde de närmaste {inst['dcf_ar']} åren."),
            "malvikt_pct": st.column_config.NumberColumn("Målvikt %", format="%.1f %%",
                                                         help="Styr signalen för ETF:er och fonder."),
            "manuell_kurs_sek": st.column_config.NumberColumn(
                "Manuell kurs (SEK)", format="%.2f", help="Valfritt, om Yahoo saknar kursen."),
        },
        column_order=KOLUMNER,
    )
    s1, s2 = st.columns([1, 4])
    if s1.button("💾 Spara innehav", type="primary"):
        try:
            lagring.spara_portfolj(redigerad)
            st.session_state.portfolj, st.session_state.ar_exempel = lagring.las_portfolj()
            st.success("Sparat.")
            st.rerun()
        except Exception as e:
            st.error(f"Kunde inte spara: {e}")
    s2.caption(f"Sparas: {lagring.beskrivning}")
    if lagring_varning:
        st.warning("⚠️ Innehaven sparas bara tillfälligt och försvinner när appen startas om. " + lagring_varning)

# ================================================================ Detaljer
with flikar[2]:
    aktier = res[~res["typ"].isin(["ETF", "Fond"])]["ticker"].tolist() if not res.empty else []
    if not aktier:
        st.write("Inga aktier att visa.")
    else:
        val = st.selectbox("Välj aktie", aktier)
        r = res[res["ticker"] == val].iloc[0]
        d = data.get(val, {})
        st.subheader(f"{r['namn'] or val}")
        fmt = lambda v, f: "–" if v is None or pd.isna(v) else f.format(v)
        c = st.columns(5)
        c[0].metric("Signal", r["signal"] or "–")
        c[1].metric("Index", fmt(r["index"], "{:.0f}"))
        c[2].metric("Index FCF", fmt(r["index_fcf"], "{:.0f}"))
        c[3].metric("Index P/E", fmt(r["index_pe"], "{:.0f}"))
        c[4].metric("Index DCF", fmt(r["index_dcf"], "{:.0f}"))

        def status(billig, dyr):
            return "🟢 billigt" if billig else ("🔴 dyrt" if dyr else "⚪ neutralt")

        fy, rf = r["fcf_yield"], r["riskfri"]
        marg = inst["dcf_marginal"] * 100
        rad_fcf = (f"FCF-yield **{fmt(fy, '{:.1%}')}** mot ränta {rf:.1%} och rimlig nivå "
                   f"{rf + inst['fcf_premie']:.1%} → "
                   + status(fy is not None and fy > 0 and fy >= rf + inst["fcf_premie"],
                            fy is not None and 0 < fy <= rf))
        pp = r["pe_pct"]
        rad_pe = (f"P/E **{fmt(r['pe_nu'], '{:.1f}')}** mot median {fmt(r['pe_median'], '{:.1f}')} "
                  f"({fmt(r['hist_ar'], '{:.1f}')} års historik), percentil {fmt(pp, '{:.0f}')} → "
                  + status(pp is not None and not pd.isna(pp) and pp <= inst["p_lag"],
                           pp is not None and not pd.isna(pp) and pp >= inst["p_hog"]))
        idcf = r["index_dcf"]
        rad_dcf = (f"Marknaden prisar in **{fmt(r['implicit_tillvaxt'], '{:.1%}')}** tillväxt/år, "
                   f"du tror på {fmt(r['tillvaxt'], '{:.1%}')} → "
                   + status(idcf is not None and not pd.isna(idcf) and idcf <= 100 - marg,
                            idcf is not None and not pd.isna(idcf) and idcf >= 100 + marg))
        rev, nd = r["eps_rev"], r["nd_ebitda"]
        rad_sparr = (f"Vinstrevidering 90 d: {fmt(rev, '{:+.1%}')}, nettoskuld/EBITDA: {fmt(nd, '{:.1f}')} → "
                     + ("⚠️ spärr" if r["sparr"] else "OK"))
        st.markdown("\n".join(f"- {x}" for x in [rad_fcf, rad_pe, rad_dcf, rad_sparr]))
        if isinstance(r["notering"], str) and r["notering"]:
            st.caption(f"Notering: {r['notering']}")

        g1, g2 = st.columns(2)
        if d.get("pe_serie"):
            pe = pd.DataFrame(d["pe_serie"], columns=["datum", "P/E"])
            pe["datum"] = pd.to_datetime(pe["datum"])
            lin = alt.Chart(pe).mark_line(color="#1F3864").encode(
                x=alt.X("datum:T", title=None), y=alt.Y("P/E:Q", scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("datum:T"), alt.Tooltip("P/E:Q", format=".1f")])
            extra = [lin]
            if pd.notna(r["pe_median"]):
                extra.append(alt.Chart(pd.DataFrame({"y": [r["pe_median"]]}))
                             .mark_rule(strokeDash=[4, 4], color="#888").encode(y="y:Q"))
            if pd.notna(r["pe_nu"]):
                extra.append(alt.Chart(pd.DataFrame({"y": [r["pe_nu"]]}))
                             .mark_rule(color="#D64545").encode(y="y:Q"))
            g1.markdown("**P/E över tid** (röd = idag, streckad = median)")
            g1.altair_chart(alt.layer(*extra).properties(height=260), width="stretch")
        if d.get("fcf_ar"):
            fc = pd.DataFrame(d["fcf_ar"], columns=["år", "FCF (mn)"])
            g2.markdown(f"**Fritt kassaflöde per år** (mn {r['valuta']})")
            g2.altair_chart(alt.Chart(fc).mark_bar(color="#2E6DB4").encode(
                x=alt.X("år:O", title=None), y="FCF (mn):Q",
                tooltip=["år", alt.Tooltip("FCF (mn):Q", format=",.0f")]).properties(height=260),
                width="stretch")

# ================================================================ Inställningar
with flikar[3]:
    with st.form("installningar"):
        st.markdown("**Riskfri ränta per valuta** (10-årig statsobligation, i procent)")
        rantor = pd.DataFrame([{"Valuta": k, "Ränta %": v * 100} for k, v in inst["rantor"].items()])
        rantor_ny = st.data_editor(rantor, num_rows="dynamic", hide_index=True, key="rantor")
        a, b, c = st.columns(3)
        ny = dict(inst)
        ny["rf_standard"] = a.number_input("Ränta för övriga valutor %", value=inst["rf_standard"] * 100, step=0.1) / 100
        ny["erp"] = b.number_input("Aktieriskpremie %", value=inst["erp"] * 100, step=0.5,
                                   help="Avkastningskrav = ränta + aktieriskpremie") / 100
        ny["fcf_premie"] = c.number_input("FCF-premie över räntan %", value=inst["fcf_premie"] * 100, step=0.5) / 100
        ny["p_lag"] = a.number_input("P/E-percentil för billig", value=int(inst["p_lag"]), min_value=0, max_value=100)
        ny["p_hog"] = b.number_input("P/E-percentil för dyr", value=int(inst["p_hog"]), min_value=0, max_value=100)
        ny["hist_ar"] = c.number_input("År P/E-historik", value=int(inst["hist_ar"]), min_value=2, max_value=10,
                                       help="Yahoo har oftast 4–5 års bokslut.")
        ny["dcf_ar"] = a.number_input("År med din tillväxt (DCF)", value=int(inst["dcf_ar"]), min_value=1, max_value=20)
        ny["tillv_term"] = b.number_input("Långsiktig tillväxt därefter %", value=inst["tillv_term"] * 100, step=0.5) / 100
        ny["dcf_marginal"] = c.number_input("Säkerhetsmarginal DCF %", value=inst["dcf_marginal"] * 100, step=5.0) / 100
        ny["rev_grans"] = a.number_input("Spärr: vinstrevidering %", value=inst["rev_grans"] * 100, step=1.0) / 100
        ny["nd_max"] = b.number_input("Spärr: max nettoskuld/EBITDA", value=float(inst["nd_max"]), step=0.5)
        ny["rebal_band"] = c.number_input("ETF/fond: tillåten avvikelse (procentenheter)",
                                          value=inst["rebal_band"] * 100, step=1.0) / 100
        ny["w_fcf"] = a.number_input("Vikt FCF", value=float(inst["w_fcf"]), step=0.5, min_value=0.0)
        ny["w_pe"] = b.number_input("Vikt P/E", value=float(inst["w_pe"]), step=0.5, min_value=0.0)
        ny["w_dcf"] = c.number_input("Vikt DCF", value=float(inst["w_dcf"]), step=0.5, min_value=0.0)
        ny["dra_sbc"] = st.checkbox("Dra av aktieersättningar från FCF (rekommenderas för tech)", value=bool(inst["dra_sbc"]))
        if st.form_submit_button("💾 Spara inställningar", type="primary"):
            ny["rantor"] = {str(rw["Valuta"]).strip().upper(): float(rw["Ränta %"]) / 100
                            for _, rw in rantor_ny.iterrows()
                            if pd.notna(rw["Valuta"]) and str(rw["Valuta"]).strip() and pd.notna(rw["Ränta %"])}
            try:
                lagring.spara_installningar(ny)
                st.session_state.inst = ny
                st.success("Sparat.")
                st.rerun()
            except Exception as e:
                st.error(f"Kunde inte spara: {e}")
    if st.button("Återställ standardinställningar"):
        lagring.spara_installningar(STANDARD_INSTALLNINGAR)
        st.session_state.inst = dict(STANDARD_INSTALLNINGAR)
        st.rerun()

# ================================================================ Om metoden
with flikar[4]:
    st.markdown(f"""
**Tre mått** bedöms som billigt, neutralt eller dyrt för varje aktie:

1. **FCF-yield mot räntan.** Snitt av fritt kassaflöde de senaste tre åren delat med börsvärdet. Billigt om det
   överstiger räntan + {inst['fcf_premie']:.1%}, dyrt om det ligger under räntan. Räknar utan tillväxt, så det är en försiktig golvnivå.
2. **P/E mot egen historik.** Dagens P/E jämfört med bolagets egen historik. Billigt bland de lägsta {inst['p_lag']} %,
   dyrt bland de högsta {100 - inst['p_hog']} %. Cykliska bolag räknas på snittvinsten för att inte ge omvänd signal i toppen av cykeln.
3. **DCF med din tillväxt.** Värdet av kassaflödet om det växer med din förväntan i {inst['dcf_ar']} år och sedan
   {inst['tillv_term']:.1%} per år, diskonterat med ränta + {inst['erp']:.1%}. Billigt om priset ligger minst
   {inst['dcf_marginal']:.0%} under värdet, dyrt om lika mycket över.

**Spärr:** vinstprognoserna har sänkts mer än {abs(inst['rev_grans']):.0%} på 90 dagar, eller nettoskulden är över
{inst['nd_max']:.1f} gånger EBITDA.

**Signal:** *Minska* om minst två mått säger dyrt. *Granska* om spärren slår till. *Öka* om minst två säger billigt.
Annars *Behåll*. Med färre än två tillgängliga mått visas *För lite data*.

**Index:** viktat snitt av delindexen (FCF {inst['w_fcf']}, P/E {inst['w_pe']}, DCF {inst['w_dcf']}), där varje delindex
begränsas till {INDEX_MIN}–{INDEX_MAX}. 100 = rimligt värderad.

**ETF:er och fonder** värderas inte. Signalen bygger på ombalansering mot målvikten (±{inst['rebal_band']:.0%}).

**Begränsningar:** Yahoo Finance är gratis men inofficiellt, och P/E-historiken räcker oftast 4–5 år.
Banker och försäkringsbolag passar dåligt för FCF-måttet. Verktyget är ett beslutsstöd, inte investeringsrådgivning.
""")
