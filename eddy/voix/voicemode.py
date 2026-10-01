"""Vraie voix : TTS Kokoro (8880) + STT Whisper, endpoints HTTP locaux.

Même interface que VoixConsole (dis / ecoute). L'I/O audio matérielle
(micro/HP) est injectée (enregistre_audio / joue_audio) ; les POST HTTP sont
injectables pour les tests. 100 % local (VoiceMode sur la même machine que
MiCHEL — topologie voix option a, spec §5).
"""
from __future__ import annotations

import json
from typing import Callable, Optional
from urllib import request as _urlreq


def _post_bytes(url: str, body: dict) -> bytes:
    """POST JSON → réponse binaire (audio TTS)."""
    data = json.dumps(body).encode("utf-8")
    req = _urlreq.Request(url, data=data, headers={"Content-Type": "application/json"})
    with _urlreq.urlopen(req) as resp:  # noqa: S310
        return resp.read()


def _post_audio(url: str, audio: bytes) -> dict:
    """POST audio brut → JSON de transcription (STT)."""
    req = _urlreq.Request(url, data=audio, headers={"Content-Type": "audio/wav"})
    with _urlreq.urlopen(req) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


class VoixVoiceMode:
    def __init__(self, tts_url: str, stt_url: str,
                 enregistre_audio: Callable[[], bytes],
                 joue_audio: Callable[[bytes], None],
                 voix: str = "ff_siwis",
                 http_post_bytes: Optional[Callable[[str, dict], bytes]] = None,
                 http_post_audio: Optional[Callable[[str, bytes], dict]] = None) -> None:
        self.tts_url = tts_url
        self.stt_url = stt_url
        self._enregistre = enregistre_audio
        self._joue = joue_audio
        self.voix = voix
        self._post_bytes = http_post_bytes or _post_bytes
        self._post_audio = http_post_audio or _post_audio

    def dis(self, texte: str) -> None:
        audio = self._post_bytes(self.tts_url,
                                 {"input": texte, "voice": self.voix,
                                  "response_format": "wav"})
        self._joue(audio)

    def ecoute(self) -> str:
        audio = self._enregistre()
        out = self._post_audio(self.stt_url, audio)
        return out.get("text", "").strip()
