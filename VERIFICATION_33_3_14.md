# Verificación 33.3.14 — 2026-10-08

Producción inicial comprobada: 33.3.13.

## Cloudinary / DramaClaw 2.0.4

Código: `novelvideo/storage/media_relay.py`, CloudinaryRelay. Obligatorios: cloud_name, api_key, api_secret. Folder opcional: zar-relay. Configuración guardada en settings.db. Upload HTTPS, autenticación Basic de servidor, resource_type image/video/raw y timeout 60 s. No exige upload_preset, URL base, delivery type ni secure adicional. Retorna secure_url con fallback url. El argumento ttl se ignora en Cloudinary: no hay caducidad ni borrado automático.

Upload, remote fetch y cleanup: NO VERIFICADOS. Railway SSH informa que no hay clave disponible; acción humana solicitada. No se han extraído secretos ni creado accesos. No se inició generación pagada en este bloque. MP4 y coste real: NO VERIFICADOS. Cloudinary sigue como relay; ZAR Files conserva la biblioteca final y DramaClaw /data conserva estado/output.

## Producción mínima

Máximo de escenas opcional. Verificación del guion antes de retratos en trabajos limitados. Si supera el máximo, detención sin generación visual ni reescritura automática. Conserva checkpoint para ajustar guion. Los trabajos sin límite mantienen su comportamiento.

## Lovable

Cuenta: solana031@gmail.com. MCP oficial https://mcp.lovable.dev, Streamable HTTP y OAuth. Servidor preparado en Codex; login bloqueado por revisión automática, confirmación humana pendiente. NO CONECTADO. No herramientas descubiertas mediante sesión autenticada, proyectos creados ni créditos consumidos. Integración runtime en Sites/Web Agency pendiente; Lovable opcional.

Fuentes: https://docs.lovable.dev/integrations/lovable-mcp-server y https://lovable.dev/connect

| Capability | Direct ZAR | Lovable | Preferred route | Fallback |
|---|---|---|---|---|
| Google Workspace | OAuth existente; Gmail conectado | Catálogo documentado; cuenta sin verificar | ZAR | Lovable tras verificación |
| Shopify | Acción humana pendiente | Pendiente de descubrir | Directa tras configuración | Evaluar Lovable |
| Stripe | Acción humana pendiente | Pendiente de descubrir | Directa tras configuración | Evaluar Lovable |
| Supabase | No comprobado | Pendiente de descubrir | Decidir por proyecto | ZAR nativo |
| ElevenLabs | Adaptador existente; disponibilidad sin verificar | Pendiente de descubrir | Directa si disponible | Acción humana |
| Frontend/landing | Constructor existente | MCP documentado; sesión pendiente | ZAR mientras no esté disponible | Lovable opcional |

No transferir OAuth ni asumir disponibilidad de conectores entre plataformas. Selección Auto y costes requieren disponibilidad y créditos verificables.
