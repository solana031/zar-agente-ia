# ZAR V24.2

Corrección del contexto Contactos → Gmail.

- Una búsqueda que devuelve un único contacto fija `last_contact`.
- Si ese contacto no tiene email y el usuario pide preparar un correo mediante una referencia al contacto, Zar no reutiliza un destinatario anterior.
- Zar solicita explícitamente una dirección antes de preparar el borrador.
- Se mantienen Gmail, Calendar, Workspace, Maps, archivos, memoria, voz e Internet.
