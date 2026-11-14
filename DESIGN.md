---
name: LaLiga Fantasy Quant
description: Panel móvil de decisiones de fantasy, negro profundo con un hero naranja brasa y cifras grandes y limpias.
colors:
  ink-black: "#02070a"
  surface-card: "#141414"
  surface-raised: "#1c1c1e"
  ember: "#ff7a3d"
  ember-soft: "#ff9a5a"
  peach: "#ffc08a"
  coral-alert: "#fc734d"
  mint-gain: "#34d399"
  sky-data: "#0297de"
  amber-warn: "#f5b544"
  text-primary: "#f0f6fc"
  text-muted: "#8b9eb0"
  text-faint: "#6f8499"
  line: "rgba(255, 255, 255, 0.07)"
typography:
  display:
    fontFamily: "Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "3.1rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.045em"
  title:
    fontFamily: "Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.03em"
  body:
    fontFamily: "Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "-0.011em"
  label:
    fontFamily: "Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.4
  figure:
    fontFamily: "JetBrains Mono, ui-monospace, Consolas, monospace"
    fontSize: "1rem"
    fontWeight: 600
    letterSpacing: "-0.04em"
rounded:
  sm: "0.75rem"
  md: "1.5rem"
  lg: "1.75rem"
  pill: "9999px"
spacing:
  sm: "0.75rem"
  md: "1.25rem"
  lg: "1.5rem"
components:
  card:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "1.25rem"
  button-primary:
    backgroundColor: "{colors.sky-data}"
    textColor: "{colors.ink-black}"
    rounded: "{rounded.sm}"
    padding: "0.52rem 0.9rem"
  input-field:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.pill}"
    height: "48px"
  dock-indicator:
    backgroundColor: "#ffffff"
    textColor: "{colors.ink-black}"
    rounded: "{rounded.pill}"
---

# Design System: LaLiga Fantasy Quant

## Overview

**Creative North Star: "El panel de la grada"**

Es una herramienta personal que se abre unos minutos antes de cada cierre: tiene que responder en un vistazo y no pedir atención. Un fondo casi negro, tarjetas gris oscuro y una sola zona cálida, el hero naranja brasa, que concentra la cifra que importa (los puntos esperados del once). Todo lo demás es neutro y sobrio, al estilo de una app financiera móvil de gama alta, y nada infantil.

La densidad es alta pero ordenada: las listas son tablas limpias, las cifras llevan tipografía tabular y el color solo aparece cuando significa algo (un cambio, una alerta, una ganancia). El azul `#0297de`, heredado de la primera versión "Cyber-Ocean", sigue en botones primarios, gráficos y métricas de datos, pero ya no es el protagonista de Inicio.

**Key Characteristics:**
- Fondo negro profundo con tarjetas neutras de poco contraste.
- Un único foco cálido por pantalla (hero naranja brasa).
- Cifras grandes, sin decoración, en peso 600 y tracking cerrado.
- Color solo para señalar cambio, riesgo o ganancia.
- Móvil primero: dock inferior de 5 destinos y zonas táctiles de 44 px.

## Colors

Paleta casi monocroma con un acento cálido y tres colores de significado.

