"""Source de perception : un instantané de la webcam fixe → octets JPEG.

cv2 importé paresseusement (défauts) ; `ouvre`/`encode` injectables pour les
tests. Réutilise le contexte caméra de l'onglet IA XRV22 (localhost sécurisé).
"""
from __future__ import annotations

from typing import Callable, Optional

canal = "webcam"


def _ouvre_defaut(index: int):
    import cv2  # import paresseux
    return cv2.VideoCapture(index)


def _encode_defaut(frame) -> bytes:
    import cv2
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("échec encodage JPEG de la frame webcam")
    return buf.tobytes()


class SourceWebcam:
    canal = "webcam"

    def __init__(self, index: int = 0,
                 ouvre: Optional[Callable[[int], object]] = None,
                 encode: Optional[Callable[[object], bytes]] = None) -> None:
        self.index = index
        self._ouvre = ouvre or _ouvre_defaut
        self._encode = encode or _encode_defaut

    def capture(self) -> bytes:
        cap = self._ouvre(self.index)
        try:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError("lecture webcam impossible")
            return self._encode(frame)
        finally:
            cap.release()
