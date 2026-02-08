# CubeLab - Lessons Learned

> Este archivo documenta patrones aprendidos, errores evitados, y mejores prácticas descubiertas durante el desarrollo.
>
> **Protocolo**: Actualizar después de cada corrección o descubrimiento importante.

---

## Formato

```markdown
### [FECHA] Título del Aprendizaje

**Contexto**: Qué estaba haciendo
**Problema**: Qué salió mal o qué descubrí
**Solución**: Cómo lo resolví
**Regla**: Patrón a seguir en el futuro
```

---

## Registro

### [2026-02-03] Inicialización del Sistema de Tasks

**Contexto**: Configurando el proyecto después de un periodo de inactividad
**Problema**: 655 archivos staged sin commitear, documentación desalineada con realidad
**Solución**: Crear sistema de tasks según CLAUDE.md global, plan detallado antes de ejecutar
**Regla**: Siempre mantener `tasks/todo.md` actualizado. Nunca acumular más de 1 sprint de cambios sin commitear.

### [2026-02-05] Code Bugs Masked as Documentation Issues

**Contexto**: Audit completo del proyecto antes de Sprint 0
**Problema**: El plan anterior trataba todo como "alinear documentacion" pero habia bugs de codigo reales:
- Toolkit referencia `docker-compose.{env}.yml` en 6 archivos, pero los archivos reales son `compose.{base|dev|staging|prod}.yml`
- `toolkit edge` importado pero nunca registrado en CLI
- `toolkit apps` eliminado pero documentado como activo
- `pre-push.sh` ejecuta `task lint` sin Taskfile existente
**Solucion**: Dividir Sprint 0 en 0A (fix code) → 0B (align docs) → 0C (validate+commit)
**Regla**: Siempre auditar el codigo ejecutable antes de tocar documentacion. Un `grep -rn` de los patrones criticos vale mas que 14 tasks de documentacion.

### [2026-02-05] ConfigurationManager vs Direct File References

**Contexto**: Descubriendo por que algunas operaciones del toolkit funcionarian y otras no
**Problema**: `configuration.py:144-168` tiene la logica correcta (compose.base.yml + compose.{env}.yml con fallback legacy), pero 4 modulos CLI construyen filenames directamente sin usar ConfigurationManager
**Solucion**: Identificar y migrar todos los modulos a usar ConfigurationManager.get_compose_files()
**Regla**: Single source of truth para file resolution. Nunca construir paths de compose en mas de un lugar. Si existe una abstraccion, usarla.

### [2026-02-05] Plan Scope vs Execution Capacity

**Contexto**: Proyecto con 655 archivos sin commitear y roadmap de 6 meses con K3s, CKA, 60 ADRs
**Problema**: Plan anterior incluia K3s migration, certifications, newsletter targets, GitHub org migration - todo mientras el proyecto ni puede commitear su codigo
**Solucion**: Reducir horizonte a 3 meses ejecutables, mover todo lo aspiracional a backlog con tiers
**Regla**: Un plan que no puedes ejecutar en 2 sprints de distancia es fantasia, no ingenieria. Trim agresivamente.

---

*Mas entradas se anadiran conforme avance el proyecto.*
