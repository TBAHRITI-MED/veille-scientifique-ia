"""Télécharge les classements SJR (revues) et CORE (conférences) dans data/.

Usage :
    python -m quality.update_rankings
    python -m quality.update_rankings --core-edition CORE2023

Si un site refuse le téléchargement automatique, télécharge le fichier à la main
(liens affichés en cas d'échec) et importe-le depuis l'onglet « Sources & classements ».
"""

from __future__ import annotations

import argparse

import requests

import settings
from quality.rankings import parse_core, parse_sjr

SJR_URL = "https://www.scimagojr.com/journalrank.php?out=xls"
CORE_URL = (
    "https://portal.core.edu.au/conf-ranks/"
    "?search=&by=all&source={edition}&sort=arank&page=1&do=Export"
)
DEFAULT_CORE_EDITION = "CORE2023"
BROWSER_UA = "Mozilla/5.0 (veille-scientifique; usage personnel)"


def _download(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=60)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def save_sjr(text: str) -> int:
    """Valide puis enregistre un export SJR. Renvoie le nombre de revues classées."""
    _, count = parse_sjr(text)
    if count == 0:
        raise ValueError("Aucune revue classée trouvée dans le fichier SJR.")
    settings.DATA_DIR.mkdir(exist_ok=True)
    settings.SJR_FILE.write_text(text, encoding="utf-8")
    return count


def save_core(text: str) -> int:
    """Valide puis enregistre un export CORE. Renvoie le nombre de conférences classées."""
    acronyms, titles = parse_core(text)
    count = max(len(acronyms), len(titles))
    if count == 0:
        raise ValueError("Aucune conférence classée trouvée dans le fichier CORE.")
    settings.DATA_DIR.mkdir(exist_ok=True)
    settings.CORE_FILE.write_text(text, encoding="utf-8")
    return count


def update_sjr() -> int:
    return save_sjr(_download(SJR_URL))


def update_core(edition: str = DEFAULT_CORE_EDITION) -> int:
    return save_core(_download(CORE_URL.format(edition=edition)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core-edition", default=DEFAULT_CORE_EDITION)
    args = parser.parse_args()

    for label, action, url in (
        ("SJR (revues)", update_sjr, SJR_URL),
        ("CORE (conférences)", lambda: update_core(args.core_edition),
         CORE_URL.format(edition=args.core_edition)),
    ):
        try:
            print(f"{label} : {action()} entrées classées.")
        except Exception as exc:
            print(f"{label} : échec ({exc}).\n  Télécharge-le à la main : {url}")


if __name__ == "__main__":
    main()
