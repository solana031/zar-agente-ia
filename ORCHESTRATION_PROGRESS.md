# Orquestación empresarial: bloque inicial local

Rama de trabajo: `zar-current`. Versión conservada: `33.3.0`.
Sin commit, push ni despliegue. No se completa todavía todo el encargo.

## Implementado y validado

- `business_orchestration` usa el mismo `users/<scope>/holdings/state.json`.
  No crea una segunda base de datos. Migración aditiva de estado.
- Registro de RevenueAgent, OptimizationAgent y AccountManagerAgent con
  ejecutores locales permitidos, tareas, dependencias, resultados, errores,
  heartbeat, permisos y logs. Asignación idempotente con request_id.
- Modos OFF/SHADOW/SUPERVISED/ACTIVE en el worker de Holdings existente.
  Un ejecutor local por ciclo. SHADOW no llama a los handlers externos de empresas;
  conserva las tareas pendientes y registra el plan simulado.
- Wallet contable por moneda: aportaciones declaradas, ingresos, costes,
  pendientes, reservas, disponible y beneficio. Banco NO CONECTADO.
  Reservas aprobadas no equivalen a pagos, ni se convierten en gastos.
- Propuestas económicas con proveedor/precio/impuestos/total, confirmación
  explícita del importe y control de saldo. Cancelación libera reserva.
  No hay ejecutor de checkout, transferencia o pago en esta consola.
- API con CSRF por sesión, aislamiento por scope y controles de STOP GLOBAL.
- Persistencia atómica y bloqueo del archivo entre procesos/threads.
  Historial financiero sin recorte. Archivo corrupto genera error y se conserva.
- Controles en la ventana actual de Orquestación: wallet, agentes, tareas,
  aprobaciones, cuentas, nodos, ledger y actividad. Conserva formularios editados.
- Inventario de cuentas: solo metadatos y referencias a variables secretas.
  CAPTCHA/SMS/KYC/términos/verificación humana producen AWAITING_HUMAN.
  No implementa aún creación de cuentas, login, recuperación ni OAuth nuevo.
- Inventario de configuración de servicios con variables faltantes y enlaces.
  Presencia de configuración nunca implica LISTO. No se verificaron servicios
  externos ni credenciales de producción. No se modificaron secretos.
- Reinversión autónoma de dominios genera tarea AWAITING_APPROVAL.
  La compra antigua mediante confirmed=true queda bloqueada hasta disponer
  de checkout verificable y aprobación vinculada a wallet; no se envía dinero.

## Pruebas

`python -m unittest discover -s tests -p test_business_orchestration.py -v`:
12 pruebas de backend, incluyendo dos procesos concurrentes, CSRF, reservas,
aislamiento, corrupción, permisos, SHADOW y dominio sin pago. APIs externas mock.

`node tests/business-orchestration-ui.cjs`: controles DOM en Edge headless,
red simulada, encabezado CSRF y preservación de formularios.

`node tests/orchestration-layout-adaptive.cjs`: geometría existente conservada.

Sintaxis Python/JS y diff de los archivos afectados comprobados.
La suite pytest existente no se ejecutó: pytest no está instalado y su
instalación no estuvo disponible. No se verificaron Railway ni servicios reales.

## Limitaciones y siguiente bloque

La base implementada NO constituye la automatización completa solicitada.
Los agentes locales no se presentan como generadores de vídeos/webs ni vendedores.
El inventario de nodos no sustituye las comprobaciones de salud existentes.
Las tarjetas antiguas de Holdings y el mapa descriptivo todavía necesitan
unificación con el registro persistente; sus métricas históricas agregadas
requieren separación por moneda y fuente. El nuevo panel sí separa monedas.

Siguiente bloque P0: vincular tareas existentes de las empresas al registro
central, registrar atribución económica/agente/referencia/metadata, proteger
todas las rutas económicas antiguas, añadir detalle de negocio y aprobaciones
de proveedor con precio final, caducidad, ejecución idempotente y reconciliación.
Mantener bloqueados los pagos hasta completar ese contrato.

