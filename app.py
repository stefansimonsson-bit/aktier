# -*- coding: utf-8 -*-
"""Portföljvärdering – Streamlit-app. Starta lokalt med:  streamlit run app.py"""
import json
import time

import altair as alt
import pandas as pd
import streamlit as st

import avanza
import datakalla
from storage import KOLUMNER, Lagring
from valuation import INDEX_MAX, INDEX_MIN, KLASSER, STANDARD_INSTALLNINGAR, vardera_portfolj

st.set_page_config(page_title="Portföljvärdering", page_icon="📊", layout="wide")

SIGNALFARGER = {
    "Öka": ("#C6EFCE", "#006100"),
    "Minska": ("#FFC7CE", "#9C0006"),
    "Behåll": ("#EDEDED", "#3A3A3A"),
    "För lite data": ("#FFFFFF", "#808080"),
}
TYPER = KLASSER + ["ETF", "Fond"]
CACHE_TIMMAR = 24
SIDOR = ["Översikt", "Detaljer", "Innehav", "Avanza-import", "Inställningar", "EODHD-test", "Om metoden"]


# ================================================================ resurser
def las_secrets():
    try:
        return {k: (dict(v) if hasattr(v, "keys") else v) for k, v in dict(st.secrets).items()}
    except Exception:
        return {}


def hamta_lagring(alla):  # inte cachad – nya Secrets ska slå igenom direkt
    if not alla:
        return Lagring(None), "Inga Secrets hittades. Lägg in uppgifterna under Settings → Secrets i Streamlit."
    if "github" not in alla:
        return Lagring(None), (f"Secrets finns ({', '.join(alla)}) men avsnittet [github] saknas.")
    github = dict(alla["github"])
    saknas = [k for k in ("token", "repo") if not str(github.get(k, "")).strip()]
    if saknas:
        return Lagring(None), f"Under [github] saknas: {', '.join(saknas)}."
    return Lagring(github), None


SECRETS = las_secrets()
EODHD_NYCKEL = str((SECRETS.get("eodhd") or {}).get("api_key", "")).strip() if isinstance(SECRETS.get("eodhd"), dict) else ""
lagring, lagring_varning = hamta_lagring(SECRETS)


@st.cache_data(ttl=CACHE_TIMMAR * 3600, show_spinner=False)
def hamta_cachad(ticker, typ, pe_ar, _nyckel):
    return datakalla.hamta(ticker, _nyckel, typ, pe_ar)


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def sok_cachad(isin, namn, typ, _nyckel):
    for fraga in [q for q in (isin, namn) if q]:
        tk, status = datakalla.sok(fraga, _nyckel, isin=isin, typ=typ)
        if tk:
            return tk, status
    return None, "Ej hittad"


if "portfolj" not in st.session_state:
    try:
        st.session_state.portfolj, st.session_state.ar_exempel = lagring.las_portfolj()
        st.session_state.inst = lagring.las_installningar(STANDARD_INSTALLNINGAR)
    except Exception as e:
        st.error(f"Kunde inte läsa sparade uppgifter ({lagring.beskrivning}): {e}")
        st.stop()
inst = st.session_state.inst

with st.sidebar:
    st.markdown("### 📊 Portföljvärdering")
    sida = st.radio("Meny", SIDOR, label_visibility="collapsed")
    st.divider()
    st.caption(f"Data: EODHD{'' if EODHD_NYCKEL else ' – nyckel saknas'}")
    st.caption(f"Sparas: {lagring.beskrivning}")


def kraver_nyckel():
    if not EODHD_NYCKEL:
        st.error("EODHD-nyckeln saknas. Lägg till den under Settings → Secrets i Streamlit:\n\n"
                 "```toml\n[eodhd]\napi_key = \"din-nyckel\"\n```\nSpara och välj Reboot app.")
        return True
    return False


