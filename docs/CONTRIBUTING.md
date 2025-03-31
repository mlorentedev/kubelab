# Flujo de Trabajo y Directrices de Desarrollo

Aunque la documentación de este proyecto se encuentra en español, el código y los mensajes de commit deben escribirse en inglés para mantener la consistencia y facilitar la colaboración internacional.

## Convenciones para Nombres de Ramas

`master`: Código estable para producción  
`develop`: Desarrollo activo e integración  
`feature/*`: Ramas de características para nueva funcionalidad  
`hotfix/*`: Ramas de corrección urgente  

**Ejemplos:**

```bash
# Ejemplo de rama de característica
git checkout -b feature/add-user-authentication

# Ejemplo de rama de corrección urgente
git checkout -b hotfix/log-in-bug
```

## Mensajes de Commit según Conventional Commits

Sigue el estándar [Conventional Commits](https://www.conventionalcommits.org/) para mantener el historial de commits claro y consistente:

**Formato:** `<tipo>(<ámbito opcional>): <descripción>`

**Tipos Permitidos:**

- `feat` → Nueva característica  
- `fix` → Corrección de error  
- `docs` → Actualización de documentación  
- `style` → Cambios de estilo de código (formato, sin cambios de lógica)  
- `refactor` → Reestructuración de código sin cambiar comportamiento  
- `test` → Añadir o mejorar pruebas  
- `chore` → Tareas de mantenimiento (ej. actualizaciones de dependencias)  

**Ejemplos:**

```bash
git commit -m "feat(auth): add user authentication"
git commit -m "fix(api): resolve issue with data retrieval"
git commit -m "docs(readme): update installation instructions"
git commit -m "style(button): format button styles for consistency"
git commit -m "refactor(user): simplify user model logic"
git commit -m "test(api): add unit tests for data retrieval"
git commit -m "chore(deps): update dependency express to v4.17.1"
```

## Versionado y Gestión de Versiones

El proyecto sigue el Versionado Semántico a través de mensajes de commit:

- **Versión Mayor** incrementa con cambios incompatibles:
  - Mensajes conteniendo "BREAKING CHANGE:" o "!:"
  - Ejemplo: `feat!: desription of incompatible change`
- **Versión Menor** incrementa con nuevas características:
  - Mensajes comenzando con `feat:`  
  - Ejemplo: `feat: assemble new search functionality`
- **Versión Parche** incrementa con correcciones/cambios pequeños:  
  - Mensajes comenzando con `fix:`, `docs:`, `chore:`, `style:`, etc.
  - Ejemplo: `fix: solve error in contact form`

Puedes forzar un incremento específico usando `#major`, `#minor`, o `#patch` en el cuerpo del mensaje de commit.

### Proceso de Pull Request

1. Crear una rama de característica desde `develop`
2. Realizar tus cambios
3. Escribir pruebas para tus cambios
4. Asegurar que todas las pruebas pasen
5. Hacer commit con mensajes según conventional commits
6. Enviar tu rama y abrir un Pull Request a `develop`
7. Solicitar una revisión de código
8. Después de la aprobación, fusionar con `develop`

### Qué Evitar

- Nombres de rama vagos
- Mezclar cambios no relacionados
- Ignorar pruebas fallidas
- Forzar push a `master`
