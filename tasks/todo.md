# CubeLab - Roadmap

> **Objetivo**: Estabilizar, desplegar a producción, construir homelab staging.
>
> **Horizonte**: 3 meses ejecutables. Backlog separado para ideas futuras.
>
> **Estrategia**: Fix code → Commit → Local dev → Production VPS → Homelab staging

---

## Quick Reference

| Simbolo | Estado |
|---------|--------|
| `[ ]` | Pendiente |
| `[~]` | En progreso |
| `[x]` | Completado |
| `[!]` | Bloqueado |

| Prioridad | Significado |
|-----------|-------------|
| **P0** | Critico - Bloquea todo |
| **P1** | Alto - Sprint actual |
| **P2** | Medio - Proximo sprint |
| **P3** | Bajo - Backlog |

---

## Dependency Graph

```text
Sprint 0A (Fix Broken Code)
    │
    └──► Sprint 0B (Align Documentation)
              │
              └──► Sprint 0C (Validate + Commit + PR)
                        │
                        └──► Sprint 1 (Local Dev Working)
                                  │
                                  ├──► Sprint 2 (Production VPS)
                                  │
                                  └──► Sprint 3 (Homelab Staging)
                                            │
                                            └──► Sprint 4 (Persistence + Observability)

Backlog (P3 - sin dependencias directas):
    Workers Phase 2+, ClawdBot, K3s, GitHub Org Migration
```

---

## Hardware Allocation

```
┌─────────────────────┬───────────────────────────────────┐
│  VPS Hetzner        │ Produccion + WireGuard Hub        │
│  162.55.57.175      │ Traefik + Apps + Loki + Uptime    │
├─────────────────────┼───────────────────────────────────┤
│  Mini PC #1         │ Proxmox: VM staging               │
│  (Proxmox)          │ Docker Compose stack              │
│  + USB 128GB        │ /mnt/staging-data (futuro PG)     │
├─────────────────────┼───────────────────────────────────┤
│  Mini PC #2         │ Reservado (Sprint 4+)             │
│  (sin asignar)      │ Observability dedicada o K3s      │
├─────────────────────┼───────────────────────────────────┤
│  RPi #1             │ Pi-hole + DNS local               │
├─────────────────────┼───────────────────────────────────┤
│  RPi #2             │ Reservado (futuro K3s ARM64)      │
└─────────────────────┴───────────────────────────────────┘
```

---

## Hallazgos del Audit (2026-02-05)

Bugs de codigo descubiertos que el plan anterior no contemplaba:

| # | Bug | Severidad | Archivos |
|---|-----|-----------|----------|
| 1 | Toolkit referencia `docker-compose.{env}.yml` pero archivos reales son `compose.{base,env}.yml` | **CRITICO** | `cli/services.py`, `cli/infra.py`, `features/validation.py`, `config/constants.py`, `features/generator_traefik.py` |
| 2 | `toolkit edge` importado en `main.py:16` pero nunca registrado con `add_typer()` | **ALTO** | `toolkit/main.py` |
| 3 | `toolkit apps` eliminado (Phase 8) pero CLAUDE.md lo documenta como comando activo | **ALTO** | `CLAUDE.md`, `docs/TOOLKIT.md` |
| 4 | `constants.py` COMPOSE_FILE_TEMPLATE = `docker-compose.{}.yml` (patron legacy) | **ALTO** | `toolkit/config/constants.py:126` |
| 5 | `pre-push.sh` ejecuta `task lint` pero no existe Taskfile | **MEDIO** | `.github/hooks/pre-push.sh` |
| 6 | Terraform `services.json` contiene solo `PLACEHOLDER` | **MEDIO** | `infra/terraform/dns/services.json` |
| 7 | `SERVICES_CORE` en constants.py incluye "traefik" (es edge, no core) | **BAJO** | `toolkit/config/constants.py:54` |
| 8 | `infra/stacks/apps/workers/` vacio - sin compose files | **BAJO** | directorio vacio |
| 9 | `tests/` directorio no existe en disco (solo staged) | **INFO** | tests/ |
| 10 | `sprint-0-docs-checklist.md` referencia `infra/compose/` (obsoleto) | **BAJO** | `tasks/sprint-0-docs-checklist.md` |