P1: completar el flujo de importación de sitios (dominio/código/ZIP), SEO y
métricas AdSense con periodo/fecha de Google, y enlazar las etapas y controles
de DramaClaw ya existentes con los agentes. Reutilizar los módulos actuales.

Configuración a comprobar en el servidor real, sin copiar secretos al chat:

- Jev: JEV_API_KEY o TYPESAFE_API_KEY, desde TypeSafe.
- DramaClaw: DRAMACLAW_API_URL y modelos del servicio, token si exige acceso.
- AdSense: GOOGLE_ADSENSE_ACCESS_TOKEN, GOOGLE_ADSENSE_ACCOUNT y publisher;
  OAuth de Google y cuenta/sitio aprobados en AdSense.
- Vercel: VERCEL_TOKEN; dominio: identidad de titular y checkout verificable.
- ElevenLabs: ELEVENLABS_API_KEY y ELEVENLABS_VOICE_ID, desde ElevenLabs.
- Shopify: SHOPIFY_SHOP_DOMAIN y SHOPIFY_ADMIN_ACCESS_TOKEN.
- Maps: ZAR_MAPS_API_KEY, desde Google Cloud.
- TikTok/Instagram: tokens y permisos del proveedor; Instagram requiere ID.
- Mail/YouTube: identidad empresarial y OAuth apropiado; usar OAuth existente
  cuando corresponda. Telefonía requiere proveedor y número, sin inventarlos.

P2/P3 pendientes: CRM/pipeline comercial completo, investigación/demos
personalizadas, límites de outreach, negociación, cobro reconciliado,
DomainScout y compra aprobada. JEV routing avanzado también pendiente.

No modificar Kilo/Ollama/Coding Agent, Stonks, secretos ni Railway.
No publicar ni cambiar versión hasta completar el bloque y fijar versión objetivo.


## Sesión P0 JEV / DramaClaw / Sites + AdSense — 33.3.1 local

Este bloque conserva el control plane anterior. La versión local pasa de 33.3.0
 a 33.3.1 en los tres archivos y etiqueta visible. Sin commit, push ni deploy.
Los cambios locales de Pablo en AGENTS.md, .kilo y kilo.json no se han editado.
No se ha intervenido en Coding Agent ni en la lógica Stonks.

### JEV

Propuestas tipadas, política local conservadora, consulta TypeSafe opcional con
confirmación de cuota, decisiones APPROVE/REJECT/DEFER/ESCALATE persistentes
con input/output, riesgo, coste/ingreso/beneficio null si desconocidos, tarea,
wallet y estado posterior. La respuesta de un modelo no puede autorizar pagos.
Automaton consulta JEV antes de ejecutar las herramientas locales y Media antes
de iniciar generación autorizada. UI de formulario, filtros y detalle.
La política local no se presenta como conexión TypeSafe verificada. Routing de
proveedor es recomendación; no hay selección automática de proveedores caros.

### Media / DramaClaw

Proyecto y preferencias persistidos, estados y trazabilidad de trece capacidades
sobre el worker/checkpoints existentes. Historia íntegra y preferencias llegan
al proveedor. Inspección real de personajes/guion/escenas, storyboard con assets,
MP4, revisión de guion, regeneración de escena y recomposición sin subtítulos.
Formatos incompatibles con el backend se bloquean, sin sustitución silenciosa.
Voces ElevenLabs verificables, selección y generación explícita de assets con
muestra, intención persistente anti-duplicación y fallback F5 existente.

Limitación: los assets ElevenLabs por personaje requieren importación/revisión
en el editor DramaClaw; no existe contrato verificado que los monte de forma
nativa. ZAR bloquea READY mientras falta esa revisión. Duración e idioma son
preferencias objetivo; el idioma del SRT no traduce por sí mismo su contenido.

