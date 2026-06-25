/* ═══════════════════════════════════════════════════════════════════════════
   Navixa — Frontend Script
   Handles: galaxy background, dashboard polling, order submission,
            emergency stop, scroll reveal, navbar effects, ripple buttons.
   ═══════════════════════════════════════════════════════════════════════════ */

/* ════════════════════════════════════════════════════════════════════
   GALAXY INTERACTIVE BACKGROUND
   Canvas star field with orange theme, constellation lines,
   mouse repulsion, click bursts, and scroll fade-out.
   Only runs on pages that have #galaxyCanvas (landing page).
   ════════════════════════════════════════════════════════════════════ */
;(function initGalaxy() {
  const canvas = document.getElementById('galaxyCanvas');
  if (!canvas) return;

  const ctx    = canvas.getContext('2d');
  let W, H, particles;
  let frame = 0;

  /* Mouse/touch position — starts far offscreen so no initial interaction */
  const mouse = { x: -2000, y: -2000 };

  /* Tuning constants */
  const isMobile        = window.innerWidth < 768;
  const PARTICLE_COUNT  = isMobile ? 90 : 200;
  const CONNECT_DIST    = isMobile ? 90 : 130;   /* constellation line range */
  const MOUSE_DIST      = isMobile ? 90 : 130;   /* cursor connection range */
  const REPEL_DIST      = isMobile ? 80 : 110;   /* push-away range */
  const REPEL_STRENGTH  = 0.55;
  const DAMPING         = 0.965;                  /* velocity decay per frame */

  /* Orange star color palette — weighted mostly white for realism */
  const PALETTE = [
    [255, 255, 255],   /* white ×4 — most common */
    [255, 255, 255],
    [255, 255, 255],
    [255, 255, 255],
    [255, 230, 200],   /* warm white */
    [255, 200, 130],   /* warm gold */
    [255, 154,  64],   /* light orange */
    [255, 107,   0],   /* core orange */
    [255, 184,   0],   /* amber */
  ];

  /* ── Particle factory ────────────────────────────────────────────── */
  function makeParticle(x, y, burst) {
    const [r, g, b] = PALETTE[Math.floor(Math.random() * PALETTE.length)];
    const speed     = burst ? 2.5 + Math.random() * 2 : 0.08 + Math.random() * 0.14;
    const angle     = Math.random() * Math.PI * 2;
    return {
      x:    x ?? Math.random() * W,
      y:    y ?? Math.random() * H,
      vx:   Math.cos(angle) * speed,
      vy:   Math.sin(angle) * speed,
      size: burst ? 1 + Math.random() * 1.8 : 0.4 + Math.random() * 2.4,
      baseAlpha:     burst ? 1 : 0.25 + Math.random() * 0.75,
      alpha:         burst ? 1 : 0.25 + Math.random() * 0.75,
      twinkleSpeed:  0.004 + Math.random() * 0.022,
      twinklePhase:  Math.random() * Math.PI * 2,
      r, g, b,
      burst,
      life: burst ? 1 : null,
    };
  }

  function initParticles() {
    particles = Array.from({ length: PARTICLE_COUNT }, () => makeParticle());
  }

  /* ── Nebula blobs (soft glow clouds in the background) ───────────── */
  function drawNebulae() {
    const blobs = [
      { cx: W * 0.14, cy: H * 0.22, rad: 300, a: 0.04, r: 255, g: 107, b: 0 },
      { cx: W * 0.82, cy: H * 0.18, rad: 240, a: 0.03, r: 255, g: 184, b: 0 },
      { cx: W * 0.60, cy: H * 0.76, rad: 280, a: 0.025, r: 255, g: 107, b: 0 },
      { cx: W * 0.08, cy: H * 0.82, rad: 200, a: 0.02, r: 255, g: 154, b: 64 },
      { cx: W * 0.50, cy: H * 0.42, rad: 180, a: 0.015, r: 255, g: 200, b: 80 },
    ];
    blobs.forEach(({ cx, cy, rad, a, r, g, b }) => {
      const g2 = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad);
      g2.addColorStop(0, `rgba(${r},${g},${b},${a})`);
      g2.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = g2;
      ctx.beginPath();
      ctx.arc(cx, cy, rad, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  /* ── Main animation loop ─────────────────────────────────────────── */
  function tick() {
    requestAnimationFrame(tick);
    frame++;

    /* Deep space background */
    ctx.fillStyle = '#0A0A0A';
    ctx.fillRect(0, 0, W, H);

    drawNebulae();

    /* ── Constellation lines between nearby particles ── */
    for (let i = 0; i < particles.length; i++) {
      const a = particles[i];

      for (let j = i + 1; j < particles.length; j++) {
        const b  = particles[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;

        /* Quick reject before sqrt */
        if (Math.abs(dx) > CONNECT_DIST || Math.abs(dy) > CONNECT_DIST) continue;

        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist >= CONNECT_DIST) continue;

        const alpha = (1 - dist / CONNECT_DIST) * 0.22;
        ctx.strokeStyle = `rgba(255,107,0,${alpha})`;
        ctx.lineWidth   = 0.5;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
    }

    /* ── Cursor connection lines (brighter, orange) ── */
    particles.forEach(p => {
      const dx   = p.x - mouse.x;
      const dy   = p.y - mouse.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < MOUSE_DIST) {
        const alpha = (1 - dist / MOUSE_DIST) * 0.6;
        ctx.strokeStyle = `rgba(255,107,0,${alpha})`;
        ctx.lineWidth   = 0.9;
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(mouse.x, mouse.y);
        ctx.stroke();
      }
    });

    /* ── Draw cursor glow ── */
    if (mouse.x > -1000) {
      const mg = ctx.createRadialGradient(mouse.x, mouse.y, 0, mouse.x, mouse.y, 60);
      mg.addColorStop(0,   'rgba(255,107,0,0.12)');
      mg.addColorStop(0.5, 'rgba(255,107,0,0.04)');
      mg.addColorStop(1,   'rgba(0,0,0,0)');
      ctx.fillStyle = mg;
      ctx.beginPath();
      ctx.arc(mouse.x, mouse.y, 60, 0, Math.PI * 2);
      ctx.fill();
    }

    /* ── Update + draw each particle ── */
    particles.forEach((p, idx) => {
      /* Twinkle */
      p.alpha = p.baseAlpha * (0.55 + 0.45 * Math.sin(frame * p.twinkleSpeed + p.twinklePhase));

      /* Mouse repulsion */
      const mdx  = p.x - mouse.x;
      const mdy  = p.y - mouse.y;
      const mdist = Math.sqrt(mdx * mdx + mdy * mdy);
      if (mdist < REPEL_DIST && mdist > 0.1) {
        const force = (1 - mdist / REPEL_DIST) * REPEL_STRENGTH;
        p.vx += (mdx / mdist) * force;
        p.vy += (mdy / mdist) * force;
      }

      /* Velocity damping */
      p.vx *= DAMPING;
      p.vy *= DAMPING;

      /* Position update */
      p.x += p.vx;
      p.y += p.vy;

      /* Edge wrap */
      if (p.x < -4)  p.x = W + 4;
      if (p.x > W+4) p.x = -4;
      if (p.y < -4)  p.y = H + 4;
      if (p.y > H+4) p.y = -4;

      /* Draw glow halo for orange/large stars */
      const isColored = p.r < 255 || p.g < 255;
      if (p.size > 1.4 || isColored) {
        const haloR = p.size * (isColored ? 5 : 3.5);
        const halo  = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, haloR);
        halo.addColorStop(0, `rgba(${p.r},${p.g},${p.b},${p.alpha * 0.45})`);
        halo.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = halo;
        ctx.beginPath();
        ctx.arc(p.x, p.y, haloR, 0, Math.PI * 2);
        ctx.fill();
      }

      /* Core star dot */
      ctx.fillStyle = `rgba(${p.r},${p.g},${p.b},${p.alpha})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fill();

      /* Burst lifecycle */
      if (p.burst) {
        p.life       -= 0.022;
        p.baseAlpha   = Math.max(0, p.life);
        if (p.life <= 0) particles[idx] = makeParticle();
      }
    });
  }

  /* ── Resize handler ──────────────────────────────────────────────── */
  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  /* ── Scroll fade-out: galaxy fades as you scroll past the hero ───── */
  window.addEventListener('scroll', () => {
    const fade = Math.max(0, 1 - (window.scrollY / window.innerHeight) * 1.6);
    canvas.style.opacity = fade;
  }, { passive: true });

  /* ── Mouse tracking ──────────────────────────────────────────────── */
  window.addEventListener('mousemove', e => {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  }, { passive: true });

  window.addEventListener('mouseleave', () => {
    mouse.x = -2000;
    mouse.y = -2000;
  });

  /* ── Touch tracking ──────────────────────────────────────────────── */
  window.addEventListener('touchmove', e => {
    mouse.x = e.touches[0].clientX;
    mouse.y = e.touches[0].clientY;
  }, { passive: true });

  window.addEventListener('touchend', () => {
    mouse.x = -2000;
    mouse.y = -2000;
  });

  /* ── Click burst: 14 particles explode from click point ─────────── */
  window.addEventListener('click', e => {
    /* Only burst in the hero area (above the fold) */
    if (e.clientY > window.innerHeight) return;
    for (let i = 0; i < 14; i++) {
      /* Recycle the oldest/dimmest particle slot */
      let minAlpha = Infinity, minIdx = 0;
      particles.forEach((p, idx) => {
        if (!p.burst && p.alpha < minAlpha) { minAlpha = p.alpha; minIdx = idx; }
      });
      particles[minIdx] = makeParticle(
        e.clientX + (Math.random() - 0.5) * 10,
        e.clientY + (Math.random() - 0.5) * 10,
        true
      );
    }
  });

  /* ── Window resize ───────────────────────────────────────────────── */
  window.addEventListener('resize', () => {
    resize();
    initParticles();
  }, { passive: true });

  /* ── Kick off ────────────────────────────────────────────────────── */
  resize();
  initParticles();
  tick();
})();

'use strict';

/* ── State ──────────────────────────────────────────────────────────────────── */
let pollInterval   = null;
let lastUpdateTime = null;
let prevState      = null;   // detect state changes for animations
let tickerId       = null;   // "X seconds ago" counter

/* Robot state → matching icon */
const STATE_ICONS = {
  'IDLE':         '🤖',
  'NAVIGATING':   '🧭',
  'SCANNING QR':  '📷',
  'DETECTING BOX':'👁️',
  'ALIGNING':     '🎯',
  'LIFTING':      '🦾',
  'DELIVERING':   '📦',
};

/* ════════════════════════════════════════════════════════════════════
   SHARED UTILITIES
   ════════════════════════════════════════════════════════════════════ */

/** Format an ISO 8601 UTC timestamp to a local HH:MM:SS string. */
function fmtTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return '—'; }
}

/** Return "Xs ago" string from an ISO timestamp. */
function timeAgo(iso) {
  if (!iso) return '—';
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 2)  return 'just now';
  if (secs < 60) return `${secs}s ago`;
  return `${Math.floor(secs / 60)}m ago`;
}

/** Add a CSS ripple animation to a clicked button. */
function addRipple(btn, event) {
  const rect = btn.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  const x    = event.clientX - rect.left - size / 2;
  const y    = event.clientY - rect.top  - size / 2;
  const el   = document.createElement('span');
  el.className = 'ripple-el';
  el.style.cssText = `width:${size}px;height:${size}px;left:${x}px;top:${y}px`;
  btn.appendChild(el);
  setTimeout(() => el.remove(), 700);
}

/** Briefly flash a panel border to signal a data update. */
function flashPanel(el) {
  if (!el) return;
  el.style.transition = 'border-color 0.1s';
  el.style.borderColor = 'var(--orange)';
  setTimeout(() => {
    el.style.borderColor = '';
    el.style.transition = '';
  }, 400);
}

/* ════════════════════════════════════════════════════════════════════
   RIPPLE BUTTONS (landing + login pages)
   ════════════════════════════════════════════════════════════════════ */
document.querySelectorAll('.btn-ripple').forEach(btn => {
  btn.addEventListener('click', (e) => addRipple(btn, e));
});

/* ════════════════════════════════════════════════════════════════════
   NAVBAR SCROLL EFFECT (landing page)
   ════════════════════════════════════════════════════════════════════ */
const navbar = document.getElementById('navbar');
if (navbar) {
  window.addEventListener('scroll', () => {
    navbar.classList.toggle('scrolled', window.scrollY > 60);
  }, { passive: true });
}

/* ── Mobile nav toggle ──────────────────────────────────────────────── */
const navToggle = document.getElementById('navToggle');
const navLinks  = document.getElementById('navLinks');

if (navToggle && navLinks) {
  navToggle.addEventListener('click', () => {
    const open = navLinks.classList.toggle('open');
    navToggle.classList.toggle('open', open);
    navToggle.setAttribute('aria-expanded', open);
    document.body.style.overflow = open ? 'hidden' : '';
  });

  /* Close on link click */
  navLinks.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => {
      navLinks.classList.remove('open');
      navToggle.classList.remove('open');
      navToggle.setAttribute('aria-expanded', 'false');
      document.body.style.overflow = '';
    });
  });
}

/* ════════════════════════════════════════════════════════════════════
   SCROLL REVEAL (landing page)
   Observes elements with class .reveal and animates them in on entry.
   ════════════════════════════════════════════════════════════════════ */
const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry, i) => {
    if (entry.isIntersecting) {
      /* Stagger siblings using their DOM index */
      const siblings = Array.from(entry.target.parentElement?.children || []);
      const idx = siblings.indexOf(entry.target);
      setTimeout(() => {
        entry.target.classList.add('visible');
      }, idx * 120);
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.15 });

document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

/* ════════════════════════════════════════════════════════════════════
   HERO COUNTER ANIMATION (landing page)
   Counts up stat numbers when the hero section is visible.
   ════════════════════════════════════════════════════════════════════ */
const counters = document.querySelectorAll('.hero-stat-number[data-count]');

if (counters.length) {
  const counterObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const el     = entry.target;
      const target = parseInt(el.dataset.count, 10);
      const start  = performance.now();
      const duration = 1400;

      function tick(now) {
        const elapsed  = now - start;
        const progress = Math.min(elapsed / duration, 1);
        /* Ease-out cubic */
        const eased    = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(eased * target);
        if (progress < 1) requestAnimationFrame(tick);
      }

      requestAnimationFrame(tick);
      counterObserver.unobserve(el);
    });
  }, { threshold: 0.3 });

  counters.forEach(c => counterObserver.observe(c));
}

/* ════════════════════════════════════════════════════════════════════
   DASHBOARD — POLLING & UI UPDATE
   ════════════════════════════════════════════════════════════════════ */

/* Only run dashboard logic if we're on the dashboard page */
const isDashboard = !!document.getElementById('emergencyStopBtn');

if (isDashboard) {
  /* ── Start polling immediately, then every 2 seconds ── */
  pollStatus();
  pollInterval = setInterval(pollStatus, 2000);

  /* ── "X seconds ago" ticker — updates every second ── */
  tickerId = setInterval(() => {
    const el = document.getElementById('lastUpdate');
    if (el && lastUpdateTime) {
      el.textContent = 'Updated ' + timeAgo(lastUpdateTime);
    }
  }, 1000);
}

/** Fetch /api/status and update all dashboard panels. */
async function pollStatus() {
  try {
    const resp = await fetch('/api/status');
    if (!resp.ok) return;
    const data = await resp.json();
    lastUpdateTime = new Date().toISOString();
    updateDashboard(data);
  } catch (err) {
    /* Network error — mark offline */
    setConnectionBadge(false);
  }
}

/* ── Master update function ─────────────────────────────────────────────────── */
function updateDashboard(data) {
  const robot   = data.robot   || {};
  const orders  = data.orders  || [];
  const history = data.history || [];

  updateConnectionBadge(robot);
  updateStatusPanel(robot);
  updatePipeline(robot.state);
  updateQueue(orders, robot);
  updateHistory(history);
}

/* ── Connection badge ───────────────────────────────────────────────────────── */
function updateConnectionBadge(robot) {
  setConnectionBadge(robot.connected === true);
}

function setConnectionBadge(online) {
  const badge = document.getElementById('connectionBadge');
  const text  = document.getElementById('connectionText');
  if (!badge || !text) return;

  badge.className = 'connection-indicator ' + (online ? 'online' : 'offline');
  text.textContent = online ? 'Robot Online' : 'Robot Offline';
}

/* ── Status panel ───────────────────────────────────────────────────────────── */
function updateStatusPanel(robot) {
  const stateVal     = robot.state || 'IDLE';
  const isActive     = stateVal !== 'IDLE';

  /* Animate icon if state changed */
  if (stateVal !== prevState) {
    animateStateChange(stateVal);
    prevState = stateVal;
  }

  /* State display */
  const display = document.getElementById('stateDisplay');
  const stateEl = document.getElementById('robotStateValue');
  const iconEl  = document.getElementById('robotIcon');

  if (stateEl) {
    stateEl.textContent = stateVal;
    stateEl.className   = 'robot-state-value ' + (isActive ? 'active' : 'idle');
  }
  if (display) {
    display.className = 'robot-state-display ' + (isActive ? 'active' : 'idle');
  }
  if (iconEl) {
    iconEl.textContent = STATE_ICONS[stateVal] || '🤖';
  }

  /* Status badge */
  updateStatusBadge(stateVal);

  /* Current order */
  const orderEl = document.getElementById('currentOrderDisplay');
  if (orderEl) {
    orderEl.textContent = robot.current_order || '—';
    orderEl.style.color = robot.current_order ? 'var(--orange)' : '';
  }

  /* Battery */
  const batEl   = document.getElementById('batteryDisplay');
  const batFill = document.getElementById('batteryFill');
  const pct     = robot.battery != null ? Math.round(robot.battery) : null;

  if (batEl)   batEl.textContent = pct != null ? `${pct}%` : '—';
  if (batFill && pct != null) {
    batFill.style.width = `${pct}%`;
    batFill.className   = 'battery-fill ' +
      (pct > 50 ? 'high' : pct > 20 ? 'mid' : 'low');
  }
}

/** Update the colored status badge next to the panel title. */
function updateStatusBadge(state) {
  const badge = document.getElementById('statusBadge');
  const text  = document.getElementById('statusBadgeText');
  if (!badge || !text) return;

  text.textContent = state;

  let cls = 'badge ';
  if (state === 'IDLE')       cls += 'badge-idle';
  else if (state === 'DELIVERING') cls += 'badge-completed';
  else                        cls += 'badge-progress';

  badge.className = cls;
}

/** Pop animation when robot changes state. */
function animateStateChange(newState) {
  const icon = document.getElementById('robotIcon');
  if (!icon) return;

  /* Quick scale-up bounce */
  icon.style.transition = 'transform 0.15s cubic-bezier(0.34,1.56,0.64,1)';
  icon.style.transform  = 'scale(1.4) rotate(-10deg)';
  setTimeout(() => {
    icon.style.transform = 'scale(1) rotate(0deg)';
    setTimeout(() => { icon.style.transition = ''; }, 300);
  }, 150);
}

/* ── Vision Pipeline ────────────────────────────────────────────────────────── */
const PIPELINE_ORDER = [
  'IDLE', 'NAVIGATING', 'SCANNING QR', 'DETECTING BOX',
  'ALIGNING', 'LIFTING', 'DELIVERING',
];

function updatePipeline(currentState) {
  const currentIdx = PIPELINE_ORDER.indexOf(currentState);
  const labelEl    = document.getElementById('pipelineStageLabel');

  if (labelEl) {
    labelEl.textContent = currentState || 'Standby';
  }

  PIPELINE_ORDER.forEach((stage, idx) => {
    const stageEl = document.getElementById('stage-' + stage);
    if (!stageEl) return;

    stageEl.className = 'pipeline-stage';

    if (idx < currentIdx) {
      stageEl.classList.add('completed');
    } else if (idx === currentIdx) {
      stageEl.classList.add('active');
    }
  });
}

/* ── Order Queue ────────────────────────────────────────────────────────────── */
function updateQueue(orders, robot) {
  const list      = document.getElementById('queueList');
  const emptyEl   = document.getElementById('queueEmpty');
  const countEl   = document.getElementById('queueCount');
  const warnEl    = document.getElementById('orderWarning');
  const submitBtn = document.getElementById('submitOrderBtn');

  if (!list) return;

  const hasActive = orders.some(o => o.status === 'IN_PROGRESS' || o.status === 'PENDING');

  /* Show/hide warning and disable order form */
  if (warnEl)   warnEl.classList.toggle('visible', hasActive);
  if (submitBtn) submitBtn.disabled = hasActive;

  /* Count badge */
  if (countEl) {
    countEl.textContent = `${orders.length} order${orders.length !== 1 ? 's' : ''}`;
    countEl.className   = 'badge ' + (orders.length > 0 ? 'badge-progress' : 'badge-idle');
  }

  /* Empty state */
  if (emptyEl) emptyEl.style.display = orders.length === 0 ? 'block' : 'none';

  /* Render queue items — only re-render if count changed to avoid flicker */
  const existing = list.querySelectorAll('.queue-item');
  if (existing.length !== orders.length) {
    /* Clear old items (keep the empty placeholder) */
    existing.forEach(el => el.remove());

    orders.forEach(order => {
      const item = document.createElement('div');
      item.className = 'queue-item' + (order.status === 'IN_PROGRESS' ? ' in-progress' : '');
      item.setAttribute('data-id', order.id);

      const badgeClass = order.status === 'IN_PROGRESS' ? 'badge-progress' : 'badge-pending';
      const badgeText  = order.status === 'IN_PROGRESS' ? 'In Progress' : 'Pending';

      item.innerHTML = `
        <span class="queue-shelf">${escapeHtml(order.shelf_id)}</span>
        <span class="badge ${badgeClass}">
          <span class="badge-dot"></span> ${badgeText}
        </span>
        <span class="queue-time">${fmtTime(order.created_at)}</span>
      `;
      list.appendChild(item);
    });
  } else {
    /* Just update badge classes in place to avoid re-animation */
    orders.forEach((order, i) => {
      const item = existing[i];
      if (!item) return;
      const isProgress = order.status === 'IN_PROGRESS';
      item.className = 'queue-item' + (isProgress ? ' in-progress' : '');
      const badge = item.querySelector('.badge');
      if (badge) {
        badge.className = 'badge ' + (isProgress ? 'badge-progress' : 'badge-pending');
        const dot  = badge.querySelector('.badge-dot');
        const span = badge.querySelector('span:last-child');
        if (span) span.textContent = isProgress ? ' In Progress' : ' Pending';
      }
    });
  }
}

/* ── Order History ──────────────────────────────────────────────────────────── */
function updateHistory(history) {
  const tbody   = document.getElementById('historyBody');
  const countEl = document.getElementById('historyCount');
  if (!tbody)   return;

  if (countEl) {
    countEl.textContent = `${history.length} completed`;
  }

  if (history.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="history-empty">No completed orders yet</td></tr>';
    return;
  }

  /* Only re-render when row count changes */
  if (tbody.querySelectorAll('tr[data-id]').length === history.length) return;

  tbody.innerHTML = history.map(order => {
    const statusClass = {
      COMPLETED: 'badge-completed',
      FAILED:    'badge-failed',
    }[order.status] || 'badge-idle';

    return `
      <tr data-id="${escapeHtml(order.id)}">
        <td><code style="color:var(--orange);font-family:monospace;font-size:var(--text-xs)">${escapeHtml(order.id)}</code></td>
        <td><strong>${escapeHtml(order.shelf_id)}</strong></td>
        <td><span class="badge ${statusClass}"><span class="badge-dot"></span>${order.status}</span></td>
        <td>${fmtTime(order.created_at)}</td>
        <td>${fmtTime(order.completed_at)}</td>
      </tr>
    `;
  }).join('');
}

/* ════════════════════════════════════════════════════════════════════
   ORDER SUBMISSION
   ════════════════════════════════════════════════════════════════════ */
async function submitOrder() {
  const input   = document.getElementById('shelfInput');
  const btn     = document.getElementById('submitOrderBtn');
  const toast   = document.getElementById('orderSuccessToast');
  if (!input || !btn) return;

  const shelfId = input.value.trim().toUpperCase();
  if (!shelfId) {
    shakeElement(input);
    input.focus();
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span aria-hidden="true">⏳</span> Sending…';

  try {
    const resp = await fetch('/api/order', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ shelf_id: shelfId }),
    });

    const data = await resp.json();

    if (data.success) {
      input.value = '';

      /* Success toast */
      if (toast) {
        toast.textContent = `✓ Order sent — ${shelfId} (ID: ${data.order_id})`;
        toast.style.display = 'block';
        setTimeout(() => { toast.style.display = 'none'; }, 5000);
      }

      /* Immediately refresh queue */
      pollStatus();

    } else {
      showOrderError(data.error || 'Failed to place order');
      btn.disabled = false;
    }

  } catch (err) {
    showOrderError('Network error — check connection');
    btn.disabled = false;
  }

  btn.innerHTML = '<span aria-hidden="true">🚀</span> Send Order';
}

function showOrderError(message) {
  const warn = document.getElementById('orderWarning');
  if (warn) {
    warn.textContent = '⚠ ' + message;
    warn.classList.add('visible');
    setTimeout(() => { warn.classList.remove('visible'); }, 5000);
  }
}

/* Allow Enter key in the shelf input to submit */
const shelfInput = document.getElementById('shelfInput');
if (shelfInput) {
  shelfInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') submitOrder();
    /* Auto-uppercase while typing */
    setTimeout(() => { shelfInput.value = shelfInput.value.toUpperCase(); }, 0);
  });
}

/* ════════════════════════════════════════════════════════════════════
   EMERGENCY STOP
   Single click — no confirmation dialog.
   QoS 2 on the backend ensures exactly-once delivery.
   ════════════════════════════════════════════════════════════════════ */
async function emergencyStop() {
  const btn = document.getElementById('emergencyStopBtn');

  /* Visual feedback first — before the HTTP round trip */
  if (btn) {
    btn.style.transform  = 'scale(0.92)';
    btn.style.background = '#CC0000';
    setTimeout(() => {
      btn.style.transform  = '';
      btn.style.background = '';
    }, 300);
  }

  try {
    const resp = await fetch('/api/stop', { method: 'POST' });
    const data = await resp.json();

    if (data.success) {
      /* Immediately refresh to show FAILED orders */
      pollStatus();
    }
  } catch (err) {
    console.error('[STOP] Network error:', err);
    /* Still try again — safety critical */
    setTimeout(() => fetch('/api/stop', { method: 'POST' }).catch(() => {}), 500);
  }
}

/* ════════════════════════════════════════════════════════════════════
   HELPERS
   ════════════════════════════════════════════════════════════════════ */

/** Shake an input to indicate validation error. */
function shakeElement(el) {
  el.style.animation = 'none';
  el.offsetHeight;   /* force reflow */
  el.style.animation = 'shake 0.4s ease';
  setTimeout(() => { el.style.animation = ''; }, 500);
}

/** Escape HTML to prevent XSS when inserting dynamic content. */
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

/* ════════════════════════════════════════════════════════════════════
   MENU VERTICAL — SCROLL SPY  (berlix exact translation)
   Tracks which section is active and applies .active to that nav item.
   Active item: arrow visible at x:0 + label at x:0 orange (CSS handles it).
   ════════════════════════════════════════════════════════════════════ */
;(function initMenuVertical() {
  const nav = document.getElementById('menuVertical');
  if (!nav) return;

  const items    = nav.querySelectorAll('.mv-item[href^="#"]');
  const sections = [];

  items.forEach(item => {
    const id  = item.getAttribute('href').slice(1);
    const sec = document.getElementById(id);
    if (sec) sections.push({ item, sec });
  });

  function updateActive() {
    const trigger = window.innerHeight * 0.48;
    let active = sections[0];
    sections.forEach(e => {
      if (e.sec.getBoundingClientRect().top <= trigger) active = e;
    });
    items.forEach(i => i.classList.remove('active'));
    if (active) active.item.classList.add('active');
  }

  window.addEventListener('scroll', updateActive, { passive: true });
  requestAnimationFrame(updateActive);
})();

/* ════════════════════════════════════════════════════════════════════
   VERTICAL IMAGE STACK  (jatin-yadav05/vertical-image-stack)
   Cards stack up inside a sticky frame as user scrolls.
   Each card slides in, previous cards scale down and fade.
   ════════════════════════════════════════════════════════════════════ */
;(function initVerticalStack() {
  const wrapper = document.getElementById('verticalStack');
  if (!wrapper) return;

  const cards   = Array.from(wrapper.querySelectorAll('.vis-card'));
  const counter = document.getElementById('visCurrentNum');
  if (!cards.length) return;

  const CARD_COUNT = cards.length;

  function getProgress() {
    const rect     = wrapper.getBoundingClientRect();
    const scrolled = -rect.top;
    const total    = wrapper.offsetHeight - window.innerHeight;
    return Math.max(0, Math.min(1, scrolled / total));
  }

  function update() {
    const progress   = getProgress();
    const slot       = progress * CARD_COUNT;
    const activeIndex = Math.min(CARD_COUNT - 1, Math.floor(slot));

    if (counter) counter.textContent = String(activeIndex + 1);

    cards.forEach((card, i) => {
      if (i > activeIndex) {
        card.style.transform = 'translateY(100%) scale(1)';
        card.style.opacity   = '0';
        card.style.zIndex    = String(i);
      } else if (i === activeIndex) {
        card.style.transform = 'translateY(0%) scale(1)';
        card.style.opacity   = '1';
        card.style.zIndex    = String(CARD_COUNT + i);
      } else {
        const depth  = activeIndex - i;
        const scale  = Math.max(0.82, 1 - depth * 0.05);
        const pushUp = depth * 24;
        card.style.transform = `translateY(-${pushUp}px) scale(${scale})`;
        card.style.opacity   = String(Math.max(0, 1 - depth * 0.22));
        card.style.zIndex    = String(CARD_COUNT - depth);
      }
    });
  }

  /* Snap initial state without transitions, then enable them */
  cards.forEach(c => { c.style.transition = 'none'; });
  update();
  requestAnimationFrame(() => {
    cards.forEach(c => {
      c.style.transition = 'transform 0.45s cubic-bezier(0.22,1,0.36,1), opacity 0.45s ease';
    });
  });

  window.addEventListener('scroll', update, { passive: true });
  window.addEventListener('resize', update, { passive: true });
})();

/* end of landing page scripts */
