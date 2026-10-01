"""Point d'entrée du jeu « Eddy devine ce que tu montres » (V1).

Câble les organes selon la config CLI et enchaîne les parties. Par défaut :
canal webcam, voix console (sûr, sans audio). Options pour le canal tablette
et la vraie voix VoiceMode.

Exemples :
  python3 -m eddy.run_devine --canal webcam --voix console
  python3 -m eddy.run_devine --canal webcam --voix voicemode \
      --vlm-model qwen2.5vl:7b --chat-model mistral-small3.2:24b \
      --ollama-host http://localhost:11434
"""
from __future__ import annotations

import argparse
from pathlib import Path

from eddy.carnet_parties import CarnetParties
from eddy.cerveau.cerveau_jeu import CerveauJeu
from eddy.session import DevinetteSession
from eddy.vision.vlm import VisionModel
from eddy.voix.console import VoixConsole


class _Chat:
    """Client Mistral texte (Ollama) pour le CerveauJeu."""
    def __init__(self, model: str, host: str) -> None:
        from eddy._ollama import ollama_post
        self.model, self.host, self._post = model, host.rstrip("/"), ollama_post

    def repond(self, messages) -> str:
        out = self._post(f"{self.host}/api/chat",
                         {"model": self.model, "messages": messages, "stream": False})
        return out["message"]["content"].strip()


def _source(canal: str):
    if canal == "webcam":
        from eddy.perception.webcam import SourceWebcam
        return SourceWebcam()
    if canal == "tablette":
        from eddy.perception.tablette import SourceTablette
        # collecte réelle = lecteur stylet côté Pi ; à brancher selon le déploiement.
        raise SystemExit("Canal tablette : brancher `collecte` (lecteur stylet) "
                         "dans run_devine avant usage.")
    raise SystemExit(f"canal inconnu : {canal}")


def _voix(mode: str):
    if mode == "console":
        return VoixConsole()
    if mode == "voicemode":
        raise SystemExit("Voix voicemode : brancher enregistre_audio/joue_audio "
                         "(ex. sounddevice) dans run_devine avant usage.")
    raise SystemExit(f"voix inconnue : {mode}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canal", default="webcam", choices=["webcam", "tablette"])
    ap.add_argument("--voix", default="console", choices=["console", "voicemode"])
    ap.add_argument("--vlm-model", default="qwen2.5vl:7b")
    ap.add_argument("--chat-model", default="mistral-small3.2:24b")
    ap.add_argument("--ollama-host", default="http://localhost:11434")
    ap.add_argument("--carnet", default="eddy_parties.jsonl")
    ap.add_argument("--max-tours", type=int, default=6)
    args = ap.parse_args()

    vision = VisionModel(args.vlm_model, args.ollama_host)
    cerveau = CerveauJeu(_Chat(args.chat_model, args.ollama_host))
    carnet = CarnetParties(Path(args.carnet))

    print("Montre quelque chose à Eddy. (Ctrl-C pour quitter.)")
    try:
        while True:
            input("— Appuie sur Entrée quand c'est prêt — ")
            sess = DevinetteSession(_source(args.canal), vision, cerveau,
                                    _voix(args.voix), carnet, max_tours=args.max_tours)
            issue = sess.jouer_une_partie()
            print(f"[partie terminée : {issue}] {carnet.recap()}")
    except KeyboardInterrupt:
        print("\nÀ bientôt !")


if __name__ == "__main__":
    main()