SRT sincronizado del proveedor, edición, tamaño/posición/estilos, exportación y
render local FFmpeg/libass. Fuente ya subtitulada exige recomposición limpia
confirmada antes de renderizar; no se superponen textos. Revisiones anteriores,
renders, publicaciones e intenciones se conservan. Publicar requiere revisión y
confirmación individual; YouTube privado mediante OAuth existente, TikTok y
Reels usan los conectores existentes y seguimiento de IDs sin repetir envíos
ambiguos. URL/métricas no disponibles permanecen null. No se publicó nada.
Coste estimado/real/moneda/uso monetario permanecen null sin dato del proveedor;
los assets de voz registran cantidad real de caracteres, sin inventar créditos.

### Sites / AdSense / Wallet / Automaton

SiteProject admite dominio inventariado, HTML, archivos estáticos, ZIP o idea.
Validación de rutas/secretos/tamaño y preview aislado CSP sandbox sin autoridad
sobre ZAR. Persistencia sobre registry existente, estados y análisis HTML/SEO.
Construcción local de ideas mediante fuentes públicas sin proveedor de pago;
contenido y política de privacidad requieren revisión editorial antes de usar.
Idioma/país contextualizan búsqueda; no se afirma traducción editorial completa.
El dominio no se descarga arbitrariamente; importar HTML para análisis local.
Publicación externa conserva el conector existente, no se despliega en esta sesión.
Agentes Sites registrados sin duplicar RevenueAgent/OptimizationAgent.
Automaton puede construir, analizar y revisar proyectos/rendimiento con métricas
persistidas; sin métricas por sitio, rendimiento desconocido. ContentAgent prepara
recomendaciones locales; generación editorial con modelos queda pendiente de
un contrato de coste y aprobación. No se presenta workflow_status como generación.

AdSenseAdapter usa Google AdSense API v2, cuenta/sitios/informes/pagos, periodo,
totales/ratios, advertencias y hora de consulta ZAR. No llama tiempo real al informe
ni inventa hora interna de actualización de Google. Filtro por sitio evita
atribuir métricas de toda la cuenta a un proyecto individual. ESTIMATED y
FINALIZED no crean saldo; RECEIVED requiere confirmación y referencia bancaria,
ledger con referencia Google idempotente. Es confirmación manual del cobro,
no reconciliación bancaria automática. El token OAuth se configura en secretos
y puede caducar; renovación OAuth automática de AdSense queda pendiente.

Nodos: LISTO requiere respuesta real, alcance de verificación y configuración
coincidente; caduca a los diez minutos. La presencia de variables no es prueba.
Ninguna prueba de esta sesión verificó cuentas reales; no declarar LISTO por mocks.

### Validación

- 27 unittests offline: control plane y workflows (incluye persistencia JEV,
  Sites/importaciones/SEO, AdSense/ledger, Media/voz/subtítulos/publicación).
- 15 pruebas existentes del cliente DramaClaw, APIs simuladas: PASS.
- UI workflows: escritorio 1920 y móvil 390, CSRF, desconocidos, formularios,
  detalle/preferencias y errores JS: PASS.
- UI del control plane y layout adaptativo: PASS.
- Render real FFmpeg/libass con MP4 sintético local: PASS, fuente conservada.
- Sintaxis Python y JS, tres VERSION y diff check: PASS.
- Stonks: mock de recursos estáticos actualizado para cargar los nuevos scripts
  reales (antes devolvía JSON y provocaba SyntaxError); aserciones conservadas.
- No se ejecutó toda la suite pytest: pytest no disponible en este entorno.
- No se probaron cuentas reales, generación pagada, publicación ni Railway.

### Configuración y siguiente bloque

