/**
 * Телеграм-бот «Местов.Нет» для Cloudflare Workers.
 *
 * Мгновенный бесплатный serverless:
 *   • webhook — Telegram шлёт апдейты на Worker (мгновенный ответ);
 *   • Cron Trigger — рассылка в 13:20 UTC (16:20 Крым);
 *   • хранилище — Cloudflare KV (биндинг с именем KV).
 *
 * Переменные/секреты Worker:
 *   BOT_TOKEN, WEBHOOK_SECRET, ADMIN_ID
 * Биндинг KV namespace: KV
 */

const SITE = "https://mestov.net";
const EVENTS_URL = `${SITE}/events.json`;
const SETTINGS_URL = `${SITE}/settings.json`;
const MAX_EVENTS = 25;
const HORIZON_DAYS = 7;

const GENRE_MAP = {
  "джаз": "jazz",
  "рок": "rock", "русский рок": "rock", "панк-рок": "rock",
  "инди-рок": "rock", "метал": "rock", "инди": "rock", "авторская": "rock",
  "классика": "classic", "хоровая": "classic", "медитативная": "classic",
  "поп": "pop", "поп-рок": "pop", "лаунж": "pop", "хип-хоп": "pop",
  "каверы": "pop", "юмор": "pop", "шоу": "pop", "интерактив": "pop",
  "этно": "folk", "фолк-метал": "folk", "народная": "folk",
  "блюз": "blues",
};
const GENRE_LABELS = { jazz: "Джаз", rock: "Рок", folk: "Фолк", blues: "Блюз", classic: "Классика", pop: "Поп" };
const GENRE_ORDER = ["jazz", "rock", "folk", "blues", "classic", "pop"];

const CITY_MAP = {
  "Севастополь": "sevastopol", "Симферополь": "simferopol", "Ялта": "yalta",
  "Судак": "sudak", "Керчь": "kerch", "Коктебель": "koktebel",
  "Бахчисарай": "bakhchisaray", "Евпатория": "evpatoria", "Крым": "all",
};
const CITY_LABELS = {
  sevastopol: "Севастополь", simferopol: "Симферополь", yalta: "Ялта",
  sudak: "Судак", kerch: "Керчь", koktebel: "Коктебель",
  bakhchisaray: "Бахчисарай", evpatoria: "Евпатория",
};
const CITY_ORDER = ["sevastopol", "simferopol", "yalta", "evpatoria", "kerch", "sudak", "koktebel", "bakhchisaray"];

const MONTHS_GEN = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const DOW = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
const WEEKDAY_LABELS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];
const WEEKDAY_PLURAL = ["понедельникам", "вторникам", "средам", "четвергам", "пятницам", "субботам", "воскресеньям"];

const BTN_MENU = "☰ Меню";
const BTN_DIGEST = "📩 Подборка сейчас";