---

## Fase 1: Estabilizacion (Semanas 1-3)

### Sprint 0A: Corregir Codigo Roto [P0]

> **Contexto**: 655 archivos staged en `feature/blog-restruct`
> **Problema critico**: El toolkit CLI no encontrara compose files porque busca nombres incorrectos
> **Duracion**: 2-4 horas

Estos bugs deben corregirse ANTES de alinear documentacion o commitear.

#### FIX-001: Corregir patron de nombres de compose files

El toolkit busca `docker-compose.{env}.yml` pero los archivos reales son `compose.{base|dev|staging|prod}.yml`.

**Archivos a corregir**:

- [x] `toolkit/config/constants.py:126` - Cambiar COMPOSE_FILE_TEMPLATE
  ```python
  # ANTES
  COMPOSE_FILE_TEMPLATE: str = "docker-compose.{}.yml"
  # DESPUES
  COMPOSE_FILE_TEMPLATE: str = "compose.{}.yml"
  ```

- [x] `toolkit/cli/services.py:168,203,246` - Refactorizado a `ConfigurationManager.get_compose_files()`
  ```python
  # ANTES
  f"docker-compose.{environment}.yml"
  # DESPUES - usar ConfigurationManager.get_compose_files() en su lugar
  ```

- [x] `toolkit/cli/infra.py:519` - Nuke refactorizado: eliminado compose lookup legacy, usa docker stop/prune
  ```python
  # ANTES
  compose_file = f"docker-compose.{env}.yml"
  # DESPUES
  compose_file = f"compose.{env}.yml"
  ```

- [x] `toolkit/features/validation.py:98` - Corregir path de validacion
  ```python
  # ANTES
  compose_file = component_dir / f"docker-compose.{environment}.yml"
  # DESPUES
  compose_file = component_dir / f"compose.{environment}.yml"
  ```

- [x] `toolkit/features/generator_traefik.py:105-107` - Corregir lista de archivos
  ```python
  # ANTES
  "docker-compose.dev.yml", "docker-compose.staging.yml", "docker-compose.prod.yml"
  # DESPUES
  "compose.dev.yml", "compose.staging.yml", "compose.prod.yml"
  ```

- [x] `toolkit/features/generator_wiki.py:208-209` - Corregir path `infra/compose/services` → `PATH_STRUCTURES.INFRA_STACKS_SERVICES`

**Verificacion**:
```bash
# Despues de corregir, no debe haber resultados:
grep -rn "docker-compose\." toolkit/ --include="*.py" | grep -v "DOCKER_COMPOSE_CMD" | grep -v "__pycache__"
```

#### FIX-002: Registrar o eliminar edge CLI

- [x] N/A - El import fantasma no existe en main.py actual. `toolkit/cli/edge.py` tampoco existe. Bug ya resuelto antes del audit.

#### FIX-003: Corregir constants.py SERVICES_CORE

- [x] Eliminar "traefik" de `SERVICES_CORE` (es un edge service, no core)
  ```python
  # ANTES
  SERVICES_CORE: Sequence[str] = ("traefik", "portainer", "n8n", "gitea", "vaultwarden")
  # DESPUES
  SERVICES_CORE: Sequence[str] = ("portainer", "n8n", "gitea", "vaultwarden")
  ```

#### FIX-004: Corregir pre-push hook

- [x] `.github/hooks/pre-push.sh` ejecuta `task lint` pero no hay Taskfile
  - Aplicada Opcion A: Cambiado a `make lint`

#### FIX-005: Limpiar referencias a `infra/compose/` en toolkit

- [x] `toolkit/features/generator_wiki.py` - Corregido en FIX-001 (path + docstring)
- [x] `toolkit/features/validation.py` - Corregido en FIX-001 (docstring find_component_directory)
  ```bash
  grep -rn "infra/compose" toolkit/ --include="*.py"
  ```

