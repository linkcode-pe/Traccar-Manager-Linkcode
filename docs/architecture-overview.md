# Visión general de arquitectura

**Documento conceptual.** Esta arquitectura no está implementada y no habilita conexiones ni operaciones en el servidor.

```text
[Usuario]
   |
   v
[Traccar Manager]
   |
   +---- API y servicios propios
   |
   +---- administración del sistema mediante interfaces controladas
   |
   +---- herramientas de mantenimiento
   |
   +---- integración controlada con Traccar
   |
   +---- integración futura con base de datos
   |
   v
[Traccar]
```

Traccar Manager será un producto separado de Traccar. Las futuras interfaces deberán tener límites explícitos de privilegios, validación, auditoría y recuperación. No se debe asumir que exista una integración directa con la base de datos ni implementar acceso arbitrario a ella.

Las operaciones destructivas sobre archivos requieren una acción explícita, validación previa y recuperación. La primera versión de limpieza solo detectará y reportará; no eliminará archivos automáticamente.