Configurar en secretos/env del servidor, nunca en fixtures o UI:
JEV_API_KEY o TYPESAFE_API_KEY (https://typesafe.ai);
DRAMACLAW_API_URL, DRAMACLAW_API_TOKEN si requerido y DRAMACLAW_WEB_URL desde
instancia DramaClaw; ElevenLabs ELEVENLABS_API_KEY y voz elegida desde
https://elevenlabs.io; F5_TTS_API_URL solo si se dispone del servicio local;
GOOGLE_ADSENSE_ACCESS_TOKEN con adsense.readonly desde OAuth de Google Cloud,
GOOGLE_ADSENSE_ACCOUNT y GOOGLE_ADSENSE_PUBLISHER_ID desde https://adsense.google.com.
YouTube usa su flujo OAuth existente; TikTok TIKTOK_ACCESS_TOKEN y Reels
INSTAGRAM_ACCESS_TOKEN/INSTAGRAM_IG_USER_ID con permisos de publicación.
FFmpeg/imageio-ffmpeg con libass debe existir también en el servidor destino.

Contratos consultados: https://developers.google.com/adsense/management/reference/rest/v2/accounts.payments
https://developers.google.com/adsense/management/reference/rest/v2/accounts.reports/generate
https://developers.google.com/adsense/management/reference/rest/v2/ReportResult
https://elevenlabs.io/docs/api-reference/voices/search
https://elevenlabs.io/docs/api-reference/text-to-speech/convert
https://github.com/dramaclaw/dramaclaw/blob/main/.hermes/skills/dramaclaw/references/api-reference.md

Siguiente bloque: verificación de conexiones configuradas mediante lecturas,
contrato/importación automática de voces por personaje, uso/costes reales del
proveedor, renovación OAuth AdSense y generación editorial aprobada. No avanzar
Web Agency hasta nueva instrucción. No hacer push ni deploy.


## Bloque Commerce + Agency/CRM — 33.3.2 local

La nueva petición autoriza ampliar Web Agency y reemplaza la restricción del
bloque anterior sobre esa área. Se conserva todo el desarrollo previo. Rama
zar-current; versión local 33.3.2 en VERSION, VERSION.txt, app/VERSION.txt y UI.
Sin commit, push ni deploy. No se han modificado los archivos locales de Pablo
sobre Kilo/Ollama/Coding Agent ni la lógica de trading de Stonks.

### Commerce core / P0

Commerce vive en commerce_workspace dentro del Holdings state por usuario,
con el mismo bloqueo transaccional. No se añade una base de datos paralela.
Se inicializan once nichos editables con los subnichos/restricciones solicitados,
una única vez; se pueden editar y añadir nichos personalizados.
Investigación mediante fuentes públicas: demanda, tendencia, competencia,
estacionalidad y ticket permanecen NO DISPONIBLE cuando no hay datos medidos.
No se convierten resultados de búsqueda ni números arbitrarios en demanda real.

Productos y candidatos persistentes: proveedor/SKU, modelo de negocio, origen,
entregas, plazos, MOQ, devolución, reputación, stock, imágenes, descripción,
variantes, dimensiones/peso, dropshipping, branding y riesgos cuando constan.
Desconocidos permanecen null/ausentes. La compatibilidad de envío directo debe
confirmarse para proveedor Y producto; WHOLESALE no implica dropshipping.
La aprobación de candidatos requiere costes completos y revisión humana; los
productos de riesgo detectados requieren evidencia adicional de revisión.

Pricing usa Decimal y nueve costes por unidad explícitos. Costes vacíos no son
cero. Margen bruto/neto estimado, beneficio, CAC máximo, ROAS de equilibrio,
precio mínimo/objetivo/premium y supuestos visibles. Cero es supuesto explícito.
No hay asesoría fiscal ni modelo oculto de comisiones por porcentaje.
Scoring de quince factores y pesos que suman 100, aptitud 0–1 y clasificación
REAL/ESTIMADA con fuente. No publica score total si la cobertura es incompleta;
expone puntos conocidos, cobertura y desglose, sin fingir precisión de demanda.

SupplierAdapter y estructuras SupplierProduct/SupplierQuote/SupplierOrder:
bridge privado configurable con prefijos de secretos diferentes por proveedor.
No se afirma conexión con marketplaces concretos. Catálogo, quote, compra y
tracking requieren endpoints y contrato JSON reales. Sin API, estado operativo
MANUAL_ACTION_REQUIRED. La UI muestra modelo y alcance de la verificación.
Conexión de catálogo no demuestra que compras/fulfillment funcionen.

Quotes vinculados a línea Shopify/SKU/cantidad exactos, país, moneda, impuestos,
shipping, fees, total y caducidad, además de fingerprint de configuración.
Preparación de compra consulta JEV y vincula la aprobación/reserva existente de
Wallet a quote/pedido. Ejecución requiere modo permitido, agentes activos,
reserva vigente, configuración intacta, dirección revisada y confirmación del
total. La intención/idempotency key se persiste antes de llamar al proveedor.
Solo recibo de cargo y total reconciliados crean coste real y liquidan reserva.
Fallo ambiguo no reenvía. No se puede cancelar la reserva de una orden enviada.
Reconciliación consultando intención existente: NOT_FOUND conserva reserva;
solo CANCELLED sin cargo, confirmado por proveedor, libera fondos. No se simula
que una reserva contable autorice por sí sola un pago.

Tracking real y fulfillment Shopify explícito, solo línea/unidades del proveedor
confirmadas; sin notificación automática al consumidor. Pedidos grandes con
paginación interna incompleta se bloquean para revisión, sin omitir unidades.
Devoluciones y soporte tienen registros; fraude, amenazas, chargebacks, asuntos
legales y excepciones escalan. Respuestas son borradores, no se envían.

### Shopify / Wallet / Automaton / P1

ShopifyAdapter usa Admin GraphQL 2026-10 por defecto (configurable), hostname
myshopify.com validado, errores sanitizados, sin redirects ni reintentos de writes
ambiguos. Verifica tienda/scopes y lee catálogo/variantes/inventario/pedidos/
fulfillment orders; clientes disponibles mediante consulta separada con permisos.
Paginación externa limitada, falla explícitamente si se excede. Consultas anidadas
acotadas para controlar complejidad. Paginación interna indica datos incompletos.

Listings guardan preview original, bullets, SEO, tags, colección, precio/compare-at,
variantes/imágenes autorizadas/alt, shipping y FAQ. Crea DRAFT remoto solo tras
confirmación; soporta variantes con sku/price/options explícitos e imágenes HTTPS.
Colecciones remotas requieren gid real, no nombre inventado. Moneda debe coincidir
con la tienda. Publicación exige confirmación del canal, DRAFT remoto y guardrails;
pausa remota explícita. No se ha creado/publicado ningún producto real aquí.

La sincronización antigua de Shopify se enlaza al nuevo core y deja de sumar el
total de pedidos PAID como dinero cobrado. No se migran/borran asientos históricos.
Un cobro disponible exige confirmación de recepción y referencia bancaria;
importe, moneda y referencia por pedido son idempotentes. Payouts, comisiones,
refunds y reconciliación bancaria automática todavía pendientes. Dashboard
separa monedas y ventas observadas de caja; beneficio, CAC/conversión y ranking
de productos son null si falta atribución completa. No se acredita test mode.
El endpoint antiguo de compra con confirmed genérico queda bloqueado y dirige
al flujo quote/aprobación/ejecución. El margen parcial antiguo también conserva
costes desconocidos como null; scouting web exige símbolo/moneda al extraer precio.

Capacidades persistentes: NicheResearchAgent, ProductScoutAgent, SupplierAgent,
MarginAgent, PricingAgent, ListingAgent, OrderAgent, FulfillmentAgent,
CustomerServiceAgent. OptimizationAgent se extiende sin duplicarlo.
Automaton puede investigar con búsqueda pública, calcular pricing/scoring,
comparar quotes guardados, preparar listing LOCAL y recomendar acciones por
rentabilidad/stock. Cada tarea consulta JEV; SHADOW no ejecuta herramientas.
No se automatizan compras, checkout, publicación ni envío de mensajes.
AccountManager conserva metadatos de identidad verificada de Shopify/Stripe y
referencias de variables, nunca secretos. Los controles de nodos no deducen
LISTO por presencia de env; faltas de configuración aparecen POR CONFIGURAR.

UI dentro de Orquestación: Nichos, Productos, Proveedores, Catálogo, Pedidos,
Fulfillment, Ventas, Márgenes, Devoluciones/soporte, Agentes y Automaton. Detalle
sin otra aplicación, formularios conservados durante refresh, CSRF y confirmación.

### Agency / CRM — base funcional P2, no automatización completa

CRM persistente con estados LEAD/RESEARCH/DEMO/CONTACTED/REPLIED/NEGOTIATING/
WON/LOST/DO_NOT_CONTACT, historial, contactos públicos, propuestas, negociaciones,
borradores, pagos y entrega. Maps discovery limitado requiere confirmar cuota;
investigación pública conserva fuentes y calidad móvil/score como desconocidos
si no hay medición. No se realiza crawling arbitrario ni auditoría móvil ficticia.

Demos locales compartibles específicas para nombre, sector, servicios reales,
ubicación/contacto, diseño responsive y SEO básico. Reutiliza build_demo existente;
no inventa ubicación Madrid ni servicios. Branding avanzado, QA de sitios reales,
webs rotas/antiguas y diseño a medida completo siguen pendientes.

Outreach personalizado se identifica como ZAR Web Agency, incluye demo, alcance,
precio/CTA y baja; se guarda localmente. Gmail draft externo disponible solo con
confirmación/OAuth, pero esta sesión no crea ningún borrador en una cuenta real.
DO_NOT_CONTACT bloquea contactos y checkout; un borrador no marca CONTACTED.
CONTACTED/REPLIED requieren evidencia y confirmación humanas. No se envió email.
Negociación guarda respuesta/objeción, oferta y alcance. Oferta inferior a MINIMUM
requiere aprobación específica. Coste ≤ MINIMUM ≤ TARGET ≤ PREMIUM.

Stripe PaymentAdapter verifica cuenta, crea checkout con idempotency key y URLs
HTTPS de retorno configuradas, y consulta pago autenticado vinculado al scope,
lead, propuesta, importe/moneda. Checkout exige aprobación de total e impuestos
incluidos conocidos. Nunca recoge tarjetas en ZAR/email. PAID no aumenta saldo;
recepción bancaria confirmada crea ingreso una vez. Test mode no cuenta como
pago/ingreso real. Entrega registrada exige pago real y revisión; no despliega.
Estados PENDING/PAID/FAILED/REFUNDED vienen de respuestas del proveedor.
Pendientes webhooks firmados, payouts/fees, refund efectivo, recuperación asistida
de checkout ambiguo, cuotas/mantenimiento, correo entrante asociado automáticamente,
outreach enviado con límites/consentimiento, entrega/despliegue real y QA avanzada.
El CRM no debe presentarse como agencia autónoma end-to-end terminada.

### Contrato del bridge proveedor (no proveedor conectado por defecto)

Secretos para cada registro: PREFIX_CATALOG_URL, PREFIX_QUOTE_URL,
PREFIX_ORDER_WEBHOOK, PREFIX_TRACKING_URL y PREFIX_API_TOKEN.
El prefijo es ZAR_SUPPLIER o ZAR_SUPPLIER_NOMBRE, configurable por registro.
Catálogo GET q → products[] con name/sku y campos disponibles.
Quote POST sku/quantity/country → reference/sku/quantity/currency/product_cost/
shipping/taxes/fees/total/expires_at ISO con timezone, importes de máximo 2 decimales.
Orden POST incluye quote_reference, SKU/cantidad, moneda/total, dirección revisada,
idempotency_key y header Idempotency-Key. Confirmación requiere id/status ORDERED
 o SHIPPED/quote_reference/currency/total. Cargo requiere charged=true,
charged_amount y receipt_reference. Tracking GET order_id → order_id/status/
tracking_number/carrier/tracking_url. Reconciliación GET idempotency_key y
quote_reference debe devolver esas mismas referencias, status y coste/recibo si
existen. Nunca tratar NOT_FOUND como ausencia probada de cargo.
El bridge debe implementarse contra un proveedor real; adaptar contratos nativos
es el próximo trabajo, no se inventan tiendas/proveedores ni disponibilidad.

### Validación del bloque

- 24 tests nuevos Commerce/Agency offline: nichos/scoring/pricing, investigación,
  supplier/quote/Wallet/reserva/cargo/reconciliación, órdenes, tracking/fulfillment,
  listing, cliente/soporte, CRM/demo/baja, negociación, Stripe test/live simulado,
  recepción idempotente, Automaton/SHADOW, CSRF y adapters HTTP.
- 27 pruebas existentes control plane/workflows: PASS junto al bloque nuevo
  (51 unittest tests en la ejecución conjunta).
- Commerce/CRM UI 1920 y 390 con CSS actual: PASS; formularios, CSRF, confirmación,
  detalle, baja, sin desbordamiento global ni errores JS.
- UI workflows/control plane/layout adaptativo: PASS.
- Regresión Stonks en 7 tamaños: PASS; nuevo script servido por mock de estáticos,
  aserciones conservadas, lógica de trading intacta.
- Python compileall, JS y diff check de archivos afectados: PASS.
- Shopify Toolkit validó queries/mutations contra schema 2026-10: VALID con aviso
  Publication.name obsoleto. No garantiza scopes/permisos ni conectividad real.
- No suite pytest completa (no disponible), no tiendas/proveedores/Stripe reales,
  no gastos, órdenes, publicaciones, mensajes ni despliegues externos.

### Configuración pendiente

Shopify: SHOPIFY_SHOP_DOMAIN, SHOPIFY_ADMIN_ACCESS_TOKEN y opcional
SHOPIFY_API_VERSION. App instalada con scopes read_products/read_orders;
read_customers opcional; write_products/read_publications/write_publications
para catálogo, scopes de fulfillment apropiados a la asignación/ubicación.
Obtener vía app/OAuth Shopify: https://shopify.dev/docs/api/admin-graphql/latest
Proveedor: endpoints y token facilitados por proveedor/bridge real; no servicio
preseleccionado ficticio. Registrar contrato/modelo/dropshipping reales en Commerce.
Stripe: STRIPE_SECRET_KEY desde https://dashboard.stripe.com/apikeys;
ZAR_CHECKOUT_SUCCESS_URL y ZAR_CHECKOUT_CANCEL_URL son URLs HTTPS de ZAR revisadas.
Google Maps: ZAR_MAPS_API_KEY, proyecto Places y facturación en Google Cloud.
Email: OAuth Gmail empresarial existente; no introducir password en CRM.
Instagram/TikTok/YouTube mantienen el OAuth/tokens existentes, no se reimplementan.
Configurar valores en secretos/env del servidor; AccountManager solo guarda nombres.

Documentación usada:
https://shopify.dev/docs/api/admin-graphql/latest/mutations/productSet
https://shopify.dev/docs/api/admin-graphql/latest/mutations/publishablePublish
https://shopify.dev/docs/api/admin-graphql/latest/mutations/fulfillmentCreate
https://docs.stripe.com/api/checkout/sessions/create
https://docs.stripe.com/api/checkout/sessions/retrieve

Siguiente bloque recomendado: conectar un proveedor específico real, verificar
Shopify con lecturas, completar refunds/payouts y recuperación de errores con
contratos nativos; luego CRM/outreach autorizado y cobro/entrega completos. No
marcar LISTO por tests mock. Sin push ni deploy.

## 33.3.3
Automaton trading aislado en panel propio; SHADOW/PAPER, pausa y kill reutilizan motor y Risk existentes; LIVE bloqueado. BusinessOrchestrator despacha Commerce/Agency/Sites/Media sin acceso al broker. CRM importa respuestas reales Gmail por identidad y clasificación revisada. Stripe webhook firmado, relectura autenticada e idempotencia; nunca acredita Wallet automáticamente. AccountManager añade tipos y referencias seguras. Voces: candidatos reales, asignación conservando elecciones. Se conserva el bloque 33.3.0–33.3.2. Despliegue mediante GitHub main en servicios Railway existentes. Permanecen pendientes integración telefónica, negociación/envío autónomo, configuración avanzada de proveedores, cierre OAuth AdSense y métricas sociales.