**Definition of Done Sprint 0A**:
```bash
# Todos estos deben pasar:
poetry run python -c "from toolkit.main import app; print('OK')"
grep -rn "docker-compose\." toolkit/ --include="*.py" | grep -v "DOCKER_COMPOSE_CMD" | grep -v "__pycache__" | wc -l  # debe ser 0
grep -rn "infra/compose" toolkit/ --include="*.py" | wc -l  # debe ser 0
```

---

### Sprint 0B: Alinear Documentacion [P0]

> **Bloqueado por**: Sprint 0A completado
> **Duracion**: 2-4 horas

#### TICKET-000: Actualizar Documentacion

**Problema**: La documentacion referencia paths y comandos que no existen:

| Que | Docs Dicen | Realidad |
|-----|------------|----------|
| Compose path | `infra/compose/` | `infra/stacks/` |
| File naming | `docker-compose.{env}.yml` | `compose.{base,dev,staging,prod}.yml` |
| CLI apps | `toolkit apps up web` | `toolkit services up web` (apps fue eliminado) |
| CLI edge | `toolkit edge up traefik` | Depende de FIX-002 |
| Env location | `configs/env/` | `infra/config/env/` |
| Toolkit structure | `toolkit/commands/` | `toolkit/cli/` |

**Estructura Real** (post-migracion):

```
infra/stacks/
├── apps/           api/, blog/, web/, wiki/, workers/
├── edge/           traefik/, nginx/, cloudflared/
└── services/
    ├── ai/          ollama, webui
    ├── automation/  github-runner, kestra
    ├── core/        gitea, portainer
    ├── data/        docmost, minio
    ├── misc/        calcom, immich
    ├── observability/ grafana, loki, uptime
    └── security/    authelia, crowdsec
```

**Tareas (por prioridad)**:

- [x] **ALIGN-001**: Actualizar `CLAUDE.md` (15 edits: paths, comandos, arbol directorios)
- [x] **ALIGN-002**: Actualizar `README.md` (7 edits: paths, comandos, tree)
- [x] **ALIGN-003**: `docs/HOW-TO.md` - N/A, ya era un pointer al vault sin refs obsoletas
- [x] **ALIGN-004**: Actualizar `docs/TOOLKIT.md` (18 reemplazos: apps→services, paths, tree)
- [x] **ALIGN-005**: Actualizar `CONTRIBUTING.md` (13 edits: paths, comandos)
- [x] **ALIGN-006**: `docs/CUBELAB.md` - N/A, ya era un pointer al vault sin refs obsoletas
- [x] **ALIGN-007**: `.github/workflows/content-validation.yml` (1 path fix)
- [x] **ALIGN-008**: `.github/workflows/ci-01-dispatch.yml` (9 path fixes en dorny/paths-filter)
- [x] **ALIGN-009**: `apps/README.md` (7 edits: paths, comandos, filenames)
- [x] **ALIGN-010**: `tasks/sprint-0-docs-checklist.md` - Archivo borrado (redundante con todo.md)
- [x] **Extra**: `docs/TESTING.md` (1 fix: toolkit apps → toolkit services en ejemplo)

**Verificacion**:
```bash
# No deben quedar referencias obsoletas en docs:
grep -rn "infra/compose" docs/ CLAUDE.md README.md CONTRIBUTING.md --include="*.md" | wc -l  # debe ser 0
grep -rn "toolkit apps" docs/ CLAUDE.md README.md CONTRIBUTING.md --include="*.md" | wc -l  # debe ser 0
grep -rn "toolkit/commands" docs/ CLAUDE.md README.md CONTRIBUTING.md --include="*.md" | wc -l  # debe ser 0
```

---

### Sprint 0C: Validar y Commitear [P0]

> **Bloqueado por**: Sprint 0A + 0B completados
> **Duracion**: 1-2 horas

- [x] **VAL-001**: Buscar secretos accidentalmente staged (3 falsos positivos: GH secret ref, placeholder, test example)
  ```bash
  git diff --cached --name-only | xargs grep -l -i -E "(password|secret|token|api_key)=.[^C]" 2>/dev/null
  # Excluir lineas con CHANGE_ME (son templates)
  ```

