# ZAR v30.4.0 — Sistema de Habilidades persistentes

## Novedad principal

ZAR incorpora un sistema de **Habilidades**: procedimientos reutilizables creados por el usuario y almacenados de forma persistente por cuenta/usuario dentro de `ZAR_DATA_DIR`.

### Funciones
- Crear habilidades con nombre y descripción.
- Definir pasos reutilizables.
- Definir frases de activación.
- Indicar herramientas previstas.
- Activar/pausar, editar y eliminar habilidades.
- Ejecutarlas desde la interfaz o mediante una orden explícita en el chat.
- Contabilizar usos y conservar la configuración tras los despliegues.

### Persistencia y seguridad
- Las habilidades se guardan en `users/<usuario>/skills/skills.json`.
- No se incluyen en los ZIP de release.
- Una habilidad no modifica el código, permisos ni configuración de ZAR.
- Las acciones externas siguen sujetas a las confirmaciones de seguridad existentes (correo, Google Workspace, etc.).
- El sistema no ejecuta una habilidad por una mera mención accidental: la invocación requiere una orden explícita.

### Ejemplo
1. Crear `Informe semanal`.
2. Pasos: buscar información → consultar memoria → analizar → generar resumen.
3. Activador: `informe semanal`.
4. En el chat: `ZAR, ejecuta mi habilidad Informe semanal sobre esta semana.`

## Compatibilidad
Esta versión conserva las funciones existentes de ZAR v30.3.1 y utiliza el mismo almacenamiento persistente.
