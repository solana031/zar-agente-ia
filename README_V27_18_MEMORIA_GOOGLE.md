# ZAR v27.18 — Memoria persistente + Google automático

Esta versión añade una memoria local persistente independiente de Google.

## Memoria
- Guarda el historial completo de chat en el almacenamiento local de Zar.
- Indexa recuerdos explícitos, conversaciones, archivos subidos y artefactos generados.
- Permite buscar esa memoria desde el agente con `zar_memory_search` y desde la sección Memoria.
- Los PDF, TXT, MD, CSV, JSON, DOCX, PPTX y XLSX se indexan para poder preguntar por su contenido sin depender de Google.
- Un curso en PDF se trata como una base de conocimiento recuperable: Zar no reentrena el modelo, sino que recupera los fragmentos relevantes en cada consulta.

## Persistencia en Railway
Para que la memoria, archivos, proyectos y token de Google sobrevivan a nuevos despliegues, el servicio debe tener un **Railway Volume** montado en `/data`.

Variables útiles:
- `ZAR_DATA_DIR=/data`
- `ZAR_AUTO_GOOGLE_CONNECT=1`

## Google
Al abrir `/`, si Google no está conectado, Zar inicia automáticamente OAuth. Si existe un refresh token válido, intenta renovarlo silenciosamente y no pide consentimiento de nuevo.
