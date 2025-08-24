# Sitio Web Personal

<div align="center">

![Astro](https://img.shields.io/badge/Astro-5.5.2-FF5D01?style=flat&logo=astro&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white)
![Tailwind](https://img.shields.io/badge/Tailwind-06B6D4?style=flat&logo=tailwind-css&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)

</div>

Sitio web personal moderno y responsivo construido con framework Astro, presentando proyectos de portafolio, recursos e información profesional para mlorente.dev.

## 🏗️ Arquitectura

- **Framework**: Astro 5.5.2 con SSR (Renderizado del Lado del Servidor)
- **Estilos**: Tailwind CSS con sistema de diseño personalizado
- **Runtime**: Node.js con adaptador independiente
- **Contenido**: MDX con colecciones TypeScript
- **Despliegue**: Docker contenedorizado con builds multi-etapa

## 📁 Estructura del Proyecto

```
astro-site/
├── astro.config.mjs          # Configuración de Astro con SSR
├── package.json              # Dependencias y scripts
├── tailwind.config.mjs       # Configuración de Tailwind
├── tsconfig.json            # Configuración de TypeScript
├── public/                   # Recursos estáticos
│   ├── favicon.ico          # Favicon del sitio
│   ├── images/              # Imágenes públicas
│   ├── fonts/               # Archivos de fuentes web
│   └── robots.txt           # Directrices para motores de búsqueda
├── src/                     # Código fuente
│   ├── components/          # Componentes reutilizables
│   │   ├── forms/          # Componentes de formularios
│   │   ├── sections/       # Secciones de página
│   │   ├── meta/           # Componentes meta/SEO
│   │   └── ui/             # Componentes de interfaz
│   ├── content/            # Contenido en MDX
│   │   ├── projects/       # Proyectos de portafolio
│   │   ├── resources/      # Recursos descargables
│   │   └── config.ts       # Configuración de colecciones
│   ├── layouts/            # Plantillas de página
│   ├── pages/              # Rutas de página
│   ├── styles/             # Estilos globales
│   ├── data/               # Configuración y datos
│   └── types/              # Definiciones de tipos TypeScript
├── Dockerfile               # Configuración del contenedor
└── docker-compose.*.yml     # Configuraciones de Docker Compose
```

## 🚀 Características

### Características del Sitio Web
- **Renderizado Híbrido**: SSG + SSR para rendimiento óptimo
- **Portfolio Interactivo**: Proyectos con imágenes y demostraciones
- **Recursos Descargables**: Lead magnets con integración de formularios
- **Integración de Newsletter**: Formularios de suscripción conectados a API
- **Página de Contacto**: Múltiples métodos de contacto y formularios

### Características Técnicas
- **TypeScript**: Tipado completo para mejor experiencia de desarrollo
- **Colecciones de Contenido**: Contenido estructurado con validación de esquemas
- **Componentes de Astro**: Arquitectura de componentes moderna
- **Optimización de Imágenes**: Compresión y formatos múltiples automáticos
- **Caché Inteligente**: Estrategias de caché optimizadas

### Características de Rendimiento
- **Hidratación Parcial**: JavaScript mínimo del lado del cliente
- **Optimización de Activos**: Minificación y compresión automática
- **Carga Diferida**: Imágenes y componentes cargados bajo demanda
- **Web Vitals**: Optimizado para métricas Core Web Vitals
- **Prefetch de Vínculos**: Navegación más rápida

## 🔧 Configuración

### Configuración de Astro (`astro.config.mjs`)

```javascript
export default defineConfig({
  output: 'hybrid',
  adapter: node({
    mode: 'standalone'
  }),
  integrations: [
    tailwind(),
    mdx(),
    sitemap()
  ],
  image: {
    domains: ['mlorente.dev']
  }
});
```

### Variables de Entorno

```bash
# Configuración del servidor
PORT=4321
HOST=0.0.0.0
NODE_ENV=production

# Integración de API
API_BASE_URL=https://api.mlorente.dev
API_TIMEOUT=5000

# Configuración de funciones
ENABLE_ANALYTICS=true
ENABLE_NEWSLETTER=true
```

## 🐳 Despliegue con Docker

### Desarrollo
```bash
# Construir y ejecutar con recarga en vivo
docker-compose -f docker-compose.dev.yml up --build

# Acceder en http://localhost:4321
```

### Producción
```bash
# Desplegar con configuración de producción
docker-compose -f docker-compose.prod.yml up -d

# Monitorear contenedor
docker logs -f web
```

## 🛠️ Desarrollo Local

### Prerrequisitos
- Node.js 18+ y npm/pnpm
- Docker y Docker Compose (opcional)
- Make (opcional, para comandos de conveniencia)

### Configuración
```bash
# Navegar al directorio del sitio Astro
cd apps/web/astro-site

# Instalar dependencias
npm install

# Copiar archivo de entorno
cp .env.example .env
# Editar .env con tu configuración

# Ejecutar servidor de desarrollo
npm run dev

# Acceder en http://localhost:4321
```

### Comandos de Desarrollo
```bash
# Servidor de desarrollo con recarga en vivo
npm run dev

# Construir para producción
npm run build

# Vista previa de construcción local
npm run preview

# Verificar tipos TypeScript
npm run type-check

# Linting y formateo
npm run lint
npm run format
```

## ✍️ Gestión de Contenido

### Crear Proyectos de Portfolio

Añadir nuevos proyectos en `src/content/projects/`:

```markdown
---
title: "Título del Proyecto"
description: "Descripción breve del proyecto"
technologies: ["Astro", "TypeScript", "Tailwind"]
github: "https://github.com/usuario/proyecto"
demo: "https://proyecto.ejemplo.com"
image: "/images/proyectos/proyecto.jpg"
featured: true
date: 2024-01-15
---

## Descripción del Proyecto

Contenido detallado del proyecto aquí...

### Características Clave
- Característica 1
- Característica 2
- Característica 3

### Desafíos Técnicos
Descripción de desafíos y soluciones...
```

### Gestionar Recursos

Crear recursos descargables en `src/content/resources/`:

```markdown
---
title: "Lista de Verificación DevOps"
description: "Lista completa para implementaciones DevOps"
category: "DevOps"
fileType: "PDF"
fileSize: "2.3 MB"
downloadCount: 0
tags: ["devops", "checklist", "automation"]
featured: true
gated: true
---

Descripción del recurso y su valor...
```

## 🎨 Diseño y Estilos

### Sistema de Diseño Tailwind

```javascript
// tailwind.config.mjs
module.exports = {
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eff6ff',
          500: '#3b82f6',
          900: '#1e3a8a'
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif']
      }
    }
  }
}
```

### Componentes Personalizados
```astro
---
// src/components/ui/Button.astro
interface Props {
  variant?: 'primary' | 'secondary';
  size?: 'sm' | 'md' | 'lg';
}

const { variant = 'primary', size = 'md' } = Astro.props;
---

<button 
  class:list={[
    'font-semibold rounded-lg transition-colors',
    {
      'bg-primary-500 text-white hover:bg-primary-600': variant === 'primary',
      'bg-gray-200 text-gray-900 hover:bg-gray-300': variant === 'secondary',
      'px-3 py-2 text-sm': size === 'sm',
      'px-4 py-2': size === 'md',
      'px-6 py-3 text-lg': size === 'lg'
    }
  ]}
>
  <slot />
</button>
```

## 📊 Analíticas y Seguimiento

### Integración de Google Analytics
- Seguimiento de páginas vistas
- Seguimiento de eventos de formularios
- Seguimiento de descargas de recursos
- Métricas de conversión

### Métricas de Rendimiento
- Core Web Vitals
- Velocidad de carga de páginas
- Tasas de rebote
- Tiempo en página

## 🔒 Características de Seguridad

- **Validación de Formularios**: Validación del lado del servidor
- **Sanitización de Entrada**: Prevención de XSS
- **Headers de Seguridad**: CSP, HSTS, y otros headers
- **Rate Limiting**: Protección contra spam en formularios
- **Validación de Datos**: Esquemas de validación para contenido

## 🚀 Optimización SEO

### Características SEO Incorporadas
- **Meta Tags Dinámicos**: Títulos y descripciones por página
- **Datos Estructurados**: JSON-LD para contenido enriquecido
- **Sitemap XML**: Generación automática
- **Robots.txt**: Configuración de rastreo de motores
- **URLs Canónicas**: Prevención de contenido duplicado

### Optimización de Contenido
- **Títulos Descriptivos**: Optimizados para palabras clave
- **Meta Descripciones**: Atractivas y descriptivas
- **Alt Text de Imágenes**: Descripciones accesibles
- **Estructura de Encabezados**: Jerarquía H1-H6 apropiada
- **Enlaces Internos**: Navegación y distribución de autoridad

## 🔗 Integración de API

### Endpoints Utilizados
```typescript
// Suscripción al newsletter
POST /api/subscribe
{
  "email": "usuario@ejemplo.com",
  "tags": ["newsletter", "web"]
}

// Solicitar recursos
POST /api/lead-magnet
{
  "email": "usuario@ejemplo.com",
  "resource_id": "devops-checklist",
  "utm_source": "website"
}

// Formulario de contacto
POST /api/contact
{
  "name": "Nombre",
  "email": "email@ejemplo.com",
  "message": "Mensaje"
}
```

## 🤝 Contribuir

1. Seguir convenciones de código TypeScript/Astro
2. Probar cambios localmente antes de enviar
3. Actualizar documentación para nuevas características
4. Usar commits convencionales para changelog
5. Asegurar que las construcciones Docker sean exitosas
6. Verificar que las métricas Web Vitals se mantengan óptimas

## 📦 Dependencias Principales

### Framework y Core
- **@astrojs/node**: Adaptador de servidor Node.js
- **astro**: Framework de sitios web moderno
- **typescript**: Tipado estático

### Estilos y UI
- **@astrojs/tailwind**: Integración de Tailwind CSS
- **tailwindcss**: Framework CSS utility-first

### Contenido y Datos
- **@astrojs/mdx**: Soporte para MDX
- **zod**: Validación de esquemas TypeScript

## 🔗 Servicios Relacionados

- **Backend API**: `apps/api` - Manejo de formularios y suscripciones
- **Blog**: `apps/blog` - Blog técnico en Jekyll
- **Infraestructura**: `infra/` - Configuraciones de despliegue
- **Monitoreo**: `apps/monitoring` - Observabilidad y métricas