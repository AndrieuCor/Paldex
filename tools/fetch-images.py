#!/usr/bin/env python3
"""
Récupère les portraits des Pals depuis l'API MediaWiki de palworld.wiki.gg
et les écrit en WebP dans img/.

Les noms sont lus directement depuis le tableau P d'index.html : la liste
des Pals reste donc à un seul endroit.

    python3 tools/fetch-images.py            # ne retélécharge pas l'existant
    python3 tools/fetch-images.py --force    # tout refaire
    python3 tools/fetch-images.py --size 512 # autre résolution

Les Pals absents du wiki sont signalés en fin de course ; la page retombe
d'elle-même sur le monogramme coloré pour ceux-là.
"""

import argparse
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
OUTDIR = ROOT / "img"

API = "https://palworld.wiki.gg/api.php"
UA = "Paldex/1.0 (projet perso non commercial; +https://github.com/AndrieuCor/Paldex)"

# Le wiki plafonne les requêtes multi-titres à 50.
BATCH = 40
# Pause entre appels réseau. Le wiki est tenu par des bénévoles : on y va doux.
DELAY = 0.3


def pal_names():
    """Extrait les noms du tableau P d'index.html, dans l'ordre du Paldeck."""
    src = INDEX.read_text(encoding="utf-8")
    block = re.search(r"const P = \[(.*?)\n\];", src, re.S)
    if not block:
        sys.exit("Tableau P introuvable dans index.html — le format a changé ?")
    return re.findall(r'\["([^"]+)","', block.group(1))


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30)


def image_urls(names):
    """Nom du Pal -> URL du fichier. Convention du wiki : « <Nom> icon.png »."""
    out = {}
    for i in range(0, len(names), BATCH):
        batch = names[i : i + BATCH]
        params = urllib.parse.urlencode(
            {
                "action": "query",
                "titles": "|".join(f"File:{n} icon.png" for n in batch),
                "prop": "imageinfo",
                "iiprop": "url",
                "format": "json",
            }
        )
        data = json.load(get(f"{API}?{params}"))
        for page in data["query"]["pages"].values():
            if "imageinfo" in page:
                name = page["title"].removeprefix("File:").removesuffix(" icon.png")
                out[name] = page["imageinfo"][0]["url"]
        print(f"  index… {min(i + BATCH, len(names))}/{len(names)}", end="\r")
        time.sleep(DELAY)
    print(" " * 40, end="\r")
    return out


def save_webp(raw, dest, size):
    """Redimensionne et écrit en WebP, en préservant la transparence."""
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    if img.width > size:
        img = img.resize((size, size), Image.LANCZOS)
    img.save(dest, "WEBP", quality=88, method=6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=320, help="côté en px (défaut 320)")
    ap.add_argument("--force", action="store_true", help="retélécharge tout")
    args = ap.parse_args()

    names = pal_names()
    OUTDIR.mkdir(exist_ok=True)
    print(f"{len(names)} Pals dans index.html")

    todo = [n for n in names if args.force or not (OUTDIR / f"{n}.webp").exists()]
    if not todo:
        print("Toutes les images sont déjà là. Rien à faire.")
        return

    print(f"{len(todo)} à récupérer — interrogation du wiki…")
    urls = image_urls(todo)

    ok, failed = 0, []
    for i, name in enumerate(todo, 1):
        url = urls.get(name)
        if not url:
            failed.append(name)
            continue
        try:
            save_webp(get(url).read(), OUTDIR / f"{name}.webp", args.size)
            ok += 1
        except Exception as exc:  # réseau ou image illisible : on note et on continue
            failed.append(f"{name} ({exc})")
        print(f"  {i}/{len(todo)} — {name[:32]:<34}", end="\r")
        time.sleep(DELAY)

    total = sum(f.stat().st_size for f in OUTDIR.glob("*.webp"))
    print(" " * 60, end="\r")
    print(f"\n{ok} images écrites dans img/ — {total / 1e6:.1f} MB au total")
    if failed:
        print(f"\nAbsents du wiki ({len(failed)}) — monogramme utilisé à la place :")
        for f in failed:
            print(f"  · {f}")


if __name__ == "__main__":
    main()
