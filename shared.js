const GENRE_MAP = {
  'джаз': 'jazz', 'рок': 'rock', 'русский рок': 'rock', 'панк-рок': 'rock',
  'инди-рок': 'rock', 'метал': 'rock', 'инди': 'rock', 'авторская': 'rock',
  'классика': 'classic', 'хоровая': 'classic', 'медитативная': 'classic',
  'поп': 'pop', 'поп-рок': 'pop', 'лаунж': 'pop', 'хип-хоп': 'pop',
  'каверы': 'pop', 'юмор': 'pop', 'шоу': 'pop', 'интерактив': 'pop',
  'этно': 'folk', 'фолк-метал': 'folk', 'народная': 'folk',
  'блюз': 'blues'
};

const GENRE_LABELS = {
  jazz: 'Джаз', rock: 'Рок', folk: 'Этно/Фолк',
  blues: 'Блюз', classic: 'Классика', pop: 'Поп'
};

function mapGenre(raw) { return GENRE_MAP[raw?.toLowerCase()] || 'pop'; }

function openSubModal() {
  document.getElementById('sub-modal').classList.add('open');
  document.body.style.overflow = 'hidden';
}
function closeSubModal() {
  document.getElementById('sub-modal').classList.remove('open');
  document.body.style.overflow = '';
}
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeSubModal();
});

const _TG_SVG = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M21.94 4.6 18.9 19.3c-.22 1.02-.83 1.27-1.69.79l-4.69-3.46-2.26 2.18c-.25.25-.46.46-.94.46l.34-4.77 8.68-7.84c.38-.34-.08-.53-.59-.19L6.7 12.55l-4.62-1.44c-1-.32-1.03-1.01.21-1.49l18.06-6.96c.84-.31 1.57.2 1.3 1.49z"/></svg>';

const _NAV_HTML = `<nav class="nav">
  <a href="/index.html" class="nav-logo">местов<em>.нет</em></a>
  <div class="nav-sep"></div>
  <div class="nav-genres" id="nav-genres"></div>
  <button class="nav-cta" type="button" onclick="openSubModal()" aria-label="Подписаться на бота в Telegram">
    ${_TG_SVG}
    <span>Подписаться</span>
  </button>
</nav>`;

const _MODAL_HTML = `<div class="modal-overlay" id="sub-modal" role="dialog" aria-modal="true" aria-labelledby="sub-modal-title" onclick="if(event.target===this)closeSubModal()">
  <div class="modal">
    <button class="modal-close" type="button" onclick="closeSubModal()" aria-label="Закрыть">&times;</button>
    <span class="modal-badge">
      ${_TG_SVG}
      Telegram-бот
    </span>
    <h2 class="modal-title" id="sub-modal-title">Концерты — прямо в Telegram</h2>
    <p class="modal-lead">Бот «Местов.Нет» сам пришлёт подборку живой музыки Крыма — без листания афиш и пропущенных вечеров.</p>
    <ul class="modal-list">
      <li><span class="ico">♫</span><span><b>Под ваш вкус.</b> Выбираете жанры и города — приходит только то, что интересно.</span></li>
      <li><span class="ico">↻</span><span><b>В удобном ритме.</b> Раз в день, раз в неделю или по запросу — как захотите.</span></li>
      <li><span class="ico">✓</span><span><b>Бесплатно и без спама.</b> Только концерты, отписаться можно в одно касание.</span></li>
    </ul>
    <a class="modal-cta" href="https://t.me/mestovnet_bot" target="_blank" rel="noopener" onclick="closeSubModal()">
      ${_TG_SVG}
      Открыть в Telegram
    </a>
    <p class="modal-note">@mestovnet_bot · подписка за 10 секунд</p>
  </div>
</div>`;

const _FOOTER_HTML = `<footer>
  <a href="/index.html" class="footer-logo">местов<em>.нет</em></a>
  <span class="footer-note">Афиша живой музыки Крыма · 2026</span>
</footer>`;

class SiteNav extends HTMLElement {
  connectedCallback() {
    this.insertAdjacentHTML('afterend', _NAV_HTML);
    this.remove();
  }
}
class SiteModal extends HTMLElement {
  connectedCallback() {
    this.insertAdjacentHTML('afterend', _MODAL_HTML);
    this.remove();
  }
}
class SiteFooter extends HTMLElement {
  connectedCallback() {
    this.insertAdjacentHTML('afterend', _FOOTER_HTML);
    this.remove();
  }
}
customElements.define('site-nav', SiteNav);
customElements.define('site-modal', SiteModal);
customElements.define('site-footer', SiteFooter);
