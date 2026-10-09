# REFERENCIA / NO EJECUTABLE

Estado: copias de código de producción conservadas únicamente para inspección y diseño. No ejecutar, no sourcear ni asociar a timers/servicios. Los tres scripts tienen modo 0644 en Manager. Cambiar estos archivos o diseñar reemplazos requiere una fase/autorización posterior.

La comprobación de patrones de credenciales incrustadas no encontró candidatos en estos tres scripts (`SECRET_REMOVED = FALSE`). No se abrió ni copió contenido de configuraciones externas, archivos `.env` ni credenciales.

| Archivo en Manager | Origen activo | SHA-256 | Función/efecto observado |
|---|---|---|---|
| `traccar_retencion_90d.sh` | `/root/traccar_retencion_90d.sh` | `f0e4ef4b11ba2a389504bbdea179992d467c8a3eef20f9b1340d403d31ddaa27` | Retención de posiciones; cliente MySQL, SELECT y DELETE sobre datos de Traccar; requiere root en producción. Destructivo. |
| `traccar_log_retencion_30d.sh` | `/root/traccar_log_retencion_30d.sh` | `262de8a7954eab8e271ab61d69f932e04db98bbe6d947b71400250713ea18cef` | Retención de logs; elimina logs antiguos, usa lock y estado; requiere root en producción. Destructivo para archivos. |
| `traccar-panel-status.sh` | `/usr/local/sbin/traccar-panel-status.sh` | `f77e6c6f78f515d295711b32df2ce26b1eeac88dee41e1d63d64cb270a605505` | Recopila estado con systemd y escribe telemetría; el servicio actual corre como `traccar-panel`. No reinicia Traccar. |

Las unidades/timers de producción no se copian ni se habilitan en Manager. Estas referencias no forman parte de una implementación activa.
