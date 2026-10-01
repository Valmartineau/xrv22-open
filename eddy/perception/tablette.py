"""Source de perception : la trace 2D du stylet → image PNG.

C'est l'IMAGE rastérisée (pas les coordonnées brutes) qui part au VLM. PIL
importé paresseusement. `collecte` (récupère la liste des traits depuis le
lecteur stylet) et `encode` injectables → testable sans matériel ni PIL.

Canal volontairement traité comme FRAGILE (spec §2) : le VLM reconnaît mal les
gribouillis ; ne pas en faire le socle de la démo.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

canal = "tablette"
Point = Tuple[float, float]
Trait = Sequence[Point]


def rasterise(traits: List[Trait], taille: Tuple[int, int] = (512, 512)) -> bytes:
    from io import BytesIO

    from PIL import Image, ImageDraw  # import paresseux
    img = Image.new("L", taille, color=255)     # fond blanc
    draw = ImageDraw.Draw(img)
    for trait in traits:
        if len(trait) >= 2:
            draw.line([tuple(p) for p in trait], fill=0, width=4)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class SourceTablette:
    canal = "tablette"

    def __init__(self, collecte: Callable[[], List[Trait]],
                 encode: Optional[Callable[[List[Trait]], bytes]] = None) -> None:
        self._collecte = collecte
        self._encode = encode or rasterise

    def capture(self) -> bytes:
        return self._encode(self._collecte())
