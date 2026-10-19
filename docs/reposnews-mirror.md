# ReposNews: producciÃ³n y copia estÃ¡tica

ProducciÃ³n y fuente editorial: https://www.reposnews.com (Railway).
Mirror/backup/preview: https://solana031.github.io (GitHub Pages).
No hay cutover ni cambios DNS; el plan anterior queda archivado como opciÃ³n futura.

`deploy/reposnews-mirror.yml` estÃ¡ instalado en el repositorio de Pages.
El flujo principal detecta cambios en snapshots PUBLISHED después de la publicación
principal, verifica su manifest HTTP y solicita el workflow existente de Pages.
Necesita REPOSNEWS_MIRROR_DISPATCH_TOKEN como secreto del servidor principal, limitado
al repositorio solana031/solana031.github.io con Actions: write. No se obtiene ni
se copia automáticamente el token local de gh. Si falta, Sites muestra AUTH_REQUIRED:
el disparo inmediato no está activo; no se presenta como configurado.

El respaldo es una comprobación diaria (06:17 UTC), nunca cada cinco minutos.
Antes de construir se compara source_revision/source_hash. Igualdad => NOOP:
no builder, artefacto, deploy ni notificación. Edad, commit de aplicación ajeno y
nonce manual no fuerzan rebuild. Un cambio durante el build cancela el despliegue.
Se guardan source_revision, source_hash y last_successful_sync verificado en servidor.

Sites mantiene SINCRONIZAR MIRROR. Con el secreto configurado despierta el mismo
flujo y verifica paridad antes del dispatch; sin él queda explícitamente pendiente
de autorización y del respaldo diario. workflow_dispatch también respeta NOOP.
No hay renovación semanal ni despliegues para mantener activo el repositorio.
GitHub puede desactivar schedules tras inactividad prolongada; el evento/manual
sigue disponible y la reactivación del schedule se realiza en GitHub si se desea.

La campana distingue MIRROR_SYNC_SUCCESS / MIRROR_SYNC_FAILED / MIRROR_OUTDATED;
un fallo del mirror conserva PRIMARY_PUBLISHED. Reintentar vuelve a ponerlo en cola.

El mirror conserva canonical en producciÃ³n y aÃ±ade `noindex,follow` a cada HTML.
Robots permite rastreo para que el buscador pueda leer noindex; no se envÃ­a su sitemap.
Assets propios; verificaciones reales HTTP y comparaciÃ³n de IDs/revisiones ES/EN.
El monitor comprueba el artefacto desplegado, no solo el resultado de un push.
REPOSNEWS_RECOVERY_READY significa copia sincronizada y verificada; no activa recuperaciÃ³n.

Si Railway falla, Pages conserva el Ãºltimo artefacto navegable. La promociÃ³n a
producciÃ³n exigirÃ­a otra decisiÃ³n explÃ­cita y revertir noindex en un build futuro.
El documento de cutover existente NO autoriza ejecutar cambios.
