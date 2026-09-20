"""ZAR v29 model registry and routing layer.

All model choices live here so the rest of the application can ask for a
capability instead of hard-coding provider/model names. Environment variables
can override individual routes without exposing credentials to the browser.
"""
import os


def _env(name, default):
    value = os.environ.get(name, "").strip()
    return value or default


MODELS = {
    # Main conversational/agent brain.
    "reasoning": _env("ZAR_REASONING_MODEL", _env("ZAR_API_MODEL", "gemini-3.8-flash")),
    # Long-form research route; invoked explicitly by future research workflows.
    "deep_research": _env("ZAR_DEEP_RESEARCH_MODEL", "deep-research-max-preview-04-2026"),
    # Speech routes are intentionally separated from the conversational model.
    "transcribe": _env("ZAR_TRANSCRIBE_MODEL", "gemini-3.5-transcribe"),
    "live": _env("ZAR_LIVE_MODEL", "gemini-3.8-live"),
    "tts": _env("ZAR_TTS_MODEL", "gemini-3.1-flash-tts-preview"),
    # Creative routes.
    "image": _env("ZAR_IMAGE_MODEL", "gemini-3.1-flash-image"),
    "image_pro": _env("ZAR_IMAGE_PRO_MODEL", "gemini-3-pro-image"),
    "video": _env("ZAR_VIDEO_MODEL", "veo-3.1-generate-preview"),
    "video_fast": _env("ZAR_VIDEO_FAST_MODEL", "veo-3.1-fast-generate-preview"),
    "music": _env("ZAR_MUSIC_MODEL", "lyria-3.5"),
    # Multimodal embedding route reserved for Memory 3.0 / RAG.
    "embedding": _env("ZAR_EMBEDDING_MODEL", "gemini-embedding-2"),
}

LABELS = {
    "reasoning": "Cerebro · Gemini 3.8 Flash",
    "deep_research": "Investigación · Deep Research Max",
    "transcribe": "Voz · Gemini 3.5 Transcribe",
    "live": "Voz · Gemini 3.8 Live",
    "tts": "Voz · Gemini 3.1 TTS",
    "image": "Imagen · Nano Banana 2",
    "image_pro": "Imagen Pro · Nano Banana Pro",
    "video": "Vídeo · Veo 3.1",
    "video_fast": "Vídeo rápido · Veo 3.1",
    "music": "Música · Lyria 3.5",
    "embedding": "Memoria · Gemini Embedding 2",
}

DESCRIPTIONS = {
    "reasoning": "Conversación, planificación y uso de herramientas.",
    "deep_research": "Investigación multi-fuente y generación de informes.",
    "transcribe": "Transcripción de audio sin responder a la orden.",
    "live": "Conversación de voz de baja latencia.",
    "tts": "Síntesis de voz para respuestas habladas.",
    "image": "Generación y edición de imágenes.",
    "image_pro": "Generación de imágenes de mayor nivel de control.",
    "video": "Generación de vídeo.",
    "video_fast": "Generación de vídeo rápida.",
    "music": "Generación musical.",
    "embedding": "Representaciones multimodales para memoria y RAG.",
}


def model_for(capability: str) -> str:
    """Return the configured model for a ZAR capability."""
    return MODELS.get(capability, MODELS["reasoning"])


def catalog():
    """Return a UI-safe model catalog; never include API keys."""
    return [
        {
            "capability": capability,
            "label": LABELS.get(capability, capability),
            "model": model,
            "description": DESCRIPTIONS.get(capability, ""),
        }
        for capability, model in MODELS.items()
    ]