- [x] **VAL-002**: Verificar .gitignore cubre archivos sensibles
  ```bash
  grep -E "\.env$|\.env\.[^e]|secrets|\.sops" .gitignore
  ```

- [x] **VAL-003**: Smoke test del toolkit (import OK, --help OK, services --help OK)
  ```bash
  poetry run python -c "from toolkit.main import app; print('Import OK')"
  poetry run toolkit --help
  poetry run toolkit services --help
  ```

- [x] **VAL-004**: Validar sintaxis Python (9/9 archivos OK)
  ```bash
  poetry run python -m py_compile toolkit/main.py
  poetry run python -m py_compile toolkit/cli/services.py
  poetry run python -m py_compile toolkit/features/docker_service.py
  ```

- [ ] **VAL-005**: Commit 1 - Reorganizacion (655 archivos staged)
- [ ] **VAL-006**: Commit 2 - Sprint 0 fixes (codigo + docs)
- [ ] **VAL-007**: Push branch (sin PR todavia - primero Sprint 1 para verificar que todo funciona)

**Definition of Done Sprint 0**:
- [x] Toolkit importa sin errores
- [x] No hay secretos en el commit
- [ ] Commits creados y pusheados
- [ ] PR se crea despues de Sprint 1 (verificacion local completa)

---

### Sprint 1: Entorno Local Funcionando [P1]

> **Bloqueado por**: Sprint 0 completado (PR mergeado)
> **Duracion**: 3-5 dias

#### Phase 1: Verificar Toolkit CLI

- [ ] **T-001**: CLI carga y responde
  ```bash
  poetry run toolkit --help
  poetry run toolkit services list
  poetry run toolkit config validate
  ```

- [ ] **T-002**: Generar configuracion dev
  ```bash
  ENVIRONMENT=dev poetry run toolkit config generate
  ```

- [ ] **T-003**: Verificar configs generadas
  ```bash
  ls edge/traefik/generated/dev/
  ls infra/ansible/generated/dev/ 2>/dev/null
  ```

#### Phase 2: Levantar Primera App (Web)

- [ ] **T-004**: Levantar Traefik local
  ```bash
  poetry run toolkit services up traefik
  # Verificar: docker ps | grep traefik
  ```

- [ ] **T-005**: Levantar web app
  ```bash
  poetry run toolkit services up web
  # Verificar: curl -k https://web.cubelab.test (si DNS configurado)
  # O: curl http://localhost:{port}
  ```

- [ ] **T-006**: Verificar logs y healthcheck
  ```bash
  poetry run toolkit services logs web --no-follow
  ```

#### Phase 3: Levantar Resto de Apps

- [ ] **T-007**: Blog
  ```bash
  poetry run toolkit services up blog
  ```

- [ ] **T-008**: Wiki
  ```bash
  poetry run toolkit services up wiki
  ```

- [ ] **T-009**: API
  ```bash
  poetry run toolkit services up api
  ```

#### Phase 4: Build Tests

- [ ] **T-010**: Build API (Go)
  ```bash
  cd apps/api/src && go build ./... && cd -
  ```

- [ ] **T-011**: Build Web (Astro)
  ```bash
  cd apps/web/astro-site && npm ci && npm run build && cd -
  ```

- [ ] **T-012**: Build Blog (Jekyll)
  ```bash
  cd apps/blog/jekyll-site && bundle install && bundle exec jekyll build && cd -
  ```

- [ ] **T-013**: Build Wiki (MkDocs)
  ```bash
  cd apps/wiki && mkdocs build && cd -
  ```

#### Phase 5: Calidad de Codigo (Toolkit)

- [ ] **T-014**: Type checking
  ```bash
  poetry run mypy toolkit/
  ```

- [ ] **T-015**: Linting
  ```bash
  poetry run ruff check toolkit/
  poetry run black --check toolkit/
  ```

- [ ] **T-016**: Crear tests/ directorio con smoke tests basicos
  ```bash
  mkdir -p tests
  # Crear test minimo: importar toolkit, verificar CLI commands registrados
  poetry run pytest tests/ -v
  ```

