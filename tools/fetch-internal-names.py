#!/usr/bin/env python3
"""
Construit la correspondance « nom interne du jeu » -> « nom du Paldeck ».

    python3 tools/fetch-internal-names.py

Les sauvegardes stockent les Pals sous leur nom de code interne (SheepBall,
BlueThunderHorse). Sans cette table, un .sav est illisible pour nous.

La source est paldb.cc, dont les pages exposent le nom interne dans l'URL de
l'icône (T_<Interne>_icon_normal.webp). D'autres projets publient une table
équivalente, mais sous GPL : la dériver ici évite d'imposer ce copyleft à un
site publié.

Écrit tools/internal-names.json, que build-savedata.py injecte ensuite dans
index.html.
"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
OUT = Path(__file__).resolve().parent / "internal-names.json"

UA = "Mozilla/5.0 (compatible; Paldex/1.0; projet perso non commercial)"
DELAY = 0.4  # paldb.cc est tenu par des bénévoles

ICON = re.compile(r"cdn\.paldb\.cc/image/Pal/Texture/PalIcon/Normal/T_([A-Za-z0-9_]+)_icon_normal")


def pal_names():
    src = INDEX.read_text(encoding="utf-8")
    block = re.search(r"const P = \[(.*?)\n\];", src, re.S)
    if not block:
        sys.exit("Tableau P introuvable dans index.html.")
    return re.findall(r'\["([^"]+)","', block.group(1))


def internal_name(display):
    """Le nom interne, lu dans l'URL de l'icône de la page du Pal."""
    url = "https://paldb.cc/en/" + urllib.parse.quote(display.replace(" ", "_"))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, str(exc)
    m = ICON.search(html)
    return (m.group(1), None) if m else (None, "icône introuvable")


def main():
    names = pal_names()
    print(f"{len(names)} Pals à résoudre depuis paldb.cc…")

    mapping, failed = {}, []
    for i, n in enumerate(names, 1):
        internal, err = internal_name(n)
        if internal:
            mapping[internal] = n
        else:
            failed.append((n, err))
        print(f"  {i}/{len(names)} — {n[:30]:<32}", end="\r")
        time.sleep(DELAY)

    print(" " * 60, end="\r")
    OUT.write_text(json.dumps(mapping, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8")
    print(f"\n{len(mapping)} correspondances écrites dans {OUT.name}")

    dupes = len(mapping) - len(set(mapping.values()))
    if dupes:
        print(f"Attention : {dupes} noms internes pointent vers un même Pal.")
    if failed:
        print(f"\nNon résolus ({len(failed)}) :")
        for n, err in failed:
            print(f"  · {n} — {err}")


if __name__ == "__main__":
    main()
