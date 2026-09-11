/**
 * Scroll-reactive 3D globe for the Deus hero.
 * The module is isolated from the search app; it only updates hero visuals.
 */

(async function initHeroGlobe() {
  'use strict';

  const mount = document.getElementById('hero-coin');
  if (!mount) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const scene = document.createElement('div');
  scene.className = 'space-globe';
  scene.innerHTML = `
    <div class="space-stars" aria-hidden="true"></div>
    <div class="globe-shell" aria-hidden="true">
      <div class="globe-core"></div>
      <div class="globe-grid globe-grid-a"></div>
      <div class="globe-grid globe-grid-b"></div>
      <div class="globe-ring globe-ring-a"></div>
      <div class="globe-ring globe-ring-b"></div>
      <span class="globe-node globe-node-a"></span>
      <span class="globe-node globe-node-b"></span>
      <span class="globe-node globe-node-c"></span>
    </div>
  `;
  mount.append(scene);

  const sourceCard = document.getElementById('hero-source-card');
  sourceCard?.addEventListener('click', () => {
    sourceCard.classList.add('is-embossed');
    window.setTimeout(() => sourceCard.classList.remove('is-embossed'), 950);
  });

  if (reducedMotion) return;

  let anime;
  try {
    const mod = await import('https://cdn.jsdelivr.net/npm/animejs@3.2.2/lib/anime.es.js');
    anime = mod.default;
  } catch {
    anime = null;
  }

  if (anime) {
    anime({
      targets: scene.querySelectorAll('.globe-node'),
      scale: [.75, 1.35],
      opacity: [.38, 1],
      delay: anime.stagger(260),
      duration: 2100,
      direction: 'alternate',
      loop: true,
      easing: 'easeInOutSine',
    });
    anime({
      targets: sourceCard,
      translateY: [-4, 5],
      duration: 3800,
      direction: 'alternate',
      loop: true,
      easing: 'easeInOutSine',
    });
  }

  const updateScroll = () => {
    const hero = document.querySelector('.hero');
    const rect = hero?.getBoundingClientRect();
    const viewport = window.innerHeight || 1;
    const progress = rect ? Math.min(1, Math.max(0, (viewport - rect.top) / (viewport + rect.height))) : 0;
    mount.style.setProperty('--scroll-tilt', `${-8 + progress * 8}deg`);
    mount.style.setProperty('--scroll-y', `${progress * 22}px`);
    if (sourceCard) sourceCard.style.setProperty('--tag-y', `${progress * 18}px`);
  };

  updateScroll();
  window.addEventListener('scroll', updateScroll, { passive: true });
  window.addEventListener('resize', updateScroll);
})();
