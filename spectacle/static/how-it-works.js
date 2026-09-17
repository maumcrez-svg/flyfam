import {plannedEconomics} from './brand.js';

// This guide can open even if the main live feed cannot initialize.
// Only read projections on open. No wallet provider, signer or financial engine.
const dialog = document.getElementById('about-dialog');
const tabs = [...dialog.querySelectorAll('[role=tab]')];
const scroller = dialog.querySelector('.guide-scroll');
const status = document.getElementById('guide-runtime-status');
const checked = document.getElementById('guide-runtime-checked');
const hashBase = '#how-it-works';
let returnURL, opener, requestGeneration = 0;

function chapter(key, focus = false) {
  if (!tabs.some(t => t.dataset.chapter === key)) key = 'loop';
  for (const tab of tabs) {
    const active = tab.dataset.chapter === key;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
    if (active && focus) tab.focus();
  }
  scroller.scrollTop = 0;
  history.replaceState(history.state, '', location.pathname + location.search + hashBase + (key === 'loop' ? '' : '/' + key));
}

async function runtime() {
  const ticket = ++requestGeneration;
  status.textContent = 'CHECKING CURRENT MODE…';
  checked.textContent = 'THIS DEPLOYMENT';
  try {
    const read = async path => {
      const r = await fetch(path, {cache:'no-store', signal:AbortSignal.timeout(5000)});
      if (!r.ok) throw Error('Mode unavailable');
      return r.json();
    };
    const [site, health, vault] = await Promise.all([
      read('/api/site'), read('/api/health'), read('/api/vault/summary'),
    ]);
    if (ticket !== requestGeneration || !dialog.open) return;
    const fixture = new URLSearchParams(location.search).get('fixture') === '1' || site.fixture === true;
    const holders = fixture || site.test_holders === true || site.holder_source === 'FIXTURE' ? 'TEST HOLDERS' : site.holder_source === 'REAL_HOLDERS' ? 'ON-CHAIN HOLDERS' : 'HOLDERS NOT VERIFIED';
    const execution = fixture ? 'FIXTURE / TEST' : health.execution === 'PAPER' ? 'PAPER' : health.execution === 'LIVE' ? 'REAL EXECUTION' : 'EXECUTION NOT VERIFIED';
    const payments = fixture || health.execution === 'PAPER' || site.test_holders === true ? 'NO REAL CLAIMS' : vault.configured === true ? 'SEE BAG FUNDING / RECEIPTS' : 'PAYOUT NOT CONFIGURED';
    status.textContent = `${execution} · ${holders} · ${payments}`;
    const freshness = !fixture && health.status !== 'LIVE' ? ' · MARKET OFFLINE / STALE' : '';
    checked.textContent = `MODE CHECKED ${new Date().toLocaleTimeString('en-GB')}${freshness}`;
  } catch {
    if (ticket !== requestGeneration || !dialog.open) return;
    checked.textContent = 'CURRENT MODE UNAVAILABLE';
    status.textContent = 'Guide explains the rules. Live funds and claims are not verified.';
  }
}

function open(key = 'loop', trigger = null) {
  if (!dialog.open) {
    opener = trigger || document.activeElement;
    returnURL = location.pathname + location.search + (location.hash.startsWith(hashBase) ? '' : location.hash);
    dialog.showModal();
    runtime();
  }
  chapter(key, true);
}

for (const link of document.querySelectorAll('[data-guide]')) {
  link.addEventListener('click', e => {e.preventDefault(); open(link.dataset.guide || 'loop', link);});
}
tabs.forEach((tab, i) => {
  tab.addEventListener('click', () => chapter(tab.dataset.chapter));
  tab.addEventListener('keydown', e => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    const index = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length;
    chapter(tabs[index].dataset.chapter, true);
  });
});
dialog.querySelectorAll('[data-guide-next]').forEach(button => button.addEventListener('click', () => chapter(button.dataset.guideNext, true)));
function close() {
  if (!dialog.open) return;
  requestGeneration++;
  // Restore synchronously: a delayed native close event can otherwise erase
  // a new chapter URL when the user immediately opens another deep link.
  if (location.hash.startsWith(hashBase)) history.replaceState(history.state, '', returnURL || location.pathname + location.search);
  dialog.close();
  if (opener?.isConnected && opener.getClientRects().length) opener.focus({preventScroll:true});
  else [...document.querySelectorAll('[data-guide]')].find(el => el.getClientRects().length)?.focus({preventScroll:true});
}
dialog.querySelectorAll('[data-guide-close]').forEach(button => button.addEventListener('click', close));
dialog.addEventListener('cancel', e => {e.preventDefault(); close();});
dialog.addEventListener('click', e => {
  if (e.target !== dialog) return;
  const r = dialog.getBoundingClientRect();
  if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) close();
});
function fromURL() {
  if (location.hash === '#about-dialog' || location.hash.startsWith(hashBase)) open(location.hash.split('/')[1]);
  else if (dialog.open) close();
}
window.addEventListener('hashchange', fromURL);

const fees = document.getElementById('guide-fees');
for (const [label, amount] of plannedEconomics.allocations) {
  const row = document.createElement('div');
  row.textContent = label;
  const value = document.createElement('strong');
  value.textContent = `${amount.toFixed(1)}%`;
  row.append(value); fees.append(row);
}
fromURL();