#### Phase 6: CI/CD Fixes

- [ ] **T-017**: Monitorear CI despues del merge
- [ ] **T-018**: Fix paths rotos en workflows si los hay
- [ ] **T-019**: Verificar que Docker builds en CI funcionan

**Definition of Done Sprint 1**:
- [ ] Las 4 apps levantan localmente con Docker Compose
- [ ] Toolkit CLI funciona para operaciones basicas
- [ ] `poetry run mypy toolkit/` pasa (o issues documentados)
- [ ] Al menos 1 smoke test en tests/
- [ ] CI pasa en master

---

## Fase 2: Produccion y Staging (Semanas 4-8)

### Sprint 2: Produccion VPS [P1]

> **Bloqueado por**: Sprint 1 (apps funcionan localmente)
> **Duracion**: 1 semana
> **Razon de ir primero**: VPS ya existe (162.55.57.175), Ansible playbooks ya generados.
> Desplegar a prod con lo que ya funciona es mas rapido que montar homelab desde cero.

**Arquitectura**:

```
                         INTERNET
                            |
              ┌─────────────▼─────────────┐
              │      VPS HETZNER          │
              │  162.55.57.175            │
              │                           │
              │  Traefik (edge + TLS)     │
              │  Web    → web.mlorente.dev│
              │  Blog   → blog...        │
              │  Wiki   → wiki...        │
              │  API    → api...         │
              │  Uptime → uptime...      │
              │                           │
              │  WireGuard Hub (futuro)   │
              └───────────────────────────┘
```

#### TICKET-009: Despliegue VPS

- [ ] **PROD-001**: Verificar acceso SSH al VPS
  ```bash
  ssh mlorente-deployer@162.55.57.175 "hostname && docker --version"
  ```

- [ ] **PROD-002**: Verificar/corregir Terraform DNS
  - Fix `services.json` placeholder → generar desde `common.yaml`
  ```bash
  ENVIRONMENT=prod poetry run toolkit config generate
  ENVIRONMENT=prod poetry run toolkit infra terraform plan
  ```

- [ ] **PROD-003**: Deploy con Ansible
  ```bash
  ENVIRONMENT=prod poetry run toolkit infra ansible deploy
  ```
  O manualmente:
  ```bash
  cd infra/ansible/generated/prod
  ansible-playbook -i hosts.yml playbooks/main.yml
  ```

- [ ] **PROD-004**: Verificar Traefik + TLS
  ```bash
  curl -I https://mlorente.dev  # debe retornar 200 con cert valido
  curl -I https://api.mlorente.dev/health
  ```

- [ ] **PROD-005**: Verificar cada app
  - `https://mlorente.dev` (web)
  - `https://blog.mlorente.dev` (blog)
  - `https://wiki.mlorente.dev` (wiki)
  - `https://api.mlorente.dev` (API)

- [ ] **PROD-006**: Configurar monitoring basico
  - Uptime Kuma con checks para cada app
  - Loki recibiendo logs de todos los containers

**Definition of Done Sprint 2**:
- [ ] 4 apps accesibles publicamente con TLS valido
- [ ] Uptime Kuma monitoreando endpoints
- [ ] Logs centralizados en Loki

---

### Sprint 3: Homelab Staging [P1]

> **Bloqueado por**: Sprint 2 (prod funcionando = safety net)
> **Duracion**: 1-2 semanas

#### TICKET-006: VPS WireGuard Hub

- [ ] **WG-001**: Instalar WireGuard en VPS
- [ ] **WG-002**: Configurar como hub (AllowedIPs para homelab + road warriors)
- [ ] **WG-003**: Generar keys para: homelab, laptop, movil
- [ ] **WG-004**: Abrir puerto UDP en firewall VPS
- [ ] **WG-005**: Testear conexion desde laptop

#### TICKET-007: Proxmox Setup

