#!/usr/bin/env python3
"""
Complète les objets WORK et SKILLS d'index.html depuis les tables Cargo de
palworld.wiki.gg, puis réécrit le fichier.

    python3 tools/fetch-data.py           # écrit index.html
    python3 tools/fetch-data.py --dry-run # montre le bilan sans rien écrire

Les données déjà présentes dans WORK font autorité : elles se disent extraites
des fichiers du jeu, ce qui prime sur un wiki communautaire. Le wiki ne sert
donc qu'à combler les trous, jamais à corriger l'existant. Les divergences
sont signalées en fin de course pour arbitrage manuel.

SKILLS, à l'inverse, est régénéré intégralement : il était vide au départ.
Toute retouche manuelle y serait donc écrasée au prochain passage.

Les Pals que le wiki ne documente pas restent absents de WORK, ce que la page
distingue d'un Pal sans aptitude : voir le compteur « statut inconnu ».

Le wiki ne documente que 12 des 13 métiers — rien pour l'Extraction de
pétrole. Ce métier est donc marqué sans source dans index.html, pour ne pas
faire passer « aucune donnée » pour « aucun Pal ne le fait ».
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"

API = "https://palworld.wiki.gg/api.php"
UA = "Paldex/1.0 (projet perso non commercial; +https://github.com/AndrieuCor/Paldex)"
PAGE = 500

# Libellés Cargo -> codes courts utilisés par JOBS dans index.html.
JOBS = {
    "Kindling": "ki", "Watering": "wa", "Planting": "pl",
    "Generating Electricity": "el", "Handiwork": "ha", "Gathering": "ga",
    "Lumbering": "lu", "Mining": "mi", "Medicine Production": "me",
    "Cooling": "co", "Transporting": "tr", "Farming": "fa",
    "Oil Extraction": "oi",
}

# Éléments Cargo -> clés de l'objet EL.
ELEMENTS = {
    "Neutral": "Neutre", "Fire": "Feu", "Water": "Eau", "Grass": "Herbe",
    "Electric": "Electrique", "Ice": "Glace", "Ground": "Terre",
    "Dark": "Tenebres", "Dragon": "Dragon",
}


def cargo(tables, fields, join=None):
    """Interroge l'API Cargo en paginant jusqu'à épuisement."""
    rows, offset = [], 0
    while True:
        params = {
            "action": "cargoquery", "tables": tables, "fields": fields,
            "limit": str(PAGE), "offset": str(offset), "format": "json",
        }
        if join:
            params["join_on"] = join
        req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": UA})
        data = json.load(urllib.request.urlopen(req, timeout=30))
        if "error" in data:
            sys.exit(f"Erreur Cargo : {data['error'].get('info')}")
        batch = [r["title"] for r in data.get("cargoquery", [])]
        rows += batch
        if len(batch) < PAGE:
            return rows
        offset += PAGE
        time.sleep(0.3)


def parse_existing_work(src):
    """Relit l'objet WORK d'index.html pour ne rien écraser."""
    block = re.search(r"const WORK=\{(.*?)\n\};", src, re.S)
    if not block:
        sys.exit("Objet WORK introuvable dans index.html.")
    out = {}
    for m in re.finditer(r'"([^"]+)":\{([^}]*)\}', block.group(1)):
        out[m.group(1)] = {k: int(v) for k, v in re.findall(r"(\w+):(\d+)", m.group(2))}
    return out


def pal_names(src):
    block = re.search(r"const P = \[(.*?)\n\];", src, re.S)
    return re.findall(r'\["([^"]+)","', block.group(1))


def fmt_work(work, names):
    """Sérialise WORK dans le style du fichier : une entrée compacte par Pal."""
    lines, row = [], ""
    for n in names:
        if n not in work:
            continue
        body = ",".join(f"{k}:{v}" for k, v in sorted(work[n].items()))
        entry = f'"{n}":{{{body}}},'
        if len(row) + len(entry) > 96:
            lines.append(row)
            row = ""
        row += entry
    if row:
        lines.append(row)
    return "\n".join(lines).rstrip(",")


def fmt_skills(skills, names):
    lines = []
    for n in names:
        if n not in skills:
            continue
        items = ",".join(
            '["{}","{}",{},{},{}]'.format(*s) for s in skills[n]
        )
        lines.append(f'"{n}":[{items}],')
    return "\n".join(lines).rstrip(",")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = INDEX.read_text(encoding="utf-8")
    names = pal_names(src)
    known = set(names)
    existing = parse_existing_work(src)
    print(f"{len(names)} Pals dans index.html, {len(existing)} déjà renseignés")

    print("Interrogation des tables Cargo…")
    ws = cargo("PalWorkSuitability", "palName,workType,level")
    pal = cargo("Pal", "palName,isNocturnal")
    sk = cargo(
        "PalActiveSkill,ActiveSkill",
        "PalActiveSkill.palName,PalActiveSkill.activeSkillName,"
        "PalActiveSkill.level,ActiveSkill.element,ActiveSkill.power,"
        "ActiveSkill.cooldownTime",
        join="PalActiveSkill.activeSkillName=ActiveSkill.activeSkillName",
    )
    print(f"  {len(ws)} aptitudes, {len(sk)} compétences, {len(pal)} fiches Pal")

    nocturnal = {r["palName"] for r in pal if r.get("isNocturnal") == "1"}

    # --- Aptitudes de travail -------------------------------------------
    wiki, skipped = {}, set()
    for r in ws:
        if r["palName"] not in known:
            continue
        code = JOBS.get(r["workType"])
        if not code:
            skipped.add(r["workType"])
            continue
        wiki.setdefault(r["palName"], {})[code] = int(r["level"])
    for n in wiki:
        if n in nocturnal:
            wiki[n]["n"] = 1

    conflicts = []
    work = dict(existing)
    for n, v in wiki.items():
        if n in existing:
            if existing[n] != v:
                conflicts.append((n, existing[n], v))
        else:
            work[n] = v

    # --- Compétences actives --------------------------------------------
    skills, incomplete = {}, 0
    for r in sk:
        n = r["palName"]
        if n not in known:
            continue
        el = ELEMENTS.get(r.get("element") or "")
        if not el or not r.get("power") or not r.get("cooldownTime"):
            incomplete += 1
            continue
        skills.setdefault(n, []).append(
            (r["activeSkillName"], el, int(r["power"]),
             int(float(r["cooldownTime"])), int(r["level"]))
        )
    for n in skills:
        skills[n].sort(key=lambda s: s[4])

    # --- Bilan -----------------------------------------------------------
    print(f"\nWORK   : {len(existing)} -> {len(work)} / {len(names)} Pals")
    print(f"SKILLS :   0 -> {len(skills)} / {len(names)} Pals")
    if skipped:
        print(f"Types de travail non reconnus : {sorted(skipped)}")
    if incomplete:
        print(f"{incomplete} compétence(s) ignorée(s), champs manquants côté wiki")

    absent = [n for n in names if n not in work]
    print(f"\n{len(absent)} Pals restent sans aptitudes (non documentés) :")
    for i in range(0, len(absent), 4):
        print("  " + ", ".join(absent[i:i + 4]))

    if conflicts:
        print(f"\n{len(conflicts)} divergence(s) — l'existant est conservé, "
              "à arbitrer à la main :")
        for n, a, b in conflicts:
            print(f"  {n}\n     index.html : {a}\n     wiki       : {b}")

    if args.dry_run:
        print("\n--dry-run : index.html inchangé.")
        return

    # --- Réécriture -------------------------------------------------------
    out = re.sub(r"(const WORK=\{\n).*?(\n\};)",
                 lambda m: m.group(1) + fmt_work(work, names) + m.group(2),
                 src, count=1, flags=re.S)
    out = re.sub(r"const SKILLS=\{.*?\};",
                 "const SKILLS={\n" + fmt_skills(skills, names) + "\n};",
                 out, count=1, flags=re.S)
    if out == src:
        sys.exit("Aucune substitution effectuée — le format a changé ?")
    INDEX.write_text(out, encoding="utf-8")
    print(f"\nindex.html réécrit ({len(src)} -> {len(out)} octets)")


if __name__ == "__main__":
    main()
