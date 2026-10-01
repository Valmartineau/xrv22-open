from eddy.voix.voicemode import VoixVoiceMode

def test_dis_poste_le_texte_au_tts_et_joue_laudio():
    capture = {}
    def fake_post_bytes(url, body):
        capture["tts_url"] = url
        capture["tts_body"] = body
        return b"AUDIO_WAV"
    joue = []
    voix = VoixVoiceMode(
        tts_url="http://localhost:8880/v1/audio/speech",
        stt_url="http://localhost:8000/v1/audio/transcriptions",
        enregistre_audio=lambda: b"MIC", joue_audio=joue.append,
        http_post_bytes=fake_post_bytes, http_post_audio=lambda u, a: {"text": ""},
        voix="ff_siwis")
    voix.dis("Bonjour")
    assert capture["tts_url"].endswith("/v1/audio/speech")
    assert capture["tts_body"]["input"] == "Bonjour"
    assert capture["tts_body"]["voice"] == "ff_siwis"
    assert joue == [b"AUDIO_WAV"]

def test_ecoute_enregistre_et_transcrit():
    capture = {}
    def fake_post_audio(url, audio):
        capture["stt_url"] = url
        capture["audio"] = audio
        return {"text": "  une pomme  "}
    voix = VoixVoiceMode(
        tts_url="http://localhost:8880/v1/audio/speech",
        stt_url="http://localhost:8000/v1/audio/transcriptions",
        enregistre_audio=lambda: b"MIC_BYTES", joue_audio=lambda b: None,
        http_post_bytes=lambda u, b: b"", http_post_audio=fake_post_audio)
    assert voix.ecoute() == "une pomme"          # strip appliqué
    assert capture["audio"] == b"MIC_BYTES"
    assert capture["stt_url"].endswith("/v1/audio/transcriptions")
