# -*- coding: utf-8 -*-
"""Sparar innehav och inställningar.

- Med GitHub-konfiguration (i Streamlit secrets) sparas filerna i en egen gren i ditt privata repo,
  så att de överlever omstarter av appen utan att appen driftsätts om vid varje sparning.
- Utan konfiguration sparas de lokalt i mappen 'sparat/' (bra när du kör appen på din egen dator).
"""
import base64
import io
import json
import os

import pandas as pd
import requests

KOLUMNER = ["ticker", "namn", "typ", "antal", "tillvaxt_pct", "malvikt_pct", "manuell_kurs_sek", "isin"]
PORTFOLJ_FIL = "portfolj.csv"
INSTALLNINGAR_FIL = "installningar.json"
LOKAL_MAPP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sparat")

EXEMPEL = pd.DataFrame([
    {"ticker": "MSFT", "typ": "Aktie", "antal": 10},
    {"ticker": "VOLV-B.ST", "typ": "Cyklisk", "antal": 100},
    {"ticker": "VWCE.DE", "typ": "ETF", "antal": 20, "malvikt_pct": 30.0},
], columns=KOLUMNER)


TEXT = ["ticker", "namn", "typ", "isin"]
TAL = ["antal", "tillvaxt_pct", "malvikt_pct", "manuell_kurs_sek"]


def typa(df):
    """Ger kolumnerna rätt datatyp så att tabellen går att redigera i appen."""
    df = df.reindex(columns=KOLUMNER).copy()
    for k in TEXT:
        df[k] = df[k].astype(object).where(df[k].notna(), None)
        df[k] = df[k].map(lambda v: None if v is None or str(v).strip() in ("", "nan", "None", "<NA>")
                          else str(v).strip()).astype("string")
    for k in TAL:
        df[k] = pd.to_numeric(df[k], errors="coerce").astype(float)
    return df.reset_index(drop=True)


class Lagring:
    def __init__(self, github=None):
        """github: dict med token, repo ('anvandare/repo') och valfritt branch (standard 'data')."""
        self.gh = github if github and github.get("token") and github.get("repo") else None
        if self.gh:
            self.gh = dict(self.gh)
            self.gh.setdefault("branch", "data")
            self._api = f"https://api.github.com/repos/{self.gh['repo']}"
            self._hdr = {"Authorization": f"Bearer {self.gh['token']}",
                         "Accept": "application/vnd.github+json"}

    @property
    def beskrivning(self):
        if self.gh:
            return f"GitHub: {self.gh['repo']} (gren '{self.gh['branch']}')"
        return "Lokalt på servern där appen körs (mappen sparat/)"

    # ---------------------------------------------------------- GitHub
    def _sakerstall_gren(self):
        b = self.gh["branch"]
        r = requests.get(f"{self._api}/branches/{b}", headers=self._hdr, timeout=20)
        if r.status_code == 200:
            return
        repo = requests.get(self._api, headers=self._hdr, timeout=20)
        repo.raise_for_status()
        standard = repo.json()["default_branch"]
        sha = requests.get(f"{self._api}/git/ref/heads/{standard}", headers=self._hdr, timeout=20)
        sha.raise_for_status()
        ny = requests.post(f"{self._api}/git/refs", headers=self._hdr, timeout=20,
                           json={"ref": f"refs/heads/{b}", "sha": sha.json()["object"]["sha"]})
        ny.raise_for_status()

    def _gh_las(self, namn):
        r = requests.get(f"{self._api}/contents/{namn}", headers=self._hdr,
                         params={"ref": self.gh["branch"]}, timeout=20)
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        j = r.json()
        return base64.b64decode(j["content"]).decode("utf-8"), j["sha"]

    def _gh_spara(self, namn, text, meddelande):
        self._sakerstall_gren()
        _, sha = self._gh_las(namn)
        body = {"message": meddelande, "branch": self.gh["branch"],
                "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}
        if sha:
            body["sha"] = sha
        r = requests.put(f"{self._api}/contents/{namn}", headers=self._hdr, json=body, timeout=20)
        r.raise_for_status()

    # ---------------------------------------------------------- generellt
    def _las(self, namn):
        if self.gh:
            return self._gh_las(namn)[0]
        sokvag = os.path.join(LOKAL_MAPP, namn)
        if os.path.exists(sokvag):
            with open(sokvag, encoding="utf-8") as f:
                return f.read()
        return None

    def _spara(self, namn, text, meddelande):
        if self.gh:
            self._gh_spara(namn, text, meddelande)
        else:
            os.makedirs(LOKAL_MAPP, exist_ok=True)
            with open(os.path.join(LOKAL_MAPP, namn), "w", encoding="utf-8") as f:
                f.write(text)

    def las_portfolj(self):
        text = self._las(PORTFOLJ_FIL)
        if not text:
            return typa(EXEMPEL), True
        return typa(pd.read_csv(io.StringIO(text), dtype={k: str for k in TEXT})), False

    def spara_portfolj(self, df):
        df = df.reindex(columns=KOLUMNER).copy()
        df = df[df["ticker"].notna() & (df["ticker"].astype(str).str.strip() != "")]
        df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
        self._spara(PORTFOLJ_FIL, df.to_csv(index=False), "Uppdatera innehav")

    def las_installningar(self, standard, strategi_nycklar=()):
        text = self._las(INSTALLNINGAR_FIL)
        inst = json.loads(json.dumps(standard))  # djupkopia
        if text:
            sparade = json.loads(text)
            if "strategi" not in sparade:
                # Sparat av en äldre version utan strategier – använd standardstrategin
                sparade = {k: v for k, v in sparade.items() if k not in strategi_nycklar}
            inst.update({k: v for k, v in sparade.items() if k in standard})
        return inst

    def spara_installningar(self, inst):
        self._spara(INSTALLNINGAR_FIL, json.dumps(inst, indent=2, ensure_ascii=False),
                    "Uppdatera inställningar")