const mapGenre = (raw) => GENRE_MAP[(raw || "").toLowerCase()] || "pop";
const mapCity = (raw) => CITY_MAP[raw] || "all";
const esc = (s) => (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function crimeaParts() {
  const d = new Date(Date.now() + 3 * 3600 * 1000);
  return { iso: d.toISOString().slice(0, 10), weekday: (d.getUTCDay() + 6) % 7 };
}

// ---------------------------------------------------------------------------
// Telegram API
// ---------------------------------------------------------------------------
async function tg(env, method, params) {
  try {
    const r = await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    return await r.json();
  } catch (e) {
    console.log("tg error", method, e);
    return null;
  }
}
const send = (env, chatId, text, markup, html = true) =>
  tg(env, "sendMessage", {
    chat_id: chatId, text,
    ...(html ? { parse_mode: "HTML" } : {}),
    link_preview_options: { is_disabled: true },
    ...(markup ? { reply_markup: markup } : {}),
  });
const editText = (env, chatId, msgId, text, markup, html = true) =>
  tg(env, "editMessageText", {
    chat_id: chatId, message_id: msgId, text,
    ...(html ? { parse_mode: "HTML" } : {}),
    link_preview_options: { is_disabled: true },
    ...(markup ? { reply_markup: markup } : {}),
  });
const editMarkup = (env, chatId, msgId, markup) =>
  tg(env, "editMessageReplyMarkup", { chat_id: chatId, message_id: msgId, reply_markup: markup });
const answerCb = (env, id, text, alert = false) =>
  tg(env, "answerCallbackQuery", { callback_query_id: id, ...(text ? { text, show_alert: alert } : {}) });

// ---------------------------------------------------------------------------
// Хранилище (Cloudflare KV)
// ---------------------------------------------------------------------------
const getSub = (env, id) => env.KV.get(`sub:${id}`, { type: "json" });
const setSub = (env, id, sub) => env.KV.put(`sub:${id}`, JSON.stringify(sub));
const delSub = (env, id) => env.KV.delete(`sub:${id}`);
const getDraft = async (env, id) =>
  (await env.KV.get(`draft:${id}`, { type: "json" })) || { genres: [], cities: [], freq: "ondemand", weekday: 4 };
const setDraft = (env, id, d) => env.KV.put(`draft:${id}`, JSON.stringify(d));
const delDraft = (env, id) => env.KV.delete(`draft:${id}`);

async function iterSubs(env) {
  const out = [];
  let cursor;
  do {
    const list = await env.KV.list({ prefix: "sub:", cursor });
    for (const k of list.keys) {
      const sub = await env.KV.get(k.name, { type: "json" });
      if (sub) out.push([Number(k.name.slice(4)), sub]);
    }
    cursor = list.list_complete ? null : list.cursor;
  } while (cursor);
  return out;
}
async function bumpCounter(env, name) {
  const stats = (await env.KV.get("stats", { type: "json" })) || {};
  stats[name] = (stats[name] || 0) + 1;
  await env.KV.put("stats", JSON.stringify(stats));
}
async function getCounter(env, name) {
  const stats = (await env.KV.get("stats", { type: "json" })) || {};
  return stats[name] || 0;
}

// ---------------------------------------------------------------------------
// События
// ---------------------------------------------------------------------------
async function fetchEvents() {
  const [evResp, setResp] = await Promise.all([fetch(EVENTS_URL), fetch(SETTINGS_URL).catch(() => null)]);
  const data = await evResp.json();
  let settings = {};
  if (setResp && setResp.ok) settings = await setResp.json().catch(() => ({}));
  const hidden = new Set(settings.hidden || []);
  const ov = (k) => settings[k] || {};
  const ovNames = ov("names"), ovTimes = ov("times"), ovPrices = ov("prices");
  const ovCities = ov("cities"), ovVenues = ov("venues"), ovGenres = ov("genres");
  const today = crimeaParts().iso;
  const out = [];
  for (const e of data) {
    const url = e.source_url || "";
    if (hidden.has(url) || !e.date || e.date < today) continue;
    const rawGenre = ovGenres[url] ?? e.genre;
    const rawCity = ovCities[url] ?? e.source_city;
    out.push({
      id: e.id, date: e.date,
      time: ovTimes[url] ?? e.time ?? "",
      artist: ovNames[url] ?? e.artist ?? "Концерт",
      venue: ovVenues[url] ?? e.venue ?? "",
      price: ovPrices[url] ?? e.price ?? "",
      sourceCity: rawCity || "",
      genre: mapGenre(rawGenre), city: mapCity(rawCity),
    });
  }
  out.sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));
  return out;
}

function filterEvents(events, genres, cities) {
  const today = crimeaParts().iso;
  const h = new Date(Date.now() + 3 * 3600 * 1000);
  h.setUTCDate(h.getUTCDate() + HORIZON_DAYS);
  const horizon = h.toISOString().slice(0, 10);
  const allG = !genres.length || genres.includes("all");
  const allC = !cities.length || cities.includes("all");
  return events.filter((e) => {
    if (!allG && !genres.includes(e.genre)) return false;
    if (!allC && e.city !== "all" && !cities.includes(e.city)) return false;
    return e.date >= today && e.date <= horizon;
  });
}

function priceText(p) {
  const low = (p || "").toLowerCase();
  if (!p || low.includes("бесплат") || low === "вход свободный") return "бесплатно";
  return p;
}

