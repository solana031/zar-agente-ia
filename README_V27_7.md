# Zar V27.7 — Studio Editor Pro + Visual Learning

Basada en V27.6.

## Cambios
- Texto libre sobre imágenes: añadir, seleccionar y arrastrar directamente sobre el lienzo.
- Texto libre sobre vídeo: seleccionar clip, añadir texto y moverlo directamente sobre la previsualización.
- Tipografías, tamaño, color, opacidad, giro y estilos (normal, sombra, contorno, caja, brillo).
- Los overlays de vídeo se guardan en el proyecto y se integran en el render MP4.
- Órdenes por texto y voz en el editor de imagen para cambios sencillos.
- Laboratorio de inspiración: búsqueda de referencias visuales públicas online, análisis visual con Gemini y generación de propuestas de mejora para Studio.
- Los aprendizajes se pueden guardar en la memoria persistente de Zar.
- Mejora supervisada: Zar no reescribe ni despliega automáticamente su propio código; las propuestas de software requieren aprobación humana.
- Se mantiene la previsualización sin descarga y la separación Zar principal / Centro de control / Zar Studio.

## Instalación cloud
1. Sustituye el contenido del repositorio GitHub por esta versión.
2. Haz Commit changes.
3. Railway debe desplegar automáticamente el nuevo commit.
4. Recarga Zar con Ctrl+F5.

No hay nuevas variables de Railway obligatorias.

## Nota de credenciales
`credentials.json` se mantiene para compatibilidad con las versiones de escritorio. En Railway usa las variables de entorno ya configuradas y no publiques secretos en GitHub.
