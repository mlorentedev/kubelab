# KubeLab - Lessons Learned

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

### [2026-02-14] YAML Duplicate Keys Silently Overwrite

**Contexto**: Adding gitea domain override to dev.yaml under `apps.services.core`
**Problema**: Created a second `core:` block instead of adding to the existing one. YAML silently uses the last occurrence, wiping traefik/portainer/n8n overrides. Portainer started routing to `kubelab.live` instead of `kubelab.test`.
**Solución**: Always search for existing key before adding new entries. YAML does NOT merge duplicate keys.
**Regla**: When editing YAML overrides, verify with `python3 -c "import yaml; print(yaml.safe_load(open('file.yaml')))"` that keys aren't duplicated.

### [2026-02-14] Docker Bind Mounts Resolve from Compose File Directory

**Contexto**: web and blog containers in restart loop, `package.json` / `Gemfile` not found
**Problema**: Containers were created from `/home/manu/Projects/mlorente.dev/` (old project path). Relative bind mount paths (`../../../../apps/web/`) resolved to non-existent location.
**Solución**: Recreate containers from the correct working directory (`/home/manu/Projects/kubelab/`).
**Regla**: After renaming project directories, always recreate (not just restart) containers that use relative bind mounts.

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

### [2026-02-09] Docker Anonymous Volumes Inherit Image Ownership

**Contexto**: Construyendo imagenes Docker para apps web (Astro, Jekyll)
**Problema**: El build stage corre como root, creando `node_modules/`, `.vite/`, `.astro/` con ownership root. Aunque compose tiene `user: "1000:1000"`, los volumenes anonimos creados durante build mantienen ownership root, causando errores de permisos en runtime.
**Solucion**: Usar `USER node` en el Dockerfile build stage, no solo la directiva `user:` en compose. Los volumenes deben crearse ya con el usuario correcto.
**Regla**: Siempre verificar ownership de volumenes anonimos en imagenes multi-stage. `docker compose exec <svc> ls -la /app/` antes de buscar bugs en el codigo.

### [2026-02-09] Staging Must Mirror Prod Architecture

**Contexto**: Diseñando entorno staging en homelab con Raspberry Pis
**Problema**: Si prod es single-VPS con Docker Compose, staging debe ser single-node con Docker Compose. Usar RPis como nodos de stack introduce diferencias arquitecturales que invalidan la validacion staging→prod.
**Solucion**: MiniPC B = staging (mirror de VPS). RPis = infraestructura transversal (VPN, DNS, monitoring externo), NO nodos de stack.
**Regla**: staging == prod en arquitectura. La infra auxiliar (VPN, DNS, monitoring) vive en nodos separados para no contaminar la validacion.

### [2026-02-09] Tailscale Over WireGuard When No Port Forwarding

**Contexto**: Configurando VPN para acceso remoto al homelab
**Problema**: WireGuard necesita puerto UDP abierto en el router. Sin acceso al router (NAT sin port forwarding) → WireGuard imposible. Headscale requiere nodo publico.
**Solucion**: Tailscale (o Headscale via relay publico). Las restricciones de red dictan la tecnologia, no la preferencia.
**Regla**: Antes de elegir VPN, verificar: ¿tengo port forwarding? Si → WireGuard. Si no → Tailscale/Headscale. La arquitectura de red manda.

### [2026-02-09] Ansible Templates Drift from Code

**Contexto**: Auditing Ansible templates after major refactoring (infra/compose → infra/stacks)
**Problema**: Templates en `infra/ansible/templates/` todavia referencian `infra/compose`, puertos k3s (6443), wiki, n8n, wireguard. Los templates divergen silenciosamente cuando se refactoriza el repo sin actualizar Ansible.
**Solucion**: Auditar templates cada vez que cambia la estructura del proyecto. Incluir Ansible en el checklist de refactoring.
**Regla**: Ansible templates son ciudadanos de primera clase. Un refactoring no esta completo hasta que los templates de Ansible estan alineados.

### [2026-02-09] OS Choice Matters for Staging

**Contexto**: Eligiendo SO para nodo staging en homelab
**Problema**: Si staging corre Arch Linux (rolling release) y prod corre Ubuntu Server (LTS), hay una clase entera de bugs "funciona en staging, falla en prod" causados por diferencias de kernel, libc, paquetes.
**Solucion**: Staging OS == Prod OS. Ambos Ubuntu Server 24.04 LTS.
**Regla**: Staging debe ser identico a prod en SO, version, y configuracion base. Las diferencias de SO son bugs esperando a manifestarse.

### [2026-02-10] Always Verify Hardware Specs Against Physical Devices

**Contexto**: Planificando la arquitectura del homelab (Stream B) usando especificaciones de hardware documentadas
**Problema**: Las especificaciones documentadas eran incorrectas: 16GB para staging (real: 12GB Acemagic), 4GB para RPi 4 (real: 8GB). Ademas, faltaban dispositivos: RPi 3 con Pi-hole, Beelink con Proxmox. Toda la planificacion se baso en datos incorrectos.
**Solucion**: Verificar fisicamente cada dispositivo (`free -h`, `lsblk`, model labels) antes de documentar o planificar. Actualizar toda la documentacion (vault, todo.md, Ansible templates) con las especificaciones reales.
**Regla**: Antes de planificar infraestructura, SIEMPRE verificar specs de hardware contra los dispositivos fisicos. Los documentos mienten; `free -h` no miente. Un plan basado en specs incorrectas es peor que no tener plan.

### [2026-02-20] Proxmox Hostname Rename Breaks VM Visibility

**Contexto**: Renombrando hostnames de `cubelab-*` a `kubelab-*` como parte del rename global del proyecto
**Problema**: Después de `hostnamectl set-hostname kubelab-ace1`, `qm list` devuelve vacío. Las VMs parecen haber desaparecido. Proxmox vincula los `.conf` de las VMs al directorio `/etc/pve/nodes/{hostname}/qemu-server/`. Al cambiar el hostname, Proxmox crea un nuevo directorio pero los configs quedan en el viejo.
**Solución**: Mover los `.conf` del directorio antiguo al nuevo:
```bash
ls /etc/pve/nodes/                    # Verás old-name y new-name
mv /etc/pve/nodes/{old}/qemu-server/*.conf /etc/pve/nodes/{new}/qemu-server/
qm list                               # VMs reaparecen
qm start <vmid>
```
**Regla**: NUNCA renombrar un host Proxmox con solo `hostnamectl`. Siempre verificar `/etc/pve/nodes/` y mover los configs de VM. Documentado también en el runbook `proxmox-setup.md` del vault.

---

*Mas entradas se anadiran conforme avance el proyecto.*
