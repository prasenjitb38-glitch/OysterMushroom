(() => {
  const body = document.body, toggle = document.getElementById('nav-toggle'), overlay = document.getElementById('nav-overlay');
  const mobile = () => window.matchMedia('(max-width: 720px)').matches;
  const expanded = value => toggle && toggle.setAttribute('aria-expanded', value ? 'true' : 'false');
  const closeMobile = () => { body.classList.remove('nav-open'); expanded(false); };
  if (toggle) toggle.addEventListener('click', () => { if (mobile()) { expanded(body.classList.toggle('nav-open')); } else { expanded(!body.classList.toggle('nav-collapsed')); } });
  if (overlay) overlay.addEventListener('click', closeMobile);
  document.querySelectorAll('#sidebar a').forEach(link => link.addEventListener('click', () => { if (mobile()) closeMobile(); }));
  window.addEventListener('resize', () => { if (!mobile()) closeMobile(); });
})();
