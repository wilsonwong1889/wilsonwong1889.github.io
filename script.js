// ========================= script.js =========================
// Mobile menu toggle
const nav = document.getElementById('nav');
const menuBtn = document.getElementById('menuBtn');
menuBtn?.addEventListener('click',()=>nav.classList.toggle('open'));

// Active link on scroll
const sections = [...document.querySelectorAll('section, header.hero')];
const links = [...document.querySelectorAll('.nav a')];
const inView = (el)=>{
  const r = el.getBoundingClientRect();
  return r.top < innerHeight*0.4 && r.bottom > innerHeight*0.25;
};
const updateActive = ()=>{
  sections.forEach(sec=>{
    if(inView(sec)){
      const id = sec.id || 'home';
      links.forEach(a=>a.classList.toggle('active', a.getAttribute('href')==='#'+id));
    }
  })
};
addEventListener('scroll', updateActive, {passive:true});
addEventListener('load', updateActive);

// Back to top button
const toTop = document.getElementById('toTop');
addEventListener('scroll',()=>{
  if(scrollY>400) toTop.classList.add('show'); else toTop.classList.remove('show');
},{passive:true});
toTop.addEventListener('click',()=>window.scrollTo({top:0,behavior:'smooth'}));

// Year
const yearEl = document.getElementById('year');
if (yearEl) yearEl.textContent = new Date().getFullYear();