- [ ] **PVE-001**: Documentar IP y recursos del Mini PC #1
- [ ] **PVE-002**: Instalar Proxmox VE
- [ ] **PVE-003**: Configurar USB 128GB como storage
  ```bash
  mkfs.ext4 /dev/sda1
  mkdir -p /mnt/staging-data
  mount /dev/sda1 /mnt/staging-data
  echo "/dev/sda1 /mnt/staging-data ext4 defaults,nofail 0 2" >> /etc/fstab
  ```
- [ ] **PVE-004**: Crear LXC: wg-gateway (Alpine, 256MB) - cliente WireGuard
- [ ] **PVE-005**: Crear VM: staging-node (Ubuntu 22.04, 4GB RAM, 50GB)
- [ ] **PVE-006**: Bind mount `/mnt/staging-data` en VM staging
- [ ] **PVE-007**: Establecer tunel WireGuard persistente al VPS
- [ ] **PVE-008**: Verificar ping VPS ↔ Homelab

#### Deploy Staging

- [ ] **STG-001**: Clonar repo en VM staging
- [ ] **STG-002**: Configurar .env.staging (SOPS decrypt)
- [ ] **STG-003**: `ENVIRONMENT=staging poetry run toolkit config generate`
- [ ] **STG-004**: `ENVIRONMENT=staging poetry run toolkit services up traefik`
- [ ] **STG-005**: Deploy apps en staging
- [ ] **STG-006**: Verificar acceso via WireGuard

#### Raspberry Pi

- [ ] **RPI-001**: Instalar Pi-hole en RPi #1
- [ ] **RPI-002**: Configurar DNS local para `*.staging.cubelab.cloud`

#### Acceso de Emergencia

> Si el tunel WireGuard cae (reboot, IP change, config rota), necesitas
> una via alternativa para llegar al Proxmox host sin acceso fisico.

**Evaluar alternativas** (elegir 1 primaria + 1 secundaria):

| Opcion | Tipo | Pros | Contras |
|--------|------|------|---------|
| **Tailscale** | Mesh VPN (WireGuard-based) | Zero-config, NAT traversal, ACLs, MagicDNS | Freemium (3 users free), control plane externo |
| **Netbird** | Mesh VPN (open-source) | Self-hostable, WireGuard-based, similar a Tailscale | Mas setup, menos maduro |
| **Headscale** | Tailscale server self-hosted | 100% open-source, compatible con clientes Tailscale | Requiere servidor publico (VPS), mas mantenimiento |
| **autossh** | Reverse SSH tunnel | Zero dependencies, funciona en cualquier sitio | Fragil, necesita monitoreo, un solo puerto |
| **Cloudflare Tunnel** | HTTP tunnel | Gratis, no abre puertos, acceso web | Solo HTTP/S, no SSH directo sin WARP |
| **ZeroTier** | Mesh VPN | Open-source, P2P, facil setup | Control plane centralizado (free tier), menos usado |

**Recomendacion**: Tailscale (primaria) + autossh (secundaria minimal)
- Tailscale: instalar en Proxmox host + laptop + movil. Siempre accesible.
- autossh: reverse tunnel SSH al VPS como ultimo recurso si todo falla.

**Tareas**:

- [ ] **EMG-001**: Evaluar y decidir solucion (Tailscale vs Headscale vs Netbird)
  - Si self-hosted importa: Headscale en VPS + clientes Tailscale
  - Si pragmatismo importa: Tailscale free tier (3 users, 100 devices)
- [ ] **EMG-002**: Instalar solucion elegida en Proxmox host
- [ ] **EMG-003**: Instalar en laptop y movil
- [ ] **EMG-004**: Configurar autossh reverse tunnel como backup
  ```bash
  # En Proxmox host (crontab o systemd service):
  autossh -M 0 -f -N -R 2222:localhost:22 mlorente-deployer@162.55.57.175
  # Acceso de emergencia desde cualquier sitio:
  ssh -p 2222 root@162.55.57.175
  ```
