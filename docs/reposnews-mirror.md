# ReposNews: producción y copia estática

Producción y fuente editorial: https://www.reposnews.com (Railway).
Mirror/backup/preview: https://solana031.github.io (GitHub Pages).
No hay cutover ni cambios DNS; el plan anterior queda archivado como opción futura.

`deploy/reposnews-mirror.yml` está instalado en el repositorio de Pages.
El runner comprueba cada cinco minutos los snapshots PUBLISHED de producción;
GitHub puede retrasar ejecuciones. No requiere PC ni token en Railway.
Una aprobación publica primero en Railway; la siguiente ejecución deriva la copia.
Un borrador o revisión privada no modifica el manifest público ni dispara un build.
Si producción no responde o cambia durante el build, no se despliega esa copia.
Cada sync verificada se guarda también en Git como backup navegable. Se renueva
al menos semanalmente con contenido público aprobado para evitar inactividad del repo.

Sites muestra SYNCED / OUTDATED / ERROR, última sincronización, paridad y botón
SINCRONIZAR MIRROR. El botón solicita un rebuild para el siguiente runner, sin
confirmación adicional. Actions también permite `workflow_dispatch` inmediato.
La campana distingue MIRROR_SYNC_SUCCESS / MIRROR_SYNC_FAILED / MIRROR_OUTDATED;
un fallo del mirror conserva PRIMARY_PUBLISHED. Reintentar vuelve a ponerlo en cola.

El mirror conserva canonical en producción y añade `noindex,follow` a cada HTML.
Robots permite rastreo para que el buscador pueda leer noindex; no se envía su sitemap.
Assets propios; verificaciones reales HTTP y comparación de IDs/revisiones ES/EN.
El monitor comprueba el artefacto desplegado, no solo el resultado de un push.
REPOSNEWS_RECOVERY_READY significa copia sincronizada y verificada; no activa recuperación.

Si Railway falla, Pages conserva el último artefacto navegable. La promoción a
producción exigiría otra decisión explícita y revertir noindex en un build futuro.
El documento de cutover existente NO autoriza ejecutar cambios.
