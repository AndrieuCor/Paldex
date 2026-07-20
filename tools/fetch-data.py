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

SKILLS et PASSIVES, à l'inverse, sont régénérés intégralement : ils étaient
vides au départ. Toute retouche manuelle y serait écrasée au prochain passage.

Les passifs ici sont les traits innés à l'espèce (Legend, Earth Emperor…),
que seule une trentaine de Pals possède — pas les passifs aléatoires obtenus
à la capture, qui ne dépendent pas de l'espèce.

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

# Traductions officielles du jeu, extraites des fichiers par Palworld-Pal-Editor.
# Le wiki source est anglophone et n'expose aucune version française ; les pages
# traduites de paldb.cc rendent leurs libellés en JavaScript, donc inexploitables
# ici. Les chaînes elles-mêmes appartiennent à Pocketpair, comme les portraits.
I18N = ("https://raw.githubusercontent.com/Guineabear/Palworld-Pal-Editor/HEAD/"
        "src/palworld_pal_editor/assets/data/{}.json")

# Libellés Cargo -> codes courts utilisés par JOBS dans index.html.
JOBS = {
    "Kindling": "ki", "Watering": "wa", "Planting": "pl",
    "Generating Electricity": "el", "Handiwork": "ha", "Gathering": "ga",
    "Lumbering": "lu", "Mining": "mi", "Medicine Production": "me",
    "Cooling": "co", "Transporting": "tr", "Farming": "fa",
    "Oil Extraction": "oi",
}

# Divergences vérifiées en jeu sur un Pal non condensé : le wiki a tort,
# index.html a raison. On les tait pour qu'une nouvelle divergence ressorte
# au lieu de se noyer parmi des questions déjà réglées.
ARBITRATED = {"Cinnamoth", "Herbil", "Kingpaca", "Penking Lux"}

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


def js_str(v):
    """Échappe une chaîne pour l'insérer dans un littéral JavaScript."""
    return str(v).replace("\\", "\\\\").replace('"', '\\"')


def fmt_skills(skills, names):
    lines = []
    for n in names:
        if n not in skills:
            continue
        items = ",".join(
            '["{}","{}",{},{},{}]'.format(js_str(s[0]), s[1], s[2], s[3], s[4])
            for s in skills[n]
        )
        lines.append(f'"{n}":[{items}],')
    return "\n".join(lines).rstrip(",")


def unique_combos(names):
    """Couples de parents donnant un enfant imposé, hors calcul de moyenne.

    Ils vivent dans le paramètre uniqueCombos du modèle {{Breeding}} de
    chaque page, au format « Parent + Parent = Enfant », et non dans Cargo :
    la table ne fait que signaler qu'un Pal en résulte, sans dire de qui.
    """
    combos, param = [], re.compile(r"\|uniqueCombos\s*=(.*?)(?=\n\s*\||\n\}\})", re.S)
    for i in range(0, len(names), 40):
        batch = names[i:i + 40]
        params = urllib.parse.urlencode({
            "action": "query", "titles": "|".join(batch), "prop": "revisions",
            "rvprop": "content", "rvslots": "main", "format": "json",
        })
        req = urllib.request.Request(f"{API}?{params}", headers={"User-Agent": UA})
        data = json.load(urllib.request.urlopen(req, timeout=30))
        for page in data["query"]["pages"].values():
            revs = page.get("revisions")
            if not revs:
                continue
            m = param.search(revs[0]["slots"]["main"]["*"])
            if not m:
                continue
            for row in m.group(1).split(";"):
                pair = re.match(r"\s*(.+?)\s*\+\s*(.+?)\s*=\s*(.+?)\s*$", row)
                if pair:
                    combos.append(tuple(g.strip() for g in pair.groups()))
        print(f"  combos… {min(i + 40, len(names))}/{len(names)}", end="\r")
        time.sleep(0.3)
    print(" " * 40, end="\r")
    return combos


def fetch_i18n(which, lang="fr"):
    """Nom et description traduits, indexés par le libellé anglais.

    C'est l'anglais qui sert de clé : c'est la seule chose que les tables
    Cargo et ces fichiers ont en commun.
    """
    req = urllib.request.Request(I18N.format(which), headers={"User-Agent": UA})
    data = json.load(urllib.request.urlopen(req, timeout=30))
    out = {}
    for entry in data.values():
        i18n = entry.get("I18n") or {}
        en = (i18n.get("en") or {}).get("Name")
        loc = i18n.get(lang) or {}
        if en and loc.get("Name"):
            out[en] = (loc["Name"], (loc.get("Description") or "").strip())
    return out