- [ ] **EMG-005**: Documentar procedimientos en `docs/EMERGENCY-ACCESS.md`
  - Escenario 1: WireGuard caido → usar Tailscale/mesh
  - Escenario 2: Tailscale caido → usar autossh via VPS
  - Escenario 3: VPS caido → acceso fisico (documentar localizacion)
  - Contactos y credenciales (referencia a SOPS secrets)
- [ ] **EMG-006**: Test de failover: desactivar WireGuard, verificar acceso por via alternativa

**Definition of Done Sprint 3**:
- [ ] VPS con WireGuard Hub funcionando
- [ ] Proxmox con VM Staging funcionando
- [ ] Tunel site-to-site estable
- [ ] Apps staging accesibles via VPN
- [ ] Pi-hole con DNS local
- [ ] Acceso de emergencia probado (failover test)

---

### Sprint 4: Persistence + Observability [P2]

> **Bloqueado por**: Sprint 3 (staging funcional)
> **Duracion**: 1-2 semanas
> **Nota**: Solo implementar cuando una app lo necesite. Si ninguna app necesita BD, diferir.

#### TICKET-008: Persistence Layer (cuando sea necesario)

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ PostgreSQL  │  │   MinIO     │  │   Redis     │
│   :5432     │  │   :9000     │  │   :6379     │
│             │  │             │  │             │
│ Schemas:    │  │ Buckets:    │  │ Uses:       │
│ - auth      │  │ - uploads   │  │ - Cache     │
│ - app       │  │ - reports   │  │ - Celery    │
│ - workers   │  │ - assets    │  │ - Sessions  │
└─────────────┘  └─────────────┘  └─────────────┘
```

- [ ] **DATA-001**: Deploy PostgreSQL 16 en staging
- [ ] **DATA-002**: Crear schemas con aislamiento
- [ ] **DATA-003**: Deploy Redis 7 (para Celery workers)
- [ ] **DATA-004**: Deploy MinIO (si se necesita object storage)
- [ ] **DATA-005**: Configurar pg_dump daily backup
- [ ] **DATA-006**: Test backup/restore cycle
- [ ] **DATA-007**: Replicar en produccion

#### Observability (Docker Compose, no K3s)

- [ ] **OBS-001**: Grafana funcionando en staging + prod
- [ ] **OBS-002**: Loki recibiendo logs de todos los containers
- [ ] **OBS-003**: Crear 5 dashboards basicos:
  - Container health
  - Request rates por app
  - Error rates
  - Resource usage
  - Uptime history
- [ ] **OBS-004**: Alertas basicas (container down, high error rate)

**Definition of Done Sprint 4**:
- [ ] Persistence layer operativo (si necesario)
- [ ] Grafana con 5+ dashboards
- [ ] Alertas configuradas
- [ ] Backups validados

---

## Backlog (P3 - Sin Priorizar)

> Items aqui no tienen sprint asignado. Se priorizan cuando hay capacidad
> o cuando se convierten en prerequisito de algo activo.

### Tier 1: Probable (proximos 3 meses)

- [ ] **Workers deployment**: Crear compose files en `infra/stacks/apps/workers/`
- [ ] **Workers Phase 2**: Media processing (FFmpeg audio, WebP compression)
- [ ] **Test coverage**: Alcanzar 30%+ en toolkit core modules
- [ ] **Terraform DNS**: Generar `services.json` automaticamente desde `common.yaml`
- [ ] **Consolidar youtube-toolkit**: Migrar `youtube-toolkit` → `apps/workers/youtube/`
- [ ] **SOPS alignment**: Alinear con age keys de dotfiles

### Tier 2: Posible (3-6 meses)

- [ ] **ClawdBot**: Telegram bot (estructura, framework, approval workflow)
- [ ] **K3s Learning Lab**: Instalar K3s en Proxmox, aprender basics
- [ ] **ArgoCD**: GitOps para staging environment
- [ ] **Authelia expand**: Proteger mas servicios con OIDC
- [ ] **Workers Phase 3**: AI & Intelligence (embeddings, RAG, summarization)

### Tier 3: Ideas (6+ meses, sin compromiso)

- [ ] GitHub Organization migration (hub-and-spoke architecture)
- [ ] K3s multi-arch cluster con RPi #2
- [ ] Helm charts para todas las apps
- [ ] Workers Phase 4-5 (data aggregator, system maintenance)
- [ ] Newsletter (Cubernautas) setup

---

## Metricas de Exito

| Metrica | Sprint 1 | Sprint 2 | Sprint 4 |
|---------|----------|----------|----------|
| Apps en prod | 0 | 4 | 4+ |
| Toolkit CLI funcional | si | si | si |
| Test coverage | >0% | 10%+ | 30%+ |
| Grafana dashboards | 0 | 1 | 5+ |
| Staging mirror | no | no | si |
| Uptime monitoring | no | si | si |

---

## Best Practices Reference

### Compose File Pattern

```bash
# Nuevo patron (post-migracion):
docker compose -f compose.base.yml -f compose.dev.yml up -d

