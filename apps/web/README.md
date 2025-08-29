# Mi Web Personal con Astro

<div align="center">

![Astro](https://img.shields.io/badge/Astro-5.5.2-FF5D01?style=flat&logo=astro&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white)
![Tailwind](https://img.shields.io/badge/Tailwind-06B6D4?style=flat&logo=tailwind-css&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)

</div>

Esta es mi web personal donde tengo mi portafolio, algunos recursos descargables y toda la información sobre lo que hago. La he hecho con Astro porque me gusta cómo maneja el SSR y lo rápida que es.

## 🤔 Por qué elegí estas tecnologías

- **Astro 5.5.2** - Es súper rápido y me permite mezclar SSR y SSG como quiero. Además no se carga de JavaScript innecesario
- **TypeScript** - Porque los tipos me ahorran dolores de cabeza. Me gusta poder refactorizar con confianza
- **Tailwind CSS** - Una vez que te acostumbras, no hay vuelta atrás. Prototipo súper rápido
- **MDX** - Para crear contenido dinámico mezclando markdown con componentes. Muy cómodo para el portafolio

## 📁 Cómo está organizado todo

```
astro-site/
├── astro.config.mjs          # Configuración principal de Astro
├── package.json              # Las dependencias de siempre
├── tailwind.config.mjs       # Mis colores y configuración custom
├── public/                   # Cosas estáticas (favicon, imágenes, etc.)
├── src/
│   ├── components/           # Componentes reutilizables
│   │   ├── forms/           # Formularios de contacto y suscripción
│   │   ├── sections/        # Secciones grandes de las páginas
│   │   └── ui/             # Botones, cards, etc.
│   ├── content/            # Contenido en MDX
│   │   ├── projects/       # Mis proyectos del portafolio
│   │   └── resources/      # Recursos descargables
│   ├── layouts/            # Plantillas de página
│   ├── pages/              # Las rutas de la web
│   └── styles/             # Estilos globales
└── Dockerfile              # Para containerizar todo
```

## 🚀 Lo que hace especial mi web

### Para los visitantes

- **Carga súper rápida** - Gracias a Astro y su hidratación parcial
- **Portfolio interactivo** - Proyectos con imágenes, demos y enlaces a GitHub
- **Recursos descargables** - Lead magnets como checklists de DevOps (con formulario integrado)
- **Newsletter** - Formularios conectados a mi API para suscripciones
- **Responsive** - Se ve bien en móvil, tablet y desktop

### Para mí como desarrollador

- **TypeScript en todo** - Menos bugs, más tranquilidad
- **Colecciones de contenido** - Los proyectos y recursos están tipados y validados
- **Componentes de Astro** - Arquitectura moderna sin complicaciones
- **Optimización automática** - Compresión de imágenes y formatos múltiples
- **Caché inteligente** - Los recursos estáticos se cachean bien

## 🔧 Variables de entorno

```bash
# Configuración del servidor
PORT=4321
HOST=0.0.0.0
NODE_ENV=production

# Mi API para formularios
API_BASE_URL=https://api.mlorente.dev
API_TIMEOUT=5000

# Características que uso
ENABLE_ANALYTICS=true
ENABLE_NEWSLETTER=true
```

## 🐳 Cómo lo ejecuto

### En desarrollo

```bash
# Lo arranco con hot reload
docker-compose -f docker-compose.dev.yml up --build

# Y lo veo en http://localhost:4321
```

### En producción

```bash
# Despliegue completo
docker-compose -f docker-compose.prod.yml up -d

# Ver los logs
docker logs -f web
```

## 🛠️ Desarrollo local

```bash
# Me voy al directorio
cd apps/web/astro-site

# Instalo dependencias
npm install

# Configuro las variables (copio el ejemplo)
cp .env.example .env

# Y arranco el servidor de desarrollo
npm run dev

# Se abre en http://localhost:4321
```

### Comandos que uso a menudo

```bash
# Desarrollo con hot reload
npm run dev

# Build para producción
npm run build

# Vista previa del build
npm run preview

# Verificar tipos
npm run type-check

# Linting y formateo
npm run lint
npm run format
```

## ✍️ Cómo añado contenido

### Nuevo proyecto del portafolio

```markdown
---
title: "Mi Nuevo Proyecto"
description: "Una descripción corta pero que venda"
technologies: ["Astro", "TypeScript", "Tailwind"]
github: "https://github.com/mlorentedev/proyecto"
demo: "https://proyecto.mlorente.dev"
image: "/images/proyectos/proyecto.jpg"
featured: true  # Para que aparezca en featured
date: 2024-01-15
---

## De qué va el proyecto

Aquí explico qué hace, por qué lo hice y cómo está hecho...

### Lo que más me gusta del proyecto

- Característica 1
- Característica 2  
- Característica 3

### Los retos técnicos que tuve

Siempre hay algún problema que resolver...
```

### Nuevo recurso descargable

```markdown
---
title: "Mi Checklist de DevOps"
description: "Todo lo que necesitas revisar antes de un despliegue"
category: "DevOps"
fileType: "PDF"
fileSize: "2.3 MB"
downloadCount: 0
tags: ["devops", "checklist", "automation"]
featured: true
gated: true  # Requiere email para descargar
---

Descripción de lo que se van a descargar y por qué les va a ser útil...
```

## 🎨 Mi sistema de diseño

Uso Tailwind con algunas personalizaciones que me gustan:

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

### Componentes que reutilizo

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

## 📊 Analytics y seguimiento

Me gusta saber qué pasa en mi web, así que tengo:

- **Google Analytics** - Para ver el tráfico y comportamiento
- **Seguimiento de formularios** - Para saber qué recursos se descargan más
- **Métricas de conversión** - Newsletter y lead magnets
- **Core Web Vitals** - Para asegurarme de que va rápida

## 🔒 Seguridad

No es paranoia, es precaución:

- **Validación en servidor** - Los formularios se validan también en la API
- **Headers de seguridad** - CSP, HSTS y compañía
- **Rate limiting** - Para evitar spam en los formularios
- **Sanitización** - Todo lo que viene del usuario se limpia

## 🚀 SEO que funciona

- **Meta tags dinámicos** - Cada página tiene su título y descripción únicos
- **Datos estructurados** - JSON-LD para que Google me entienda mejor
- **Sitemap automático** - Se genera solo cuando hago build
- **URLs canónicas** - Sin contenido duplicado
- **Alt text en imágenes** - Accesibilidad y SEO

## 🔗 Integración con mi API

Los formularios se conectan con mi API de Go:

```typescript
// Suscripción al newsletter
POST /api/subscribe
{
  "email": "usuario@ejemplo.com",
  "tags": ["newsletter", "web"]
}

// Descargar recursos
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
  "message": "El mensaje"
}
```

## 🤝 Si quieres contribuir

1. Fork del repo
2. Haz tus cambios siguiendo las convenciones de TypeScript/Astro
3. Pruébalo todo localmente
4. Actualiza la documentación si añades algo nuevo
5. Asegúrate de que el build de Docker funciona
6. Envía el PR

## 📦 Las dependencias principales

### Framework y core

- **@astrojs/node** - Para el servidor Node.js
- **astro** - El framework que mola
- **typescript** - Para no volverme loco con los tipos

### Estilos y UI

- **@astrojs/tailwind** - Integración con Tailwind
- **tailwindcss** - El CSS utility-first que me encanta

### Contenido

- **@astrojs/mdx** - Para el contenido dinámico
- **zod** - Validación de esquemas que funciona de verdad

---

Esta web es el escaparate de lo que hago y me gusta tenerla siempre actualizada y funcionando bien. Si tienes preguntas o sugerencias, no dudes en escribirme.