def clean_wikitext(s):
    """Rend une description lisible hors du wiki.

    Les champs Cargo contiennent du wikitexte et du HTML : icônes de fichier,
    liens internes, sauts de ligne balisés. On garde le texte, on jette le
    balisage — sans quoi l'utilisateur lirait « [[File:Neutral icon.png|… ».
    """
    s = str(s or "")
    s = re.sub(r"<span[^>]*>|</span>", "", s)          # enveloppes d'icônes
    s = re.sub(r"\[\[File:[^\]]*\]\]", "", s)          # images
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)  # [[cible|libellé]]
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)          # [[libellé]]
    s = re.sub(r"<br\s*/?>", " ", s)                   # retours à la ligne
    s = re.sub(r"<[^>]+>", "", s)                      # tout HTML restant
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


def fmt_catalog(rows):
    """Une entrée par ligne : lisible en diff, et le fichier reste éditable."""
    return "\n".join(f"{r}," for r in rows).rstrip(",")


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
    pas = cargo("PalPassiveSkill", "palName,passiveSkillName")
    all_sk = cargo("ActiveSkill",
                   "activeSkillName,element,power,cooldownTime,"
                   "isSkillFruit,isBossSkill,description")
    all_pas = cargo("PassiveSkill", "passiveSkillName,rank,description")
    print(f"  {len(ws)} aptitudes, {len(sk)} liens Pal-compétence, "
          f"{len(pas)} liens Pal-passif")
    print(f"  catalogues : {len(all_sk)} compétences, {len(all_pas)} passifs")

    breed = cargo("PalBreeding",
                  "palName,breedingRank,isUniqueCombo,combiDuplicatePriority")
    print(f"  reproduction : {len(breed)} Pals — lecture des combos uniques…")
    combos = [c for c in unique_combos(names)
              if all(x in known for x in c)]
    print(f"  combos uniques : {len(combos)}")

    tr_sk = fetch_i18n("pal_attacks")
    tr_pas = fetch_i18n("pal_passives")
    print(f"  traductions : {len(tr_sk)} compétences, {len(tr_pas)} passifs")

    def fr_name(en, table):
        """Le français quand il existe, l'anglais sinon — jamais de trou."""
        return table.get(en, (en, ""))[0]

    def fr_desc(en, table, fallback):
        return table.get(en, ("", ""))[1] or fallback

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
            (fr_name(r["activeSkillName"], tr_sk), el, int(r["power"]),
             int(float(r["cooldownTime"])), int(r["level"]))
        )
    for n in skills:
        skills[n].sort(key=lambda s: s[4])

    # --- Catalogue des compétences actives -------------------------------
    # Quels Pals apprennent quoi : c'est le renseignement utile quand on
    # parcourt les compétences plutôt que les Pals.
    learners = {}
    for r in sk:
        if r["palName"] in known:
            learners.setdefault(r["activeSkillName"], []).append(r["palName"])

    askills = []
    for r in sorted(all_sk, key=lambda r: r["activeSkillName"]):
        el = ELEMENTS.get(r.get("element") or "")
        pals = sorted(set(learners.get(r["activeSkillName"], [])))
        en = r["activeSkillName"]
        askills.append(
            '["{}","{}",{},{},{},{},"{}",[{}],"{}"]'.format(
                js_str(fr_name(en, tr_sk)),
                el or "",
                int(r["power"] or 0),
                int(float(r["cooldownTime"] or 0)),
                1 if r.get("isSkillFruit") == "1" else 0,
                1 if r.get("isBossSkill") == "1" else 0,
                js_str(fr_desc(en, tr_sk, clean_wikitext(r.get("description")))),
                ",".join(f'"{js_str(p)}"' for p in pals),
                # Le nom anglais reste accessible : les guides et les vidéos
                # sont anglophones, et la recherche doit y répondre.
                js_str(en),
            )
        )

    # --- Catalogue des passifs -------------------------------------------
    innate = {}
    for r in pas:
        if r["palName"] in known:
            innate.setdefault(r["passiveSkillName"], []).append(r["palName"])

    pskills = []
    for r in sorted(all_pas, key=lambda r: r["passiveSkillName"]):
        rank = (r.get("rank") or "").strip()
        pals = sorted(set(innate.get(r["passiveSkillName"], [])))
        en = r["passiveSkillName"]
        pskills.append(
            '["{}",{},"{}",[{}],"{}"]'.format(
                js_str(fr_name(en, tr_pas)),
                int(rank) if rank.lstrip("-").isdigit() else 0,
                js_str(fr_desc(en, tr_pas, clean_wikitext(r.get("description")))),
                ",".join(f'"{js_str(p)}"' for p in pals),
                js_str(en),
            )
        )

    # --- Reproduction -----------------------------------------------------
    # BREED : nom -> [rang de reproduction, priorité de départage, issu d'un
    # combo unique]. Les Pals issus d'un combo unique sont exclus du calcul
    # par moyenne, sans quoi ils sortiraient d'accouplements ordinaires.
    breeding = []
    for r in sorted(breed, key=lambda r: r["palName"]):
        if r["palName"] not in known:
            continue
        breeding.append('"{}":[{},{},{}]'.format(
            js_str(r["palName"]),
            int(r["breedingRank"] or 0),
            int(r["combiDuplicatePriority"] or 0),
            1 if r.get("isUniqueCombo") == "1" else 0,
        ))
    combo_rows = ['["{}","{}","{}"]'.format(*(js_str(x) for x in c))
                  for c in sorted(set(combos))]

    # --- Bilan -----------------------------------------------------------
    print(f"\nWORK     : {len(existing)} -> {len(work)} / {len(names)} Pals")
    print(f"SKILLS   : {len(skills)} / {len(names)} Pals")
    print(f"ASKILLS  : {len(askills)} compétences au catalogue")
    print(f"PSKILLS  : {len(pskills)} passifs au catalogue "
          f"({len(innate)} liés à une espèce)")
    print(f"BREED    : {len(breeding)} Pals reproductibles, "
          f"{len(combo_rows)} combos uniques")

    no_fr_sk = sorted({r["activeSkillName"] for r in all_sk
                       if r["activeSkillName"] not in tr_sk})
    no_fr_pas = sorted({r["passiveSkillName"] for r in all_pas
                        if r["passiveSkillName"] not in tr_pas})
    if no_fr_sk or no_fr_pas:
        print(f"\nSans traduction, laissés en anglais — "
              f"{len(no_fr_sk)} compétence(s), {len(no_fr_pas)} passif(s) :")
        for n in no_fr_sk + no_fr_pas:
            print(f"  · {n}")
    if skipped:
        print(f"Types de travail non reconnus : {sorted(skipped)}")
    if incomplete:
        print(f"{incomplete} compétence(s) ignorée(s), champs manquants côté wiki")

    absent = [n for n in names if n not in work]
    print(f"\n{len(absent)} Pals restent sans aptitudes (non documentés) :")
    for i in range(0, len(absent), 4):
        print("  " + ", ".join(absent[i:i + 4]))

    settled = [c for c in conflicts if c[0] in ARBITRATED]
    pending = [c for c in conflicts if c[0] not in ARBITRATED]
    if settled:
        print(f"\n{len(settled)} divergence(s) déjà tranchée(s) en jeu, "
              f"index.html conservé : {', '.join(c[0] for c in settled)}")
    if pending:
        print(f"\n{len(pending)} divergence(s) NON arbitrée(s) — l'existant est "
              "conservé, à vérifier en jeu sur un Pal non condensé :")
        for n, a, b in pending:
            print(f"  {n}\n     index.html : {a}\n     wiki       : {b}")

    if args.dry_run:
        print("\n--dry-run : index.html inchangé.")
        return

    # --- Réécriture -------------------------------------------------------
    out = re.sub(r"(const WORK=\{\n).*?(\n\};)",
                 lambda m: m.group(1) + fmt_work(work, names) + m.group(2),
                 src, count=1, flags=re.S)
    out = re.sub(r"const SKILLS=\{.*?\n\};",
                 "const SKILLS={\n" + fmt_skills(skills, names) + "\n};",
                 out, count=1, flags=re.S)
    out = re.sub(r"const ASKILLS=\[.*?\n\];",
                 "const ASKILLS=[\n" + fmt_catalog(askills) + "\n];",
                 out, count=1, flags=re.S)
    out = re.sub(r"const PSKILLS=\[.*?\n\];",
                 "const PSKILLS=[\n" + fmt_catalog(pskills) + "\n];",
                 out, count=1, flags=re.S)
    out = re.sub(r"const BREED=\{.*?\n\};",
                 "const BREED={\n" + fmt_catalog(breeding) + "\n};",
                 out, count=1, flags=re.S)
    out = re.sub(r"const COMBOS=\[.*?\n\];",
                 "const COMBOS=[\n" + fmt_catalog(combo_rows) + "\n];",
                 out, count=1, flags=re.S)
    if out == src:
        sys.exit("Aucune substitution effectuée — le format a changé ?")
    INDEX.write_text(out, encoding="utf-8")
    print(f"\nindex.html réécrit ({len(src)} -> {len(out)} octets)")


if __name__ == "__main__":
    main()