# ================================================================ hjälpfunktioner
def innehav_lista(df):
    rader = []
    for _, r in df.iterrows():
        tk = str(r["ticker"]).strip().upper() if pd.notna(r["ticker"]) else ""
        if not tk:
            continue
        typ = r["typ"] if pd.notna(r["typ"]) and r["typ"] in TYPER else None
        rader.append({
            "ticker": tk, "namn": r["namn"] if pd.notna(r.get("namn")) else None, "typ": typ,
            "antal": None if pd.isna(r["antal"]) else float(r["antal"]),
            "malvikt": None if pd.isna(r["malvikt_pct"]) else float(r["malvikt_pct"]) / 100,
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
            data[h["ticker"]] = hamta_cachad(h["ticker"], h["typ"], int(inst["pe_ar"]), EODHD_NYCKEL)
        except datakalla.EodhdFel as e:
            rad.empty()
            st.error(str(e))
            st.stop()
        except Exception as e:
            data[h["ticker"]] = {"ok": False, "notering": f"Fel vid hämtning: {e}"}
    rad.empty()
    return data


def berakna():
    lista = innehav_lista(st.session_state.portfolj)
    data = hamta_all_data(lista)
    return data, pd.DataFrame(vardera_portfolj(lista, data, inst))


def kr(v):
    return "–" if v is None or pd.isna(v) else f"{v:,.0f} kr".replace(",", " ")


def fmt(v, f):
    return "–" if v is None or (isinstance(v, float) and pd.isna(v)) else f.format(v)


def indexfarg(v):
    if v is None or pd.isna(v):
        return ""
    t = max(-1.0, min(1.0, (v - 100) / 40))
    if t < 0:
        r, g, b = (int(255 + (99 - 255) * -t), int(255 + (190 - 255) * -t), int(255 + (123 - 255) * -t))
    else:
        r, g, b = (int(255 + (248 - 255) * t), int(255 + (105 - 255) * t), int(255 + (107 - 255) * t))
    return f"background-color: rgb({r},{g},{b}); font-weight: 600"


def signalstil(v):
    bg, fg = SIGNALFARGER.get(v, ("", ""))
    return f"background-color: {bg}; color: {fg}; font-weight: 700" if bg else ""


TREND_PIL = {"stigande": "↗ stigande", "fallande": "↘ fallande", "stabil": "→ stabil"}


# ================================================================ Översikt
def sida_oversikt():
    if kraver_nyckel():
        return
    data, res = berakna()
    if st.session_state.get("ar_exempel"):
        st.info("Det här är exempelinnehav. Importera från Avanza eller lägg in dina egna under **Innehav**.")
    if res.empty:
        st.write("Inga innehav ännu.")
        return
    if lagring_varning:
        st.warning("⚠️ Innehaven sparas bara tillfälligt. " + lagring_varning)

    totalt = res["varde_sek"].sum(skipna=True)
    summa = {k: res.loc[res["kategori"] == k, "varde_sek"].sum(skipna=True) for k in ["Aktier", "Fonder", "ETF:er"]}
    k = st.columns(4)
    k[0].metric("Totalt värde", kr(totalt))
    for col, (namn, v) in zip(k[1:], summa.items()):
        col.metric(namn, kr(v), f"{v / totalt:.0%} av totalt" if totalt else None, delta_color="off")
    s = st.columns([1, 1, 3])
    s[0].metric("Öka", int((res["signal"] == "Öka").sum()))
    s[1].metric("Minska", int((res["signal"] == "Minska").sum()))
    with s[2]:
        aldst = min((d.get("hamtad") for d in data.values() if d.get("hamtad")), default="–")
        st.caption(f"Data hämtad {aldst}. Hämtas automatiskt en gång per dygn.")
        if st.button("🔄 Hämta ny data nu"):
            hamta_cachad.clear()
            st.rerun()

    pct = "{:.1%}"
    aktier = res[res["kategori"] == "Aktier"].sort_values("varde_sek", ascending=False, na_position="last")
    st.subheader(f"Aktier · {kr(summa['Aktier'])}")
    if aktier.empty:
        st.caption("Inga aktier.")
    else:
        ar_tillv = aktier["klass"] == "Tillväxt"
        aktier = aktier.assign(trend=aktier["peg_trend_ord"].map(lambda v: TREND_PIL.get(v, "–") if v else "–"),
                               peg=aktier["peg"].where(ar_tillv), pe_pct=aktier["pe_pct"].where(~ar_tillv))
        t = aktier[["ticker", "namn", "klass", "signal", "index", "orsak", "varde_sek", "vikt", "peg", "trend",
                    "fwd_pe", "g_forvantad", "pe_nu", "pe_pct", "rev_90", "riktkurs_uppsida", "valuta", "kurs",
                    "kurs_sek", "notering"]].rename(columns={
            "ticker": "Ticker", "namn": "Namn", "klass": "Klass", "signal": "Signal", "index": "Index",
            "orsak": "Orsak", "varde_sek": "Värde (SEK)", "vikt": "Vikt", "peg": "PEG", "trend": "PEG-trend",
            "fwd_pe": "P/E framåt", "g_forvantad": "Förv. tillväxt", "pe_nu": "P/E", "pe_pct": "P/E-percentil",
            "rev_90": "Estimat 90 d", "riktkurs_uppsida": "Till riktkurs", "valuta": "Valuta", "kurs": "Kurs",
            "kurs_sek": "Kurs (SEK)", "notering": "Notering"})
        st.dataframe(t.style.map(signalstil, subset=["Signal"]).map(indexfarg, subset=["Index"])
                     .format({"Index": "{:.0f}", "Värde (SEK)": "{:,.0f}", "Vikt": pct, "PEG": "{:.2f}",
                              "P/E framåt": "{:.1f}", "Förv. tillväxt": pct, "P/E": "{:.1f}",
                              "P/E-percentil": "{:.0f}", "Estimat 90 d": "{:+.1%}", "Till riktkurs": "{:+.0%}",
                              "Kurs": "{:,.2f}", "Kurs (SEK)": "{:,.2f}"}, na_rep="–"),
                     hide_index=True, width="stretch")
        st.caption("Index: 100 = rimligt värderad. Tillväxtbolag: PEG ÷ "
                   f"{inst['peg_rimlig']}. Mogna och cykliska: P/E ÷ historisk median. "
                   "Estimat 90 d = hur analytikernas vinstestimat ändrats de senaste 90 dagarna.")

    for kat in ["Fonder", "ETF:er"]:
        df = res[res["kategori"] == kat].sort_values("varde_sek", ascending=False, na_position="last")
        st.subheader(f"{kat} · {kr(summa[kat])}")
        if df.empty:
            st.caption(f"Inga {kat.lower()}.")
            continue
        df = df.assign(avvikelse=df["vikt"] - df["malvikt"])
        t = df[["ticker", "namn", "signal", "orsak", "varde_sek", "vikt", "malvikt", "avvikelse", "valuta", "kurs",
                "kurs_sek", "notering"]].rename(columns={
            "ticker": "Ticker", "namn": "Namn", "signal": "Signal", "orsak": "Orsak", "varde_sek": "Värde (SEK)",
            "vikt": "Vikt", "malvikt": "Målvikt", "avvikelse": "Avvikelse", "valuta": "Valuta", "kurs": "Kurs",
            "kurs_sek": "Kurs (SEK)", "notering": "Notering"})
        st.dataframe(t.style.map(signalstil, subset=["Signal"])
                     .format({"Värde (SEK)": "{:,.0f}", "Vikt": pct, "Målvikt": pct, "Avvikelse": "{:+.1%}",
                              "Kurs": "{:,.2f}", "Kurs (SEK)": "{:,.2f}"}, na_rep="–"),
                     hide_index=True, width="stretch")
    st.caption(f"Fonder och ETF:er: signal vid avvikelse från målvikten (±{inst['rebal_band']:.0%}).")

    graf = aktier[aktier["index"].notna()][["ticker", "index", "signal", "klass"]] if not aktier.empty else pd.DataFrame()
    if not graf.empty:
        st.subheader("Värderingsindex per aktie")
        staplar = alt.Chart(graf).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("ticker:N", sort="x", title=None),
            x=alt.X("index:Q", title="Index (100 = rimligt värderad)", scale=alt.Scale(domain=[0, 250], clamp=True)),
            color=alt.Color("signal:N", title="Signal", scale=alt.Scale(
                domain=list(SIGNALFARGER), range=["#2E9E5B", "#D64545", "#9E9E9E", "#CCCCCC"])),
            tooltip=["ticker", "klass", alt.Tooltip("index:Q", format=".0f"), "signal"])
        linje = alt.Chart(pd.DataFrame({"x": [100]})).mark_rule(strokeDash=[4, 4], color="#555").encode(x="x:Q")
        st.altair_chart((staplar + linje).properties(height=max(120, 32 * len(graf))), width="stretch")


# ================================================================ Detaljer
def sida_detaljer():
    if kraver_nyckel():
        return
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
    st.subheader(r["namn"] or val)
    st.caption(f"{d.get('eodhd_ticker', '')} · {d.get('sektor') or ''} {('· ' + d['bransch']) if d.get('bransch') else ''}")
    c = st.columns(4)
    c[0].metric("Signal", r["signal"] or "–")
    c[1].metric("Index", fmt(r["index"], "{:.0f}"))
    c[2].metric("Klass", r["klass"] or "–")
    c[3].metric("Vikt i portföljen", fmt(r["vikt"], "{:.1%}"))
    st.markdown(f"**Orsak:** {r['orsak'] or '–'}  \n**Klass:** {r['klass']} – {r['klass_motivering'] or ''}")

    st.markdown("##### Tillväxt och PEG")
    rek = d.get("rek") or {}
    rek_txt = ", ".join(f"{n} {int(rek[k])}" for k, n in (("StrongBuy", "starkt köp"), ("Buy", "köp"), ("Hold", "behåll"),
                                                          ("Sell", "sälj"), ("StrongSell", "starkt sälj")) if rek.get(k))
    rader = [
        f"**P/E framåt** (nästa 12 mån): {fmt(d.get('fwd_pe'), '{:.1f}')} – vinst per aktie "
        f"{fmt(d.get('eps_ntm'), '{:.2f}')} (i år {fmt(d.get('eps0'), '{:.2f}')}, nästa år {fmt(d.get('eps1'), '{:.2f}')})",
        f"**Förväntad vinsttillväxt:** {fmt(d.get('g_forvantad'), '{:.1%}')} per år ({d.get('g_kalla') or 'saknas'}). "
        f"Analytiker 2 år {fmt(d.get('g_2ar'), '{:.1%}')} · 5 år {fmt(d.get('g_5ar'), '{:.1%}')} · "
        f"historisk vinst {fmt(d.get('g_hist_eps'), '{:.1%}')} · historisk omsättning {fmt(d.get('g_hist_oms'), '{:.1%}')}",
        f"**PEG:** {fmt(d.get('peg'), '{:.2f}')} (för 90 dagar sedan {fmt(d.get('peg_90'), '{:.2f}')}, "
        f"förändring {fmt(d.get('peg_trend'), '{:+.0%}')} → {TREND_PIL.get(r['peg_trend_ord'], '–')}). "
        f"Billig ≤ {inst['peg_billig']}, rimlig {inst['peg_rimlig']}, dyr ≥ {inst['peg_dyr']}. "
        f"EODHD:s egen PEG: {fmt(d.get('peg_eodhd'), '{:.2f}')}",
        f"**Estimat senaste 90 dagarna:** {fmt(d.get('rev_90'), '{:+.1%}')} · senaste 30 dagarna "
        f"{int(d.get('rev_upp_30') or 0)} höjningar och {int(d.get('rev_ned_30') or 0)} sänkningar"
        + (" → ⚠️ stoppar köpsignal" if r["revfilter"] else ""),
        f"**Analytiker:** {fmt(d.get('antal_analytiker'), '{:.0f}')} st · {rek_txt or 'rekommendationer saknas'} · "
        f"riktkurs {fmt(d.get('riktkurs_uppsida'), '{:+.0%}')} från dagens kurs (information, påverkar inte signalen)",
    ]
    st.markdown("\n".join(f"- {x}" for x in rader))

    st.markdown("##### P/E mot egen historik")
    st.markdown(
        f"- **P/E idag:** {fmt(d.get('pe_nu'), '{:.1f}')}"
        + (" (på 10 års snittvinst, cykliskt)" if d.get("cyklisk_berakning") else "")
        + f" · median {fmt(d.get('pe_median'), '{:.1f}')} · percentil {fmt(d.get('pe_pct'), '{:.0f}')} "
        f"({fmt(d.get('hist_ar'), '{:.1f}')} års historik, beräknat med {d.get('pe_metod') or '–'})")
    if d.get("pe_serie"):
        pe = pd.DataFrame(d["pe_serie"], columns=["datum", "P/E"])
        pe["datum"] = pd.to_datetime(pe["datum"])
        lager = [alt.Chart(pe).mark_line(color="#1F3864").encode(
            x=alt.X("datum:T", title=None), y=alt.Y("P/E:Q", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("datum:T"), alt.Tooltip("P/E:Q", format=".1f")])]
        if d.get("pe_median"):
            lager.append(alt.Chart(pd.DataFrame({"y": [d["pe_median"]]}))
                         .mark_rule(strokeDash=[4, 4], color="#888").encode(y="y:Q"))
        if d.get("pe_nu"):
            lager.append(alt.Chart(pd.DataFrame({"y": [d["pe_nu"]]})).mark_rule(color="#D64545").encode(y="y:Q"))
        st.altair_chart(alt.layer(*lager).properties(height=260), width="stretch")
        st.caption("Röd = idag, streckad = median.")
    if d.get("marginaler"):
        st.caption("Rörelsemarginal senaste åren: " + " / ".join(f"{m:.0%}" for m in d["marginaler"]))
    if isinstance(r["notering"], str) and r["notering"]:
        st.caption(f"Notering: {r['notering']}")


# ================================================================ Innehav
def sida_innehav():
    st.write("Redigera dina innehav. **Typ** lämnas tom för att appen ska avgöra tillväxt eller moget själv. "
             "Välj Cyklisk för verkstad, råvaror och liknande, och Investmentbolag för t.ex. Investor. "
             "Tickers: `MSFT`, `ATCO-B.ST`, `PROT.OL` – appen översätter till EODHD:s format.")
    if lagring_varning:
        st.warning("⚠️ Innehaven sparas bara tillfälligt. " + lagring_varning)
    redigerad = st.data_editor(
        st.session_state.portfolj.drop(columns=["tillvaxt_pct"], errors="ignore"), num_rows="dynamic",
        width="stretch", hide_index=True, key="redigerare",
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", required=True),
            "namn": st.column_config.TextColumn("Namn"),
            "typ": st.column_config.SelectboxColumn("Typ", options=TYPER, help="Tomt = automatiskt"),
            "antal": st.column_config.NumberColumn("Antal", min_value=0, format="%.2f"),
            "malvikt_pct": st.column_config.NumberColumn("Målvikt %", format="%.1f %%",
                                                         help="Styr signalen för fonder och ETF:er."),
            "manuell_kurs_sek": st.column_config.NumberColumn("Manuell kurs (SEK)", format="%.2f",
                                                              help="Om EODHD saknar kursen."),
            "isin": st.column_config.TextColumn("ISIN"),
        },
        column_order=[k for k in KOLUMNER if k != "tillvaxt_pct"],
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
    if kraver_nyckel():
        return
    st.write("Exportera dina innehav från Avanza och ladda upp filen här. Samma värdepapper på flera konton slås ihop.")
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
        st.error("Hittade inga innehav i filen.")
        return
    st.markdown(f"**{len(tolkad)} värdepapper** hittades, totalt {kr(tolkad['varde_sek'].sum(min_count=1))}.")

    nyckel = (fil.name, fil.size, tuple(sorted((k, v or "") for k, v in kolumner.items())))
    if st.session_state.get("import_nyckel") != nyckel:
        st.session_state.pop("import_forslag", None)
        st.session_state.import_nyckel = nyckel

    if "import_forslag" not in st.session_state:
        if st.button("🔍 Hitta värdepappren hos EODHD", type="primary"):
            forslag = []
            prog = st.progress(0.0)
            for i, r in tolkad.iterrows():
                prog.progress((i + 1) / len(tolkad), text=f"Söker {r['namn'] or r['isin']}")
                try:
                    tk, status = sok_cachad(r["isin"], r["namn"], r["typ"], EODHD_NYCKEL)
                except datakalla.EodhdFel as e:
                    st.error(str(e))
                    return
                except Exception:
                    tk, status = None, "Ej hittad"
                antal, varde = r["antal"], r["varde_sek"]
                manuell = varde / antal if (varde and antal and status == "Ej hittad") else None
                typ = r["typ"] if r["typ"] in ("ETF", "Fond") else None
                forslag.append({"Importera": True, "Namn": r["namn"], "ISIN": r["isin"], "Antal": antal,
                                "Värde (SEK)": varde, "Typ": typ, "Ticker": tk or r["isin"] or r["namn"],
                                "Status": status, "Manuell kurs (SEK)": manuell})
            prog.empty()
            st.session_state.import_forslag = pd.DataFrame(forslag)
            st.rerun()
        st.dataframe(tolkad.drop(columns=["typ_avanza"]), hide_index=True, width="stretch")
        return

    st.markdown("Kontrollera tickers och typ. För **Ej hittad** fylls en manuell kurs i från Avanzas värde.")
    granskad = st.data_editor(
        st.session_state.import_forslag, hide_index=True, width="stretch", key="import_editor",
        disabled=["Namn", "ISIN", "Antal", "Värde (SEK)", "Status"],
        column_config={
            "Importera": st.column_config.CheckboxColumn(),
            "Typ": st.column_config.SelectboxColumn(options=TYPER, help="Tomt = automatiskt"),
            "Värde (SEK)": st.column_config.NumberColumn(format="%.0f"),
            "Manuell kurs (SEK)": st.column_config.NumberColumn(format="%.2f"),
        })
    satt = st.radio("Hur ska importen göras?", ["Uppdatera mina innehav (behåll typ och målvikt)", "Ersätt alla innehav"])
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
    with st.form("installningar"):
        ny = dict(inst)
        st.markdown("##### Tillväxtbolag – PEG")
        a, b, c = st.columns(3)
        ny["tillvaxt_grans"] = a.number_input("Tillväxtbolag från förväntad vinsttillväxt %",
                                              value=inst["tillvaxt_grans"] * 100, step=1.0) / 100
        ny["peg_rimlig"] = b.number_input("Rimlig PEG (index 100)", value=float(inst["peg_rimlig"]), step=0.1)
        ny["peg_billig"] = c.number_input("Billig PEG (Öka under)", value=float(inst["peg_billig"]), step=0.1)
        ny["peg_dyr"] = a.number_input("Dyr PEG (Minska över)", value=float(inst["peg_dyr"]), step=0.1)
        ny["peg_dyr_stigande"] = b.number_input("Dyr PEG om PEG stiger", value=float(inst["peg_dyr_stigande"]), step=0.1)
        ny["peg_trend_grans"] = c.number_input("PEG-trend: förändring som räknas %", value=inst["peg_trend_grans"] * 100,
                                               step=1.0, help="Förändring i PEG på 90 dagar") / 100
        st.markdown("##### Mogna och cykliska bolag – P/E mot historik")
        a, b, c = st.columns(3)
        ny["pe_lag"] = a.number_input("Percentil för billig (Öka under)", value=int(inst["pe_lag"]), min_value=0, max_value=100)
        ny["pe_hog"] = b.number_input("Percentil för dyr (Minska över)", value=int(inst["pe_hog"]), min_value=0, max_value=100)
        ny["pe_ar"] = c.number_input("År P/E-historik", value=int(inst["pe_ar"]), min_value=3, max_value=30)
        st.markdown("##### Filter och risk")
        a, b, c = st.columns(3)
        ny["rev_grans"] = a.number_input("Stoppa köp om estimaten sänkts mer än % (90 d)",
                                         value=abs(inst["rev_grans"]) * 100, step=1.0) / -100
        ny["max_vikt"] = b.number_input("Maxvikt per aktie % (0 = av)", value=inst["max_vikt"] * 100, step=1.0,
                                        min_value=0.0) / 100
        ny["rebal_band"] = c.number_input("Fond/ETF: tillåten avvikelse (procentenheter)",
                                          value=inst["rebal_band"] * 100, step=1.0) / 100
        if st.form_submit_button("💾 Spara inställningar", type="primary"):
            try:
                lagring.spara_installningar(ny)
                st.session_state.inst = ny
                st.success("Sparat.")
                st.rerun()
            except Exception as e:
                st.error(f"Kunde inte spara: {e}")
    if st.button("Återställ standardvärden"):
        lagring.spara_installningar(dict(STANDARD_INSTALLNINGAR))
        st.session_state.inst = dict(STANDARD_INSTALLNINGAR)
        st.rerun()


# ================================================================ EODHD-test
def sida_test():
    if kraver_nyckel():
        return
    st.write("Visar vad EODHD levererar för en ticker, så att vi kan kontrollera att rätt fält finns.")
    a, b = st.columns([2, 1])
    tk = a.text_input("Ticker", value="MSFT", help="T.ex. MSFT, ATCO-B.ST, PROT.OL eller EODHD-format som MSFT.US")
    typ = b.selectbox("Typ (för beräkningen)", ["(automatiskt)"] + TYPER)
    if st.button("Hämta", type="primary"):
        try:
            with st.spinner("Hämtar…"):
                diag = datakalla.diagnos(tk, EODHD_NYCKEL)
                res = datakalla.hamta(tk, EODHD_NYCKEL, None if typ.startswith("(") else typ, int(inst["pe_ar"]))
        except Exception as e:
            st.error(f"Fel: {e}")
            return
        st.markdown(f"**EODHD-ticker:** `{diag['eodhd_ticker']}` · **Avsnitt:** {', '.join(diag['avsnitt']) or 'inga'}")
        kontroll = {
            "Kurs": bool(diag["dagskurser"]),
            "Månadskurser 10 år": diag["manadskurser_antal"] >= 100,
            "Kvartalsresultat": diag["antal_kvartal"] >= 8,
            "Årsresultat 10 år": diag["antal_ar"] >= 10,
            "Antal aktier över tid": diag["antal_aktieposter"] >= 8,
            "Estimat i år / nästa år": bool(diag["trend"].get("0y")) and bool(diag["trend"].get("+1y")),
            "Estimat för 90 dagar sedan": bool((diag["trend"].get("+1y") or {}).get("epsTrend90daysAgo")),
            "Rekommendationer": bool(diag["analyst_ratings"]),
        }
        st.markdown(" · ".join(f"{'✅' if v else '❌'} {k}" for k, v in kontroll.items()))
        st.markdown("**Beräknat för ramverket**")
        st.json({k: v for k, v in res.items() if k not in ("pe_serie",)}, expanded=True)
        with st.expander("Rådata från EODHD"):
            st.json(diag, expanded=False)
        st.download_button("Ladda ner som JSON", json.dumps({"diagnos": diag, "beraknat": res}, default=str,
                                                            ensure_ascii=False, indent=2),
                           file_name=f"eodhd_{diag['eodhd_ticker']}.json")

    st.divider()
    if st.button("Kontrollera alla innehav"):
        lista = innehav_lista(st.session_state.portfolj)
        rader = []
        prog = st.progress(0.0)
        for i, h in enumerate(lista, 1):
            prog.progress(i / len(lista), text=h["ticker"])
            try:
                d = hamta_cachad(h["ticker"], h["typ"], int(inst["pe_ar"]), EODHD_NYCKEL)
            except Exception as e:
                d = {"ok": False, "notering": str(e)}
            rader.append({"Ticker": h["ticker"], "EODHD": d.get("eodhd_ticker"), "OK": "✅" if d.get("ok") else "❌",
                          "Typ": d.get("typ"), "Valuta": d.get("valuta"), "Kurs": d.get("kurs"),
                          "PEG": d.get("peg"), "P/E": d.get("pe_nu"), "P/E-historik (år)": d.get("hist_ar"),
                          "Estimat 90 d": d.get("rev_90"), "Notering": d.get("notering")})
        prog.empty()
        st.dataframe(pd.DataFrame(rader), hide_index=True, width="stretch")


# ================================================================ Om metoden
def sida_om():
    st.markdown(f"""
**Indelning.** Aktier delas in i *tillväxtbolag* (analytikerna väntar minst {inst['tillvaxt_grans']:.0%} vinsttillväxt
per år, och den historiska omsättningstillväxten är minst hälften av det) och *mogna bolag*. Du kan välja klass själv
under Innehav: *Cyklisk* räknar P/E på 10 års snittvinst, *Investmentbolag* värderas inte.

**Tillväxtbolag – PEG.** PEG = P/E framåt ÷ förväntad vinsttillväxt i procent. P/E framåt bygger på analytikernas
vinst per aktie för de kommande tolv månaderna. Tillväxten är i första hand analytikernas förväntade årliga tillväxt
fram till nästa år (två års estimat), annars femårsprognosen, annars bolagets historiska vinsttillväxt.
*Öka* vid PEG ≤ {inst['peg_billig']} om PEG inte stiger. *Minska* vid PEG ≥ {inst['peg_dyr']}, eller ≥
{inst['peg_dyr_stigande']} om PEG stiger. **PEG-trend** jämför dagens PEG med PEG för 90 dagar sedan, räknat på
kursen och estimaten då. Index = PEG ÷ {inst['peg_rimlig']} × 100.

**Mogna bolag – P/E mot egen historik.** Dagens P/E (rullande tolv månader) jämförs med bolagets egen historik de
senaste {inst['pe_ar']} åren. *Öka* bland de lägsta {inst['pe_lag']} %, *Minska* bland de högsta {100 - inst['pe_hog']} %.
Index = P/E ÷ historisk median × 100.

**Analytikernas estimat.** Styr PEG. Har estimaten sänkts mer än {abs(inst['rev_grans']):.0%} på 90 dagar blir en
köpsignal *Behåll*. Riktkurs och rekommendationer visas som information.

**Maxvikt.** {'Av.' if not inst['max_vikt'] else f"En aktie över {inst['max_vikt']:.0%} av portföljen får *Minska*."}

**Fonder och ETF:er.** Signal vid avvikelse från målvikten (±{inst['rebal_band']:.0%}).

**Data.** EODHD, uppdateras en gång per dygn. Beslutsstöd, inte investeringsrådgivning.
""")


{"Översikt": sida_oversikt, "Detaljer": sida_detaljer, "Innehav": sida_innehav, "Avanza-import": sida_import,
 "Inställningar": sida_installningar, "EODHD-test": sida_test, "Om metoden": sida_om}[sida]()
