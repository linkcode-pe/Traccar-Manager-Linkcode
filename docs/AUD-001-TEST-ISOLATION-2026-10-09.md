# AUD-001 — Aislamiento de pruebas

La batería inicial en laboratorio falló con 5 fallos y 13 errores porque el módulo de progreso usaba una ruta fija de SQLite productiva. La rama de desarrollo permite configurar `TRACCAR_MANAGER_PROGRESS_DB` y el ejecutor aislado establece la ruta dentro de `$LAB`. La batería aislada con el parche finalizó con código de salida 0 y nueve omisiones. No se cambió la base de datos de producción. Pendiente aprobación de integración y despliegue.