# compose.base.yml: imagen, healthcheck, networks, volumes compartidos
# compose.dev.yml: hot reload, debug, ports locales
# compose.staging.yml: mirrors prod, recursos limitados
# compose.prod.yml: resource limits, logging, replicas
```

### Service Categories

| Category | Purpose | Services |
|----------|---------|----------|
| **core** | Essential platform | gitea, portainer, n8n, vaultwarden |
| **observability** | Monitoring/logging | grafana, loki, uptime |
| **security** | Auth/protection | authelia, crowdsec |
| **data** | Storage/docs | minio, docmost |
| **automation** | CI/workflows | github-runner, kestra |
| **ai** | ML/AI | ollama, webui |
| **misc** | Productivity | calcom, immich |

### Environment Strategy

```
dev      → Local (hot reload, debug, mkcert certs)
staging  → CubeLab homelab (mirrors prod, WireGuard access)
prod     → Hetzner VPS (public, Let's Encrypt TLS)
```

### CLI Command Reference (Actual)

```bash
toolkit services up <name>       # Levantar app o servicio
toolkit services down <name>     # Parar
toolkit services logs <name>     # Ver logs
toolkit services list            # Listar disponibles
toolkit config generate          # Generar configs desde templates
toolkit config validate          # Validar configs
toolkit credentials generate     # Generar credenciales
toolkit infra ansible deploy     # Deploy con Ansible
toolkit infra terraform plan     # Terraform plan
toolkit deployment deploy        # Deployment completo
toolkit dashboard                # Terminal dashboard
toolkit tools certs generate     # Generar certs locales
```

---

## Notas

- **Prioridad absoluta**: Sprint 0 (fix code + align docs + commit)
- **No overengineer**: Resolver lo que hay antes de anadir complejidad
- **K3s es futuro**: No iniciar hasta tener Docker Compose 100% estable en prod + staging
- **Lessons learned**: Actualizar `tasks/lessons.md` despues de cada sprint

---

## Completado

### 2026-02-05
- [x] Audit completo del proyecto (estructura, toolkit, CI/CD, docs, infra)
- [x] Identificar 10 bugs de codigo no contemplados en plan anterior
- [x] Replanificar roadmap con enfoque en codigo primero

### 2026-02-04
- [x] Merge BACKLOG.md y todo.md en archivo unico
- [x] Definir arquitectura de hardware (VPS + Proxmox + RPis)
- [x] Refinar arquitectura hibrida (VPS WireGuard Hub)

### 2026-02-03
- [x] Analisis profundo del proyecto
- [x] Crear plan de ejecucion de 6 meses
- [x] Definir estrategia de estabilizacion

### Feature Branch (Pre-commit)
- [x] Reorganizar infraestructura a `infra/stacks/`
- [x] Traducir blog a espanol
- [x] Anadir fuentes Roboto al blog
- [x] Consolidar edge services
- [x] Anadir soporte staging environment
- [x] Anadir nuevos servicios (Gitea, Authelia, CrowdSec, etc.)
- [x] Crear estructura Workers app
- [x] Workers Phase 1: YouTube toolkit
- [x] CLI Architecture Audit

---

*Ultima actualizacion: 2026-02-05*
*Proxima revision: Despues de Sprint 0*
