"""Lightweight zero-token sub-agent router for ZAR.

This module does not call an LLM. It narrows the tool catalogue sent to a model
when the user's intent clearly belongs to one or more domains. Unknown or highly
mixed requests deliberately fall back to the full catalogue so routing can never
silently remove a capability.
"""
from dataclasses import dataclass
import re

CORE_TOOLS = {
    "get_local_time", "zar_get_context", "zar_set_task_state", "save_memory",
    "zar_memory_search", "file_get", "file_search",
}

DOMAINS = {
    "workspace": {
        "google_workspace_status", "drive_list_recent", "drive_search",
        "docs_create", "docs_append", "sheets_create", "sheets_read",
        "sheets_write", "sheets_add_professional_table", "sheets_build_workbook", "sheets_upgrade_workbook", "slides_create", "slides_build_deck", "docs_build_report", "forms_create", "forms_get",
        "forms_add_question",
    },
    "gmail": {
        "gmail_status", "gmail_recent", "gmail_search", "gmail_get_latest",
        "gmail_get_message", "gmail_get_current_context", "gmail_prepare_email",
        "gmail_save_current_draft",
    },
    "calendar": {"calendar_status", "calendar_upcoming", "calendar_create_confirmed"},
    "contacts": {"contacts_status", "contacts_search", "contacts_get", "contacts_create", "contacts_update"},
    "files": {"file_list", "file_search", "file_get", "file_analyze", "file_update_metadata"},
    "research": {"web_search", "web_image_search", "web_open", "open_url"},
    "maps": {"maps_status", "maps_search", "maps_open_search", "maps_directions"},
    "studio": {"video_get_current_project", "video_edit_project", "video_viral_optimize", "video_transition_catalog", "music_reference_analyze"},
    "media": {"search_youtube", "search_spotify", "open_url"},
}

PATTERNS = {
    "gmail": r"\b(gmail|correo|correos|email|emails|bandeja|remitente|borrador)\b",
    "calendar": r"\b(calendario|calendar|evento|eventos|cita|reunión|reunion|agenda)\b",
    "contacts": r"\b(contacto|contactos|persona|teléfono|telefono|people)\b",
    "workspace": r"\b(drive|documento|docs|hoja|sheets|excel|presentación|presentacion|slides|formulario|forms|workspace)\b",
    "files": r"\b(archivo|archivos|pdf|factura|fichero|adjunto|biblioteca)\b",
    "research": r"\b(internet|web|investiga|investigación|investigacion|fuentes|busca online|buscar online)\b",
    "maps": r"\b(mapa|maps|ruta|dirección|direccion|distancia|cómo llegar|como llegar)\b",
    "studio": r"\b(studio|vídeo|video|audio|música|musica|timeline|transición|transicion|editar vídeo|editar video)\b",
    "media": r"\b(youtube|spotify|canción|cancion|playlist)\b",
}

@dataclass(frozen=True)
class SubAgentRoute:
    name: str
    domains: tuple
    confidence: float
    reason: str


def classify(message: str) -> SubAgentRoute:
    text = (message or "").lower().strip()
    hits = [domain for domain, pattern in PATTERNS.items() if re.search(pattern, text, re.I)]
    # Workspace terms are frequently embedded inside Gmail/contact requests.
    # Keep all explicit domains instead of forcing a winner.
    if not hits:
        return SubAgentRoute("general", tuple(), 0.0, "Sin dominio inequívoco; catálogo completo")
    if len(hits) >= 4:
        return SubAgentRoute("general", tuple(hits), 0.35, "Petición multidominio amplia; catálogo completo")
    if len(hits) == 1:
        return SubAgentRoute(hits[0], tuple(hits), 0.92, f"Dominio explícito: {hits[0]}")
    return SubAgentRoute("multi", tuple(hits), 0.78, "Petición compuesta: " + ", ".join(hits))


def tool_names_for(message: str, all_names=None):
    """Return allowed tool names, or None to preserve the full catalogue."""
    route = classify(message)
    if route.name == "general":
        return None, route
    allowed = set(CORE_TOOLS)
    for domain in route.domains:
        allowed.update(DOMAINS.get(domain, ()))
    if all_names is not None:
        allowed.intersection_update(set(all_names))
    return allowed, route