### Primary
- **Brasa** (#ff7a3d): hero de Inicio, botones de acción de Inicio y énfasis cálido. Se mezcla con negro en degradados radiales suaves.
- **Brasa clara** (#ff9a5a) y **Melocotón** (#ffc08a): texto o cifras destacadas sobre fondo oscuro cuando el naranja pleno es demasiado intenso.

### Secondary
- **Azul datos** (#0297de): botón primario, anillos de métricas, gráficos y enlaces de datos. Es el acento de la versión anterior; úsalo para información, no para decoración.

### Tertiary
- **Menta ganancia** (#34d399): subidas, cifras positivas, estados "al día".
- **Coral alerta** (#fc734d): avisos, ventas, riesgo y saldo negativo.
- **Ámbar aviso** (#f5b544): datos antiguos y advertencias suaves.

### Neutral
- **Negro tinta** (#02070a): fondo de la app y del móvil.
- **Gris tarjeta** (#141414) y **gris elevado** (#1c1c1e): tarjetas e inputs.
- **Texto principal** (#f0f6fc), **apagado** (#8b9eb0) y **tenue** (#6f8499): jerarquía de texto. El tenue cumple 4,5:1 sobre el fondo y no debe oscurecerse más.
- **Línea** (rgba(255,255,255,0.07)): separadores de lista y bordes de tarjeta.

### Named Rules
**La regla del foco único.** Cada pantalla tiene como mucho una zona naranja grande. El resto usa neutros; el color de datos (azul, menta, coral) aparece solo en cifras y cambios.

**La regla del color con significado.** Nada se colorea por decorar. Verde es ganancia, coral es riesgo, ámbar es dato antiguo; una lista sin cambios va en blanco y gris.

## Typography

**Display / Body Font:** Inter (con Segoe UI, system-ui)
**Figure Font:** JetBrains Mono (con ui-monospace, Consolas)

**Character:** Inter da un tono neutro y moderno; JetBrains Mono se reserva para cifras que se comparan (precios, puntos, cuentas atrás).

### Hierarchy
- **Display** (600, 3.1rem, 1, -0.045em): cifra héroe de Inicio y de cada pantalla (puntos del once, nº de pujas).
- **Title** (700, 1.25rem, 1.15, -0.03em): título de pantalla.
- **Body** (400, 13px, 1.5): texto de apoyo y listas. En inputs y textareas, 16 px en móvil para evitar el zoom de iOS.
- **Label** (500, 12px): etiquetas y metadatos. No bajar de 11 px ni usar el color tenue por debajo de 4,5:1.
- **Figure** (600, tabular, -0.04em): precios, puntos y tiempos, siempre con `tabular-nums`.

### Named Rules
**La regla de la cifra.** Toda cantidad que se compara usa cifras tabulares; nunca se trunca con "…".

## Layout

Móvil primero, una columna con tarjetas de 1.5 rem de radio y 1.25 rem de relleno. Una barra de navegación flotante (dock) con 5 destinos queda anclada abajo respetando el safe-area. En escritorio aparece una barra lateral y las pantallas pasan a rejillas de 2 columnas desde 900 px. La altura de pantalla usa `dvh` para no saltar con la barra del navegador.

## Elevation & Depth

Profundidad por capas tonales, no por sombras decorativas: las tarjetas son neutras con un borde de 1 px muy tenue y un brillo interior (`inset 0 1px 0 rgba(255,255,255,0.05)`). El hero lleva una sombra amplia y suave (`0 16px 40px rgba(0,0,0,0.4)`) y el dock un desenfoque de fondo.

### Named Rules
**La regla plana.** En reposo las tarjetas no flotan; la sombra aparece solo en el hero y en el dock.

## Shapes

Esquinas generosas y consistentes: botones en 0.75 rem, tarjetas en 1.5 rem, hero en 1.75 rem, y píldora completa para dock, inputs de búsqueda y botones de estado. Los bordes son de 1 px y translúcidos. No se usan bordes laterales gruesos ni franjas de color en las tarjetas.

## Components

### Buttons
- **Shape:** esquina suave (0.75 rem).
- **Primary:** fondo azul datos con texto negro y un halo azul fino.
- **Hover / Focus:** el hover solo existe donde hay puntero (`@media (hover: hover)`); el foco visible usa un anillo azul de 2 px.
- **Secondary / Ghost:** borde translúcido o sin fondo, para acciones de bajo peso.

### Cards / Containers
- **Corner Style:** 1.5 rem.
- **Background:** gris tarjeta con degradado blanco muy tenue.
- **Border:** 1 px translúcido.
- **Internal Padding:** 1.25 rem.

### Inputs / Fields
- **Style:** píldora de 48 px, fondo gris elevado, sin borde.
- **Focus:** línea interior de 1 px en naranja brasa (buscador) o azul.
- **Mobile:** 16 px de tamaño de letra.

### Navigation
- **Dock:** píldora flotante translúcida con indicador blanco deslizante en el destino activo; iconos de 1.5 rem y zona táctil de 44 px.

### Skeleton y estados
- Barras con brillo suave durante la carga; avisos de datos antiguos en ámbar con botón Actualizar; errores en lenguaje claro, sin códigos HTTP.

## Do's and Don'ts

### Do:
- **Do** poner la cifra que decide en grande y arriba; el detalle, a un toque.
- **Do** usar `tabular-nums` y JetBrains Mono en precios, puntos y tiempos.
- **Do** mostrar el escudo de cualquier club o rival.
- **Do** dar a cada control táctil al menos 44 px de zona de toque.
- **Do** envolver los `:hover` en `@media (hover: hover)`.

### Don't:
- **Don't** usar píldoras de color en listas: van como tabla limpia y el color solo marca cambios.
- **Don't** añadir degradados en texto, bordes laterales gruesos ni animaciones con rebote.
- **Don't** usar más de una zona naranja grande por pantalla.
- **Don't** mostrar errores técnicos ("HTTP 500") al usuario.
- **Don't** bajar inputs de 16 px en móvil ni oscurecer el texto tenue por debajo de 4,5:1.