function formatDigest(events, genres, cities) {
  if (!events.length) {
    return "На ближайшую неделю по твоим фильтрам событий не нашлось 🤷\n" +
      "Загляни позже или измени подписку — /start\n\n" +
      `👉 <a href="${SITE}">Больше на Местов.Нет</a>`;
  }
  const gLabel = !genres.length || genres.includes("all")
    ? "любые жанры" : GENRE_ORDER.filter((g) => genres.includes(g)).map((g) => GENRE_LABELS[g]).join(", ");
  const cLabel = !cities.length || cities.includes("all")
    ? "весь Крым" : CITY_ORDER.filter((c) => cities.includes(c)).map((c) => CITY_LABELS[c]).join(", ");
  const lines = ["🎶 <b>Подборка живой музыки</b>", `<i>${esc(gLabel)} · ${esc(cLabel)}</i>`, ""];
  for (const e of events.slice(0, MAX_EVENTS)) {
    const [y, m, d] = e.date.split("-").map(Number);
    const wd = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
    let when = `${String(d).padStart(2, "0")} ${MONTHS_GEN[m - 1]} (${DOW[wd]})`;
    if (e.time) when += ` ${e.time}`;
    const place = [e.sourceCity, e.venue, priceText(e.price)].filter(Boolean).map(esc).join(" · ");
    const link = `${SITE}/event/${e.id}`;
    lines.push(`📅 ${when} — <a href="${link}"><b>${esc(e.artist)}</b></a>\n📍 ${place}\n`);
  }
  if (events.length > MAX_EVENTS)
    lines.push(`…и ещё ${events.length - MAX_EVENTS}. Все события — <a href="${SITE}">Местов.Нет</a>`);
  if (genres.length && !genres.includes("all")) {
    const gl = GENRE_ORDER.filter((g) => genres.includes(g))
      .map((g) => `<a href="${SITE}/genre.html?g=${g}">${GENRE_LABELS[g]}</a>`).join(" · ");
    lines.push(`\n🔎 На сайте: ${gl}`);
  }
  lines.push(`\n👉 <a href="${SITE}">Больше на Местов.Нет</a>`);
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Клавиатуры
// ---------------------------------------------------------------------------
const btn = (text, data) => ({ text, callback_data: data });
const MAIN_KB = { keyboard: [[{ text: BTN_MENU }, { text: BTN_DIGEST }]], resize_keyboard: true, is_persistent: true };

const mainMenuKb = () => ({
  inline_keyboard: [
    [btn("✏️ Настроить подписку", "cfg:start")],
    [btn("📩 Прислать подборку сейчас", "digest:now")],
    [btn("👀 Моя подписка", "sub:show")],
    [btn("🔕 Отписаться", "sub:stop")],
  ],
});

function genresKb(selected) {
  const rows = [];
  let row = [];
  for (const g of GENRE_ORDER) {
    row.push(btn((selected.includes(g) ? "✅ " : "") + GENRE_LABELS[g], `g:${g}`));
    if (row.length === 2) { rows.push(row); row = []; }
  }
  if (row.length) rows.push(row);
  rows.push([btn((selected.includes("all") ? "✅ " : "") + "Все жанры", "g:all")]);
  rows.push([btn("Далее ▶", "g:next")]);
  return { inline_keyboard: rows };
}

function citiesKb(selected) {
  const rows = [];
  let row = [];
  for (const c of CITY_ORDER) {
    row.push(btn((selected.includes(c) ? "✅ " : "") + CITY_LABELS[c], `c:${c}`));
    if (row.length === 2) { rows.push(row); row = []; }
  }
  if (row.length) rows.push(row);
  rows.push([btn((selected.includes("all") ? "✅ " : "") + "Весь Крым", "c:all")]);
  rows.push([btn("Далее ▶", "c:next")]);
  return { inline_keyboard: rows };
}

const freqKb = () => ({
  inline_keyboard: [
    [btn("📅 Каждый день", "f:daily")],
    [btn("🗓 Раз в неделю", "f:weekly")],
    [btn("✋ Только по запросу", "f:ondemand")],
  ],
});
const weekdayKb = () => ({ inline_keyboard: WEEKDAY_LABELS.map((l, i) => [btn(l, `w:${i}`)]) });

function toggle(selected, value) {
  if (value === "all") return selected.includes("all") ? [] : ["all"];
  selected = selected.filter((x) => x !== "all");
  return selected.includes(value) ? selected.filter((x) => x !== value) : [...selected, value];
}

function summaryText(sub) {
  const g = sub.genres.includes("all") || !sub.genres.length
    ? "любые" : GENRE_ORDER.filter((x) => sub.genres.includes(x)).map((x) => GENRE_LABELS[x]).join(", ");
  const c = sub.cities.includes("all") || !sub.cities.length
    ? "весь Крым" : CITY_ORDER.filter((x) => sub.cities.includes(x)).map((x) => CITY_LABELS[x]).join(", ");
  let when;
  if (sub.freq === "daily") when = "каждый день в 16:20";
  else if (sub.freq === "weekly") when = `по ${WEEKDAY_PLURAL[sub.weekday]} в 16:20`;
  else when = "только по запросу (/digest)";
  return `📋 <b>Твоя подписка</b>\nЖанры: ${esc(g)}\nГорода: ${esc(c)}\nЧастота: ${when}`;
}

// ---------------------------------------------------------------------------
// Логика
// ---------------------------------------------------------------------------
const WELCOME =
  "Привет! Я бот <b>Местов.Нет</b> 🎸\n" +
  "Присылаю подборки живой музыки Крыма под твой вкус.\n\n" +
  "Выбери жанры, города и как часто слать — а дальше я сам.\n" +
  `Источник: ${SITE}`;

async function sendDigest(env, chatId, sub) {
  const genres = sub ? sub.genres : ["all"];
  const cities = sub ? sub.cities : ["all"];
  let events;
  try {
    events = await fetchEvents();
  } catch (e) {
    await send(env, chatId, "Не удалось загрузить события с сайта, попробуй позже 🙏", null, false);
    return;
  }
  await send(env, chatId, formatDigest(filterEvents(events, genres, cities), genres, cities));
}

async function finishSub(env, chatId, msgId, draft) {
  if (!(await getSub(env, chatId))) await bumpCounter(env, "total_subscribed");
  const sub = { genres: draft.genres, cities: draft.cities, freq: draft.freq, weekday: draft.weekday ?? 4 };
  await setSub(env, chatId, sub);
  await delDraft(env, chatId);
  const tail = sub.freq === "ondemand"
    ? "\n\nБуду ждать команды /digest 👌"
    : "\n\nГотово! Первая подборка придёт по расписанию. Прислать сейчас — /digest";
  await editText(env, chatId, msgId, summaryText(sub) + tail);
}

async function onStats(env, chatId, userId) {
  if (userId !== Number(env.ADMIN_ID)) {
    await send(env, chatId, "Команда доступна только администратору.", null, false);
    return;
  }
  const freq = { daily: 0, weekly: 0, ondemand: 0 };
  const gc = {}, cc = {};
  GENRE_ORDER.forEach((g) => (gc[g] = 0));
  CITY_ORDER.forEach((c) => (cc[c] = 0));
  let total = 0, gAll = 0, cAll = 0;
  for (const [, s] of await iterSubs(env)) {
    total++;
    freq[s.freq] = (freq[s.freq] || 0) + 1;
    if (s.genres.includes("all") || !s.genres.length) gAll++;
    else s.genres.forEach((g) => { if (g in gc) gc[g]++; });
    if (s.cities.includes("all") || !s.cities.length) cAll++;
    else s.cities.forEach((c) => { if (c in cc) cc[c]++; });
  }
  const lines = [
    "📊 <b>Статистика</b>", "",
    `👥 Активных подписчиков: <b>${total}</b>`,
    `➕ Всего подписалось: ${await getCounter(env, "total_subscribed")}`,
    `➖ Всего отписалось: ${await getCounter(env, "total_unsubscribed")}`, "",
    "<b>По частоте:</b>",
    `• каждый день: ${freq.daily}`, `• раз в неделю: ${freq.weekly}`, `• по запросу: ${freq.ondemand}`, "",
    "<b>По жанрам:</b>", `• любые: ${gAll}`,
    ...GENRE_ORDER.map((g) => `• ${GENRE_LABELS[g]}: ${gc[g]}`),
    "", "<b>По городам:</b>", `• весь Крым: ${cAll}`,
    ...CITY_ORDER.map((c) => `• ${CITY_LABELS[c]}: ${cc[c]}`),
  ];
  await send(env, chatId, lines.join("\n"));
}

async function onCommand(env, chatId, userId, text) {
  const cmd = text.split(/\s+/)[0].replace("/", "").split("@")[0];
  if (cmd === "start") {
    await send(env, chatId, WELCOME, MAIN_KB);
    await send(env, chatId, "Что хочешь сделать?", mainMenuKb(), false);
  } else if (cmd === "help") {
    await send(env, chatId, "Команды:\n/start — меню\n/digest — подборка сейчас\n/stop — отписаться", mainMenuKb(), false);
  } else if (cmd === "digest") {
    await sendDigest(env, chatId, await getSub(env, chatId));
  } else if (cmd === "stop") {
    if (await getSub(env, chatId)) {
      await delSub(env, chatId);
      await bumpCounter(env, "total_unsubscribed");
      await send(env, chatId, "Отписал. Вернуться — /start", null, false);
    } else {
      await send(env, chatId, "У тебя и не было подписки. /start", null, false);
    }
  } else if (cmd === "stats") {
    await onStats(env, chatId, userId);
  }
}

async function onCallback(env, cb) {
  const data = cb.data;
  const chatId = cb.message.chat.id;
  const msgId = cb.message.message_id;
  const userId = cb.from.id;
  await answerCb(env, cb.id);

  if (data === "cfg:start") {
    const sub = await getSub(env, chatId);
    const draft = sub ? { ...sub } : { genres: [], cities: [], freq: "ondemand", weekday: 4 };
    await setDraft(env, chatId, draft);
    await editText(env, chatId, msgId,
      "Шаг 1/3. Какие <b>жанры</b> интересны? Можно несколько. Потом нажми «Далее».", genresKb(draft.genres));
  } else if (data.startsWith("g:")) {
    const val = data.slice(2);
    const draft = await getDraft(env, chatId);
    if (val === "next") {
      if (!draft.genres.length) { await answerCb(env, cb.id, "Выбери хотя бы один жанр (или «Все жанры»)", true); return; }
      await editText(env, chatId, msgId, "Шаг 2/3. В каких <b>городах</b>? Можно несколько.", citiesKb(draft.cities));
    } else {
      draft.genres = toggle(draft.genres, val);
      await setDraft(env, chatId, draft);
      await editMarkup(env, chatId, msgId, genresKb(draft.genres));
    }
  } else if (data.startsWith("c:")) {
    const val = data.slice(2);
    const draft = await getDraft(env, chatId);
    if (val === "next") {
      if (!draft.cities.length) { await answerCb(env, cb.id, "Выбери хотя бы один город (или «Весь Крым»)", true); return; }
      await editText(env, chatId, msgId, "Шаг 3/3. Как часто присылать подборку?", freqKb());
    } else {
      draft.cities = toggle(draft.cities, val);
      await setDraft(env, chatId, draft);
      await editMarkup(env, chatId, msgId, citiesKb(draft.cities));
    }
  } else if (data.startsWith("f:")) {
    const draft = await getDraft(env, chatId);
    draft.freq = data.slice(2);
    await setDraft(env, chatId, draft);
    if (draft.freq === "weekly") await editText(env, chatId, msgId, "В какой день недели присылать?", weekdayKb(), false);
    else await finishSub(env, chatId, msgId, draft);
  } else if (data.startsWith("w:")) {
    const draft = await getDraft(env, chatId);
    draft.weekday = Number(data.slice(2));
    await finishSub(env, chatId, msgId, draft);
  } else if (data === "digest:now") {
    await sendDigest(env, chatId, await getSub(env, chatId));
  } else if (data === "sub:show") {
    const sub = await getSub(env, chatId);
    await editText(env, chatId, msgId,
      sub ? summaryText(sub) : "Подписки пока нет. Нажми «Настроить подписку».", mainMenuKb());
  } else if (data === "sub:stop") {
    if (await getSub(env, chatId)) {
      await delSub(env, chatId);
      await bumpCounter(env, "total_unsubscribed");
      await editText(env, chatId, msgId, "Отписал. Вернуться — /start", null, false);
    } else {
      await editText(env, chatId, msgId, "Подписки и не было. /start", null, false);
    }
  }
}

async function processUpdate(env, update) {
  try {
    if (update.callback_query) return await onCallback(env, update.callback_query);
    const msg = update.message || update.edited_message;
    if (!msg) return;
    const chatId = msg.chat.id;
    const userId = (msg.from && msg.from.id) || 0;
    const text = (msg.text || "").trim();
    if (!text) return;
    if (text.startsWith("/")) await onCommand(env, chatId, userId, text);
    else if (text === BTN_DIGEST) await sendDigest(env, chatId, await getSub(env, chatId));
    else await send(env, chatId, "Что хочешь сделать?", mainMenuKb(), false);
  } catch (e) {
    console.log("update error", e);
  }
}

async function runCron(env) {
  const { weekday } = crimeaParts();
  for (const [chatId, sub] of await iterSubs(env)) {
    if (sub.freq === "daily" || (sub.freq === "weekly" && sub.weekday === weekday)) {
      try { await sendDigest(env, chatId, sub); } catch (e) { console.log("digest failed", chatId, e); }
    }
  }
}

// ---------------------------------------------------------------------------
// Точки входа Cloudflare Workers
// ---------------------------------------------------------------------------
export default {
  async fetch(request, env, ctx) {
    if (request.method === "POST") {
      if (env.WEBHOOK_SECRET &&
          request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      let update;
      try { update = await request.json(); } catch (e) { return new Response("ok"); }
      ctx.waitUntil(processUpdate(env, update));
      return new Response("ok");
    }
    return new Response("Местов.Нет бот работает 🎸");
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(runCron(env));
  },
};
