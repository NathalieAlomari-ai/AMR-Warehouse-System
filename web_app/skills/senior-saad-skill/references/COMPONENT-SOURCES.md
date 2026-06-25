# 🧩 SAAD Component Sources Reference
## Senior SAAD System — Component Library Guide

---

## SOURCE 1: KokonutUI
**URL:** https://kokonutui.com/
**Type:** Free, open-source React/Tailwind components
**Best for:** Glassmorphism, gradients, unique visual effects

### Key Components by Category:

**Cards & Containers**
- Spotlight Card — hover spotlight effect
- Glassmorphism Card — frosted glass aesthetic
- 3D Flip Card — perspective flip on hover
- Gradient Border Card — animated gradient border
- Noise Texture Card — subtle grain overlay

**Navigation**
- Dock Navigation — macOS-style animated dock
- Sidebar with collapse — animated sidebar
- Top Nav with blur — sticky blur on scroll
- Breadcrumb trail

**Buttons & CTAs**
- Magnetic Button — follows cursor
- Glow Button — pulsing glow effect
- Gradient Button — animated gradient
- 3D Push Button — depth press effect

**Inputs & Forms**
- Floating Label Input — label animates on focus
- AI Input — typing indicator style
- Animated Border Input — border draws on focus
- Search with animation

**Display & Data**
- Animated Counter — number increment
- Progress Ring — circular progress
- Timeline component
- Feature Grid
- Stats card with animation

**Backgrounds & Effects**
- Aurora Background — gradient aurora effect
- Particle Field — floating particles
- Grid/Dot background pattern
- Mesh gradient background
- Noise overlay

---

## SOURCE 2: 21st.dev Community
**URL:** https://21st.dev/community/components
**Type:** Community-submitted shadcn/ui components
**Best for:** Full page sections, complex UI patterns

### Key Components by Category:

**Landing Page Sections**
- Hero with CTA + animation
- Feature showcase (3-6 columns)
- Testimonials carousel/grid
- Pricing table (monthly/annual toggle)
- FAQ accordion
- Newsletter signup
- Footer with links

**Dashboard Layouts**
- Sidebar + main content layout
- Stats overview cards
- Activity feed
- Recent items table
- Quick actions grid
- Notification center

**Data & Tables**
- Sortable data table
- Filterable list
- Pagination component
- Empty state designs
- Loading skeleton

**Auth Screens**
- Login with social providers
- Registration multi-step
- Forgot password flow
- Email verification
- Two-factor auth

**Utility Components**
- Command palette (⌘K)
- Multi-select dropdown
- Date range picker
- File upload with preview
- Color picker
- Rich text editor

---

## SOURCE 3: Anime.js v4
**URL:** https://animejs.com/
**NPM:** `pnpm add animejs`
**Type:** JavaScript animation engine

### v4 API Quick Reference:

```javascript
import anime from 'animejs';

// Basic animation
anime({
  targets: '.element',
  translateX: 250,
  rotate: '1turn',
  opacity: [0, 1],
  duration: 800,
  easing: 'easeOutExpo',
});

// Spring physics (most natural feel)
anime({
  targets: '.element',
  translateY: [40, 0],
  opacity: [0, 1],
  easing: 'spring(mass, stiffness, damping, velocity)',
  // Example: 'spring(1, 80, 10, 0)'
});

// Stagger (cascade effect)
anime({
  targets: '.cards',
  translateY: [30, 0],
  opacity: [0, 1],
  delay: anime.stagger(100),          // 100ms between each
  delay: anime.stagger(100, {from: 'center'}), // from center out
  delay: anime.stagger(100, {grid: [3, 4], from: 'center'}), // grid
});

// Timeline (sequence/overlap)
anime.timeline({ easing: 'easeOutExpo' })
  .add({ targets: '.hero', translateY: [-60, 0], opacity: [0, 1], duration: 1000 })
  .add({ targets: '.nav', translateY: [-20, 0], opacity: [0, 1], duration: 600 }, '-=800')
  .add({ targets: '.cards', translateY: [30, 0], opacity: [0, 1], 
         delay: anime.stagger(80), duration: 600 }, '-=400');

// Number counter
anime({
  targets: '.counter',
  innerHTML: [0, 1000],
  round: 1,
  easing: 'easeOutExpo',
  duration: 2000,
});

// SVG path drawing
anime({
  targets: 'path',
  strokeDashoffset: [anime.setDashoffset, 0],
  easing: 'easeInOutSine',
  duration: 1500,
});
```

### Accessibility (Always Add):
```javascript
const prefersReducedMotion = window.matchMedia(
  '(prefers-reduced-motion: reduce)'
).matches;

if (!prefersReducedMotion) {
  // Run animations
  anime({ ... });
}
```

---

## INSTALLATION COMMANDS

```bash
# KokonutUI — no install needed, copy component code
# Visit: https://kokonutui.com/

# 21st.dev — no install needed, copy component code
# Visit: https://21st.dev/community/components

# Anime.js
pnpm add animejs
# or
npm install animejs

# TypeScript types
pnpm add -D @types/animejs
```

---

*SAAD Component Sources v2.0 — Senior SAAD System*
