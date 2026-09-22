# Zar Agente IA — V27.4

V27.4 separa tres espacios: Zar principal (chat), Centro de control y Zar Studio / Editor multimedia. Además mejora el panel derecho de escritorio y corrige la capa visual de los tooltips `i` del menú izquierdo.


### V22.5 — ajuste visual de marca
- La marca superior izquierda usa únicamente la silueta estilizada de Zar.
- Se elimina el texto «Zar» y «SIEMPRE CONTIGO» de ese bloque.
- No se modifica el layout del chat, compositor, Workspace, Gmail, Calendar ni archivos.
V22.3: corrección de la capa semántica para interceptar WORKSPACE_ACTION y convertirlo en acción pendiente con confirmación explícita. Los marcadores internos ya no se muestran en el chat.

Zar V21 — Archivos inteligentes

# Zar V18 — Orquestador general + interfaz premium + móvil

V18 mantiene el agente semántico y añade:
- estado persistente de tarea (intención, objeto, acción, riesgo y estado);
- política explícita para diferenciar acciones no destructivas de acciones sensibles/irreversibles;
- interfaz de escritorio renovada en negro/marrón/oro;
- login con fondo de Zar, panel translúcido y diseño responsive;
- control de lectura en voz alta con icono 🔊/🔇 en vez de checkbox;
- navegación móvil con barra inferior y paneles;
- identidad visual con retrato dominante de Zar.

Mantén las variables de Railway, OAuth, Gmail, Calendar y el volumen `/data`. No subas secretos a GitHub.


## V19 — chat viewport
- El área de chat es la única zona que hace scroll.
- El compositor (texto + micrófono + sonido + enviar) permanece siempre visible dentro del viewport.
- Los mensajes quedan anclados abajo y crecen hacia arriba como en un chat moderno.
- La misma estructura se adapta a móvil sin scroll global de página.

V21.1: corrección del JavaScript del chat/archivos; el compositor vuelve a responder al clic y Enter envía (Shift+Enter salto de línea).

V21.1: corregido el JavaScript del cliente; vuelven a funcionar los botones del compositor, la voz, el sonido, adjuntar archivos y Enter (Shift+Enter inserta salto de línea). También se corrigieron los handlers del panel de archivos.

V21.3 corrige el fallo de arranque de la ruta Gemini primaria: app/agent.py importa os correctamente para la política de fallback opcional.


## V21.4 - fallback Gemini

Si el modelo Gemini principal alcanza un 429 de cuota, Zar intenta automáticamente `gemini-3.5-flash-lite` con la misma API key/proyecto. Se puede cambiar con `ZAR_GEMINI_FALLBACK_MODEL`. OpenRouter sigue siendo opcional mediante `ZAR_ALLOW_OPENROUTER_FALLBACK=true`.

V25.0 añade un espaciador de chat robusto: cuando hay pocos mensajes, quedan alineados abajo; cuando el historial desborda, se puede recorrer libremente desde arriba hasta abajo. El compositor y sus controles permanecen fuera del flujo del historial.


## V27.1
Editor multimedia inteligente con edición no destructiva, comandos por voz/texto, efectos por tramo de tiempo, biblioteca amplia de transiciones y optimización heurística para vídeo corto. Consulta README_V27_1.md.


## v30.2.0 — Google 2.0
Incluye comprobación en vivo de las APIs de Google y panel de conexiones por servicio, conservando Memoria, Archivos y Deep Research de las versiones anteriores.


## V30.10.15 — Menú lateral como bloque único
- Al cerrar el menú con ☰, desaparece conjuntamente todo el lateral izquierdo, incluido el logo de ZAR.
- El área principal ocupa automáticamente el espacio liberado.
- El lateral vuelve a aparecer completo al abrir el menú.
