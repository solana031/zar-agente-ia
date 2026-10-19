# ReposNews: preview y cutover pendiente

Preview: https://solana031.github.io/ · repositorio: solana031/solana031.github.io.
GitHub Pages sirve exclusivamente el artefacto aprobado, sin Flask, DB ni Railway.
No hay custom domain asociado y no se ha cambiado DNS.

## Publicación preparada

`app/reposnews_static_publish.publish_approved()` reutiliza la aprobación exacta
de la revisión publicada y la campana existente. Ejecuta build → deploy → verify;
solo después emite PUBLISH_SUCCESS con URL, fecha y acciones. Un fallo emite
PUBLISH_FAILED con RETRY/DETAILS y conserva la revisión editorial.
Es un punto de integración preparado, NO un trigger automático activado.
RETRY/DETAILS abre el editor existente; el reintento requiere invocar el runner.
No se han introducido credenciales GitHub en Railway.

El runner local puede reutilizar `build_reposnews_static(output_nuevo)`, calcular
`tools.reposnews_static_host.artifact_digest(output)` y llamar a
`deploy(output, digest_aprobado, workspace_local)`. El adaptador publica por Git,
sin force-push ni cambios de dominio. Esperar a Pages SUCCESS y ejecutar
`verify(output)`; no confundir un push con una publicación verificada.
Se acepta rebuild completo. Nunca usar un borrador como entrada.
Tras el cutover aprobado, pasar `public_base='https://www.reposnews.com'` al
adaptador y verificar esa URL; antes del cutover, usar siempre la preview.
Validación reproducible: `python tests/reposnews_static_live.py` (HTTP real y
Playwright instalado); conserva informes y capturas en `.local/reposnews-static-verification`.

## Cutover: ejecutar únicamente tras nueva aprobación de Pablo

El plan y los valores actuales están en `reposnews-static-cutover.json`.
Canonical: **www.reposnews.com**, conservando todas las rutas ES/EN.
Antes del cambio: volver a exportar la zona IONOS y comparar con el snapshot;
asociar www en GitHub Pages ANTES de modificar registros DNS.
Después: aplicar solo A/AAAA del apex y CNAME www indicados; conservar NS/MX/TXT.
Esperar propagación y certificado, activar HTTPS y comprobar apex → www sin loops.
La emisión SSL puede tardar hasta 24 horas; no afirmar SSL custom verificado antes.
Railway conserva CMS, automatización y su dominio actual para rollback.

Rollback DNS: restaurar A/AAAA del apex y CNAME www guardados; verificar Railway.
Rollback estático: revertir el commit fallido mediante un nuevo commit en el
repositorio estático, push a main y verificar Pages. No hacer force-push.

La captura pública no sustituye una exportación completa de IONOS.
Referencia: https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site
