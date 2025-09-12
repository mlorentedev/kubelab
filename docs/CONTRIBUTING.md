# Workflow and Development Guidelines

Although the documentation of this project is in Spanish, code and commit messages should be written in English to maintain consistency and facilitate international collaboration.

## Branch Naming Conventions

`master`: Stable code for production  
`develop`: Active development and integration  
`feature/*`: Feature branches for new functionality  
`hotfix/*`: Urgent fix branches  

**Ejemplos:**

```bash
# Feature branch example
git checkout -b feature/add-user-authentication

# Hotfix branch example
git checkout -b hotfix/log-in-bug
```

## Commit Messages According to Conventional Commits

Follow the [Conventional Commits](https://www.conventionalcommits.org/) standard to keep the commit history clear and consistent:

**Format:** `<type>(<optional scope>): <description>`

**Allowed Types:**

- `feat` → New feature  
- `fix` → Bug fix  
- `docs` → Documentation update  
- `style` → Code style changes (formatting, no logic changes)  
- `refactor` → Code restructuring without changing behavior  
- `test` → Add or improve tests  
- `chore` → Maintenance tasks (e.g., dependency updates)  

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

## Versioning and Version Management

The project follows Semantic Versioning through commit messages:

- **Major Version** increments with incompatible changes:
  - Messages containing "BREAKING CHANGE:" or "!:"
  - Example: `feat!: description of incompatible change`
- **Minor Version** increments with new features:
  - Messages starting with `feat:`  
  - Example: `feat: assemble new search functionality`
- **Patch Version** increments with fixes/small changes:  
  - Messages starting with `fix:`, `docs:`, `chore:`, `style:`, etc.
  - Example: `fix: solve error in contact form`

You can force a specific increment using `#major`, `#minor`, or `#patch` in the commit message body.

### Pull Request Process

1. Create a feature branch from `develop`
2. Make your changes
3. Write tests for your changes
4. Ensure all tests pass
5. Commit with conventional commit messages
6. Push your branch and open a Pull Request to `develop`
7. Request a code review
8. After approval, merge with `develop`

### What to Avoid

- Vague branch names
- Mixing unrelated changes
- Ignoring failed tests
- Force pushing to `master`

## Coding Guidelines

### Project Structure

When adding new features, follow the existing structure:

```text
apps/
├── api/           # API en Go
│   ├── src/       # Código fuente
│   └── Dockerfile
├── blog/          # Sitio Jekyll
│   ├── jekyll-site/
│   └── Dockerfile
└── web/           # Frontend Astro
    ├── astro-site/
    └── Dockerfile
```

### Convenciones de Código

#### Para Go (API)

```go
// Usar nombres descriptivos
func GetUserByID(id string) (*User, error) {
    // Implementación
}

// Manejar errores apropiadamente
if err != nil {
    return nil, fmt.Errorf("failed to get user: %w", err)
}

// Usar comentarios para funciones públicas
// GetUsers retrieves all users from the database
func GetUsers() ([]User, error) {
    // Implementación
}
```

#### Para JavaScript/TypeScript (Web)

```javascript
// Usar const/let apropiadamente
const API_BASE_URL = 'https://api.mlorente.dev';

// Funciones con nombres descriptivos
const fetchUserData = async (userId) => {
  try {
    const response = await fetch(`${API_BASE_URL}/users/${userId}`);
    return await response.json();
  } catch (error) {
    console.error('Error fetching user:', error);
    throw error;
  }
};

// Usar destructuring cuando sea apropiado
const { name, email } = user;
```

#### Para Ruby (Blog Jekyll)

```ruby
# Usar snake_case para variables y métodos
def format_post_date(date)
  date.strftime('%d de %B de %Y')
end

# Comentarios claros para lógica compleja
# Procesa el contenido del post y aplica filtros
def process_content(content)
  # Implementación
end
```

### Docker y Contenedores

#### Mejores Prácticas para Dockerfile

```dockerfile
# Usar imagen base específica
FROM node:20-alpine

# Crear usuario no-root
RUN addgroup -g 1001 -S nodejs
RUN adduser -S nextjs -u 1001

# Optimizar capas de cache
COPY package*.json ./
RUN npm ci --only=production

# Copiar código fuente al final
COPY --chown=nextjs:nodejs . .

USER nextjs
```

#### Docker Compose

```yaml
services:
  app:
    build: .
    environment:
      - NODE_ENV=development
    volumes:
      - .:/app
    ports:
      - "3000:3000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### Documentación

#### README de Aplicaciones

Cada aplicación debe tener su propio README con:

```markdown
# Nombre de la Aplicación

## Descripción
Breve descripción de lo que hace la aplicación.

## Desarrollo Local
```bash
# Pasos para ejecutar localmente
make up-app
```

## Configuración
Variables de entorno requeridas:
- `PORT`: Puerto donde correr la aplicación
- `DATABASE_URL`: URL de la base de datos

## Pruebas
```bash
# Ejecutar pruebas
npm test
```
```

#### Comentarios en Código

```go
// Package auth provides authentication and authorization utilities.
package auth

// User represents a user in the system.
type User struct {
    ID    string `json:"id"`
    Email string `json:"email"`
    Name  string `json:"name"`
}

// Authenticate verifies user credentials and returns a JWT token.
// Returns an error if credentials are invalid.
func Authenticate(email, password string) (string, error) {
    // Implementación
}
```

### Pruebas

#### Estructura de Pruebas

```text
apps/api/
├── src/
│   ├── handlers/
│   │   ├── users.go
│   │   └── users_test.go
│   └── models/
│       ├── user.go
│       └── user_test.go
└── tests/
    ├── integration/
    └── e2e/
```

#### Ejemplos de Pruebas

**Go (API):**

```go
func TestGetUser(t *testing.T) {
    // Arrange
    userID := "test-user-123"
    expectedUser := &User{ID: userID, Name: "Test User"}
    
    // Act
    result, err := GetUserByID(userID)
    
    // Assert
    assert.NoError(t, err)
    assert.Equal(t, expectedUser.ID, result.ID)
    assert.Equal(t, expectedUser.Name, result.Name)
}
```

**JavaScript (Web):**

```javascript
describe('User API', () => {
  test('should fetch user data successfully', async () => {
    // Arrange
    const userId = '123';
    const mockUser = { id: userId, name: 'Test User' };
    
    // Act
    const result = await fetchUserData(userId);
    
    // Assert
    expect(result).toEqual(mockUser);
  });
});
```

### CI/CD y Despliegue

#### Variables de Entorno

Usa archivos `.env.example` para documentar variables:

```bash
# .env.example
PORT=3000
DATABASE_URL=postgres://localhost:5432/myapp
JWT_SECRET=your-secret-here
API_KEY=your-api-key
```

#### GitHub Actions

Al modificar workflows, asegúrate de:

1. Validar YAML localmente
2. Probar cambios en rama feature primero
3. Documentar cambios en commit message
4. Seguir patrones existentes

```yaml
# Ejemplo de step en workflow
- name: Run tests
  run: |
    cd apps/api
    go test ./...
```

### Seguridad

#### Secretos

```bash
# ❌ NUNCA hacer esto
const API_KEY = "sk-1234567890abcdef";

# ✅ Usar variables de entorno
const API_KEY = process.env.API_KEY;
```

#### Validación de Entrada

```go
// Validar entrada de usuario
func ValidateEmail(email string) error {
    if len(email) == 0 {
        return errors.New("email is required")
    }
    
    if !strings.Contains(email, "@") {
        return errors.New("invalid email format")
    }
    
    return nil
}
```

### Herramientas de Desarrollo

#### Linting y Formateo

**Go:**
```bash
# Formatear código
go fmt ./...

# Ejecutar linter
golangci-lint run
```

**JavaScript/TypeScript:**
```bash
# Formatear con Prettier
npm run format

# Ejecutar ESLint
npm run lint
```

**Ruby:**
```bash
# Formatear con RuboCop
bundle exec rubocop --auto-correct
```

#### Git Hooks

Usar pre-commit hooks para mantener calidad:

```bash
#!/bin/sh
# .git/hooks/pre-commit

# Ejecutar linting
make lint

# Ejecutar pruebas
make test

# Verificar conventional commits
npx commitlint --edit $1
```

### Debugging y Logging

#### Niveles de Log

```go
// Usar niveles apropiados
log.Debug("User attempting login", "email", email)
log.Info("User logged in successfully", "userID", userID)
log.Warn("Failed login attempt", "email", email, "attempts", attempts)
log.Error("Database connection failed", "error", err)
```

#### Debugging Local

```bash
# Variables de debugging
DEBUG=app:* npm start

# Logs detallados
LOG_LEVEL=debug make up
```

## Proceso de Release

### Preparación

1. Crear rama `release/vX.Y.Z` desde `develop`
2. Actualizar versiones y changelogs
3. Ejecutar pruebas completas
4. Crear PR a `master`

### Release Notes

```markdown
## v1.2.0 - 2025-01-23

### ✨ Nuevas Características
- feat(auth): añadido sistema de autenticación OAuth2
- feat(api): endpoint para gestión de usuarios

### 🐛 Correcciones
- fix(web): solucionado problema de carga en Safari
- fix(blog): corregidos enlaces rotos en posts

### 📚 Documentación
- docs: actualizada guía de instalación
- docs: añadidos ejemplos de API
```

### Post-Release

1. Fusionar cambios de vuelta a `develop`
2. Crear tags anotados
3. Actualizar documentación
4. Anunciar release si es necesario

## Recursos Adicionales

### Herramientas Recomendadas

- **IDE:** VS Code con extensiones Go, TypeScript, Docker
- **Git GUI:** SourceTree, GitKraken, o interfaz de VS Code
- **API Testing:** Postman, Insomnia, o Thunder Client
- **Docker:** Docker Desktop con BuildKit habilitado

### Documentación Técnica

- [Conventional Commits](https://www.conventionalcommits.org/)
- [Semantic Versioning](https://semver.org/)
- [Go Code Review Guidelines](https://github.com/golang/go/wiki/CodeReviewComments)
- [JavaScript Style Guide](https://github.com/airbnb/javascript)

### Contacto

Para preguntas sobre desarrollo o contribuciones:

1. Abrir issue en GitHub para discusión
2. Revisar documentación existente en `docs/`
3. Consultar con el equipo en PR reviews

---

*Gracias por contribuir al proyecto mlorente.dev. Tu atención a estas directrices ayuda a mantener la calidad y consistencia del código.*