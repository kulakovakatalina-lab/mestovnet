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
const MODERATION_URL = `${SITE}/moderation.json`;
const EVENTS_API_PATH = "/api/events";
const CATALOG_SYNC_PATH = "/internal/catalog-sync";
const CATALOG_KEY = "catalog:events:v1";
const PUBLIC_SITE_ORIGINS = new Set(["https://mestov.net", "https://www.mestov.net"]);
const GITHUB_API = "https://api.github.com";
const MODERATION_PUBLISH_WORKFLOW = "publish-moderation.yml";
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
// Публичный каталог событий
// ---------------------------------------------------------------------------
// KV содержит последний опубликованный снимок. Полный events.json остаётся
// резервной копией и источником данных для генератора статических страниц.
function catalogCorsHeaders(request) {
  const origin = request.headers.get("Origin");
  const headers = new Headers({
    "Cache-Control": "public, max-age=60, s-maxage=300",
    "Vary": "Origin",
  });
  if (origin && PUBLIC_SITE_ORIGINS.has(origin)) headers.set("Access-Control-Allow-Origin", origin);
  return headers;
}

function catalogEvents(events, searchParams, now = crimeaParts().iso) {
  const venue = (searchParams.get("venue") || "").trim().toLocaleLowerCase("ru-RU");
  const city = (searchParams.get("city") || "").trim().toLocaleLowerCase("ru-RU");
  const genre = (searchParams.get("genre") || "").trim().toLocaleLowerCase("ru-RU");
  const includePast = searchParams.get("include") === "past";
  const requestedLimit = Number.parseInt(searchParams.get("limit") || "100", 10);
  const limit = Number.isFinite(requestedLimit) ? Math.min(Math.max(requestedLimit, 1), 200) : 100;

  return events
    .filter((event) => {
      if (!event || typeof event !== "object" || !isoDate(event.date)) return false;
      if (!includePast && event.date < now) return false;
      if (venue && String(event.venue || "").trim().toLocaleLowerCase("ru-RU") !== venue) return false;
      if (city && String(event.source_city || "").trim().toLocaleLowerCase("ru-RU") !== city) return false;
      if (genre && String(event.genre || "").trim().toLocaleLowerCase("ru-RU") !== genre) return false;
      return true;
    })
    .sort((a, b) => `${a.date}${a.time || ""}`.localeCompare(`${b.date}${b.time || ""}`))
    .slice(0, limit);
}

async function eventsApiResponse(request, env) {
  const snapshot = await env.KV.get(CATALOG_KEY, { type: "json" });
  if (!snapshot || !Array.isArray(snapshot.events)) {
    return Response.json(
      { error: "catalog is not synchronized yet" },
      { status: 503, headers: catalogCorsHeaders(request) },
    );
  }
  return Response.json(catalogEvents(snapshot.events, new URL(request.url).searchParams), {
    headers: catalogCorsHeaders(request),
  });
}

async function catalogSyncResponse(request, env) {
  if (!env.CATALOG_SYNC_TOKEN || request.headers.get("Authorization") !== `Bearer ${env.CATALOG_SYNC_TOKEN}`) {
    return new Response("forbidden", { status: 403 });
  }
  let events;
  try { events = await request.json(); } catch (_) { return Response.json({ error: "body must be a JSON array" }, { status: 400 }); }
  if (!Array.isArray(events) || events.some((event) => !event || typeof event !== "object" || !isoDate(event.date))) {
    return Response.json({ error: "events must be an array of dated event objects" }, { status: 400 });
  }
  await env.KV.put(CATALOG_KEY, JSON.stringify({ events, synchronized_at: new Date().toISOString() }));
  return Response.json({ ok: true, events: events.length });
}

// ---------------------------------------------------------------------------
// Закрытая еженедельная аналитика
// ---------------------------------------------------------------------------
const ANALYTICS_PATH = "/api/analytics/weekly";
const REGION_ONLY_LOCATIONS = new Set(["крым"]);

function isoDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value ? null : value;
}

function addDays(iso, days) {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function lastCompletedWeek(now = new Date()) {
  // Europe/Moscow is UTC+3 year-round. getUTCDay() is calculated after the
  // shift so a Sunday in Crimea remains Sunday even when the Worker is in UTC.
  const crimeaNow = new Date(now.getTime() + 3 * 3600 * 1000);
  const weekday = (crimeaNow.getUTCDay() + 6) % 7; // Monday = 0
  const today = crimeaNow.toISOString().slice(0, 10);
  const lastSunday = addDays(today, -(weekday + 1));
  return { from: addDays(lastSunday, -6), to: lastSunday };
}

function analyticsPeriod(searchParams, now = new Date()) {
  const fromParam = searchParams.get("date_from");
  const toParam = searchParams.get("date_to");
  if (!fromParam && !toParam) return lastCompletedWeek(now);
  const from = isoDate(fromParam);
  const to = isoDate(toParam);
  if (!from || !to || from > to) return null;
  return { from, to };
}

function isInPeriod(value, period) {
  const day = typeof value === "string" ? value.slice(0, 10) : "";
  return isoDate(day) !== null && day >= period.from && day <= period.to;
}

function analyticsSource(event) {
  if (event.source_channel) return String(event.source_channel);
  try { return new URL(event.source_url).hostname || "unknown"; } catch (_) { return "unknown"; }
}

function isUnknownLocation(event) {
  const city = String(event.source_city || "").trim();
  return !city || REGION_ONLY_LOCATIONS.has(city.toLocaleLowerCase("ru-RU"));
}

function buildWeeklyAnalytics(events, queue, decisions, period, generatedAt = new Date()) {
  const previous = { from: addDays(period.from, -(Math.round((Date.parse(`${period.to}T00:00:00Z`) - Date.parse(`${period.from}T00:00:00Z`)) / 86400000) + 1)), to: addDays(period.from, -1) };
  const currentEvents = events.filter((event) => isInPeriod(event.post_date, period));
  const previousEvents = events.filter((event) => isInPeriod(event.post_date, previous));
  const currentBySource = new Map();
  const previousBySource = new Map();
  const rejectedBySource = new Map();
  const unknownBySource = new Map();
  const increment = (map, key) => map.set(key, (map.get(key) || 0) + 1);
  const sourceByUrl = new Map(events.concat(queue).filter((event) => event.source_url)
    .map((event) => [event.source_url, analyticsSource(event)]));

  for (const event of currentEvents) {
    const source = analyticsSource(event);
    increment(currentBySource, source);
    if (isUnknownLocation(event)) increment(unknownBySource, source);
  }
  for (const event of previousEvents) increment(previousBySource, analyticsSource(event));
  for (const decision of decisions) {
    if (decision.status !== "rejected" || !isInPeriod(decision.decided_at, period)) continue;
    increment(rejectedBySource, sourceByUrl.get(decision.source_url) || "unknown");
  }

  const sources = new Set([...currentBySource.keys(), ...previousBySource.keys(), ...rejectedBySource.keys()]);
  const sourceRows = [...sources].map((source) => ({
    source,
    events_added: currentBySource.get(source) || 0,
    previous_period: previousBySource.get(source) || 0,
    rejected: rejectedBySource.get(source) || 0,
    unknown_location: unknownBySource.get(source) || 0,
  })).sort((a, b) => b.events_added - a.events_added || a.source.localeCompare(b.source, "ru"));

  const cities = new Map();
  const previousCities = new Map();
  for (const event of currentEvents) if (!isUnknownLocation(event)) increment(cities, String(event.source_city).trim());
  for (const event of previousEvents) if (!isUnknownLocation(event)) increment(previousCities, String(event.source_city).trim());
  const cityRows = [...cities.entries()].map(([city, count]) => ({ city, events: count, previous_period: previousCities.get(city) || 0 }))
    .sort((a, b) => b.events - a.events || a.city.localeCompare(b.city, "ru"));
  const total = currentEvents.length;
  const previousTotal = previousEvents.length;
  const unmoderatedHasDates = queue.every((event) => isoDate((event.post_date || "").slice(0, 10)) !== null);

  return {
    period,
    previous_period: previous,
    events_added: {
      total,
      previous_period: previousTotal,
      change_absolute: total - previousTotal,
      change_percent: previousTotal ? Number((((total - previousTotal) / previousTotal) * 100).toFixed(1)) : null,
    },
    moderation: {
      new_unmoderated: unmoderatedHasDates ? queue.filter((event) => isInPeriod(event.post_date, period)).length : null,
      current_backlog: queue.length,
      previous_backlog: null,
    },
    moderation_period_data_available: unmoderatedHasDates,
    cities: cityRows,
    unknown_location: currentEvents.filter(isUnknownLocation).length,
    sources: sourceRows,
    // В данных нет журнала правок карточки и признака публикации без правок.
    source_quality_data_available: false,
    generated_at: `${new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Moscow", dateStyle: "short", timeStyle: "medium", hour12: false }).format(generatedAt).replace(" ", "T")}+03:00`,
  };
}

async function weeklyAnalyticsResponse(request, env, now = new Date()) {
  if (!env.ANALYTICS_TOKEN || request.headers.get("Authorization") !== `Bearer ${env.ANALYTICS_TOKEN}`) {
    return new Response("forbidden", { status: 403 });
  }
  const period = analyticsPeriod(new URL(request.url).searchParams, now);
  if (!period) return Response.json({ error: "date_from and date_to must be valid YYYY-MM-DD dates, with date_from <= date_to" }, { status: 400 });
  try {
    const [eventsResponse, queue] = await Promise.all([fetch(EVENTS_URL), fetchModeration()]);
    if (!eventsResponse.ok) throw new Error(`events fetch: ${eventsResponse.status}`);
    const events = await eventsResponse.json();
    const decisions = await listModerationDecisions(env);
    return Response.json(buildWeeklyAnalytics(Array.isArray(events) ? events : [], queue, decisions, period, now));
  } catch (error) {
    console.log("weekly analytics failed", error);
    return Response.json({ error: "analytics data is temporarily unavailable" }, { status: 503 });
  }
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
const sendPhoto = (env, chatId, photo, caption = "") =>
  tg(env, "sendPhoto", {
    chat_id: chatId, photo, caption,
    ...(caption ? { parse_mode: "HTML" } : {}),
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

// Решения администратора по спорным карточкам. Они хранятся в KV, а ночной
// парсер забирает их через защищённый endpoint Worker-а.
const getModerationDecision = (env, eventId) => env.KV.get(`moderation:${eventId}`, { type: "json" });
const setModerationDecision = (env, eventId, decision) =>
  env.KV.put(`moderation:${eventId}`, JSON.stringify(decision));

// Запускает короткую публикацию сразу после решения модератора. Если секрет
// не настроен или GitHub временно недоступен, ночной запуск остаётся fallback.
async function triggerModerationPublish(env) {
  const token = env.GITHUB_MODERATION_TOKEN;
  const repository = env.GITHUB_REPOSITORY || "kulakovakatalina-lab/mestovnet";
  if (!token) {
    console.log("GITHUB_MODERATION_TOKEN is not configured; waiting for nightly sync");
    return false;
  }
  try {
    const response = await fetch(
      `${GITHUB_API}/repos/${repository}/actions/workflows/${MODERATION_PUBLISH_WORKFLOW}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          // GitHub REST API отклоняет запросы из Worker-ов без User-Agent.
          "User-Agent": "MestovNet-Moderation-Worker",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "main" }),
      },
    );
    if (!response.ok) {
      console.log("moderation publish dispatch failed", response.status, await response.text());
      return false;
    }
    return true;
  } catch (error) {
    console.log("moderation publish dispatch error", error);
    return false;
  }
}

async function listModerationDecisions(env) {
  const decisions = [];
  let cursor;
  do {
    const list = await env.KV.list({ prefix: "moderation:", cursor });
    for (const key of list.keys) {
      const decision = await env.KV.get(key.name, { type: "json" });
      if (decision) decisions.push(decision);
    }
    cursor = list.list_complete ? null : list.cursor;
  } while (cursor);
  return decisions;
}

// Подписки на напоминания об конкретных событиях («Хочу пойти»):
//   evsub:<eventId>  -> [chatId, ...]   — кому напоминать про это событие
//   evsubs:<chatId>  -> [eventId, ...]  — на какие события подписан этот чат
const getEvSub = (env, eid) => env.KV.get(`evsub:${eid}`, { type: "json" });
const setEvSub = (env, eid, chats) => env.KV.put(`evsub:${eid}`, JSON.stringify(chats));
const delEvSub = (env, eid) => env.KV.delete(`evsub:${eid}`);
const getUserEvents = async (env, chatId) => (await env.KV.get(`evsubs:${chatId}`, { type: "json" })) || [];
const setUserEvents = (env, chatId, evs) => env.KV.put(`evsubs:${chatId}`, JSON.stringify(evs));
const delUserEvents = (env, chatId) => env.KV.delete(`evsubs:${chatId}`);

async function addEventSub(env, chatId, eventId) {
  const chats = (await getEvSub(env, eventId)) || [];
  if (!chats.includes(chatId)) {
    chats.push(chatId);
    await setEvSub(env, eventId, chats);
  }
  const evs = await getUserEvents(env, chatId);
  if (!evs.includes(eventId)) {
    evs.push(eventId);
    await setUserEvents(env, chatId, evs);
  }
}

async function removeEventSub(env, chatId, eventId) {
  const chats = (await getEvSub(env, eventId)) || [];
  const i = chats.indexOf(chatId);
  if (i !== -1) {
    chats.splice(i, 1);
    if (chats.length) await setEvSub(env, eventId, chats);
    else await delEvSub(env, eventId);
  }
  const evs = await getUserEvents(env, chatId);
  const j = evs.indexOf(eventId);
  if (j !== -1) {
    evs.splice(j, 1);
    if (evs.length) await setUserEvents(env, chatId, evs);
    else await delUserEvents(env, chatId);
  }
}

async function iterEventSubs(env) {
  const out = [];
  let cursor;
  do {
    const list = await env.KV.list({ prefix: "evsub:", cursor });
    for (const k of list.keys) {
      const chats = await env.KV.get(k.name, { type: "json" });
      if (chats && chats.length) out.push([k.name.slice(6), chats]);
    }
    cursor = list.list_complete ? null : list.cursor;
  } while (cursor);
  return out;
}

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
  const cancelled = new Set(settings.cancelled || []);
  const ov = (k) => settings[k] || {};
  const ovNames = ov("names"), ovTimes = ov("times"), ovPrices = ov("prices");
  const ovCities = ov("cities"), ovVenues = ov("venues"), ovGenres = ov("genres");
  const today = crimeaParts().iso;
  const out = [];
  for (const e of data) {
    const url = e.source_url || "";
    if (hidden.has(url) || cancelled.has(url) || !e.date || e.date < today) continue;
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
      updatedAt: e.updated_at || "",
    });
  }
  out.sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));
  return out;
}

async function fetchModeration() {
  const response = await fetch(MODERATION_URL);
  if (!response.ok) throw new Error(`moderation fetch: ${response.status}`);
  const data = await response.json();
  return Array.isArray(data) ? data : [];
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

function fmtWhen(e) {
  const [y, m, d] = e.date.split("-").map(Number);
  const wd = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
  let when = `${String(d).padStart(2, "0")} ${MONTHS_GEN[m - 1]} (${DOW[wd]})`;
  if (e.time) when += ` ${e.time}`;
  return when;
}

function fmtDateShort(e) {
  const [, m, d] = e.date.split("-").map(Number);
  return `${d} ${MONTHS_GEN[m - 1]}`;
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
    const place = [e.sourceCity, e.venue, priceText(e.price)].filter(Boolean).map(esc).join(" · ");
    const link = `${SITE}/event/${e.id}`;
    lines.push(`📅 ${fmtWhen(e)} — <a href="${link}"><b>${esc(e.artist)}</b></a>\n📍 ${place}\n`);
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

// Тексты напоминаний «Хочу пойти» — за неделю/3 дня/день до события.
function reminderText(kind, e) {
  const link = `${SITE}/event/${e.id}`;
  const artist = esc(e.artist);
  const venue = esc(e.venue);
  const city = esc(e.sourceCity);
  const price = priceText(e.price);
  if (kind === "t7") {
    return [
      "🎸 Через неделю — концерт, на который ты собираешься:",
      "",
      `<b>${artist}</b>`,
      fmtWhen(e),
      `📍 ${venue} · ${city}`,
      ...(price ? [esc(price)] : []),
      "",
      `👉 <a href="${link}">Подробнее на Местов.Нет</a>`,
    ].join("\n");
  }
  if (kind === "t3") {
    return [
      `⏳ Через 3 дня — <b>${artist}</b> в ${venue}.`,
      fmtWhen(e),
      "",
      "Если билет или компания ещё не в кармане — самое время этим заняться.",
      link,
    ].join("\n");
  }
  return [
    `🔥 Завтра — <b>${artist}</b>`,
    fmtWhen(e),
    `📍 ${venue}, ${city}`,
    ...(price ? [esc(price)] : []),
    "",
    "Увидимся там.",
    link,
  ].join("\n");
}

// ---------------------------------------------------------------------------
// Клавиатуры
// ---------------------------------------------------------------------------
const btn = (text, data) => ({ text, callback_data: data });
const MAIN_KB = { keyboard: [[{ text: BTN_MENU }, { text: BTN_DIGEST }]], resize_keyboard: true, is_persistent: true };
const cancelEventKb = (eventId) => ({ inline_keyboard: [[btn("❌ Отменить напоминания", `ev:cancel:${eventId}`)]] });

const moderationStartKb = () => ({ inline_keyboard: [[btn("Разобрать события ▶", "mod:next:0")]] });

function moderationCard(event, position, total) {
  const details = [
    `🔎 <b>Модерация ${position + 1} из ${total}</b>`,
    "",
    `<b>${esc(event.artist || "Без названия")}</b>`,
    `📅 ${esc(event.date || "дата не указана")}${event.time ? ` · ${esc(event.time)}` : ""}`,
    `📍 ${esc([event.source_city, event.venue].filter(Boolean).join(" · ") || "место не указано")}`,
    `🎫 ${esc(event.price || "стоимость не указана")}`,
    event.genre && `🎵 ${esc(event.genre)}`,
    event.event_type && `Тип: ${esc(event.event_type)}`,
  ].filter(Boolean);
  return details.join("\n");
}

function moderationFooter(event) {
  const lines = [];
  if (event.reasons && event.reasons.length) {
    lines.push(`⚠️ ${event.reasons.map(esc).join(", ")}`);
  }
  if (event.source_url) {
    lines.push(`🔗 <a href="${esc(event.source_url)}">Открыть первоисточник</a>`);
  }
  return lines.join("\n");
}

function splitForTelegram(text, limit = 4000) {
  const chunks = [];
  let rest = text;
  while (rest.length > limit) {
    const cut = Math.max(rest.lastIndexOf("\n", limit), rest.lastIndexOf(" ", limit), limit);
    chunks.push(rest.slice(0, cut));
    rest = rest.slice(cut).trimStart();
  }
  if (rest) chunks.push(rest);
  return chunks;
}

function moderationCardKb(eventId, nextPosition) {
  return { inline_keyboard: [
    [btn("✅ Одобрить", `mod:a:${eventId}:${nextPosition}`), btn("❌ Отклонить", `mod:r:${eventId}:${nextPosition}`)],
    [btn("Пропустить ›", `mod:next:${nextPosition}`)],
  ]};
}

const mainMenuKb = () => ({
  inline_keyboard: [
    [btn("✏️ Настроить подписку", "cfg:start")],
    [btn("📩 Прислать подборку сейчас", "digest:now")],
    [btn("🎫 Мои события", "ev:list")],
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

async function sendDigest(env, chatId, sub, onDemand = true) {
  const genres = sub ? sub.genres : ["all"];
  const cities = sub ? sub.cities : ["all"];
  let events;
  try {
    events = await fetchEvents();
  } catch (e) {
    await send(env, chatId, "Не удалось загрузить события с сайта, попробуй позже 🙏", null, false);
    return;
  }
  let filtered = filterEvents(events, genres, cities);

  // Для плановых рассылок — только события, изменившиеся/появившиеся с прошлого раза.
  // Первая плановая рассылка показывает всё и устанавливает базу; /digest по
  // запросу всегда работает как раньше — все события на 7 дней вперёд.
  if (!onDemand && sub) {
    const lastSentAt = sub.lastSentAt;
    sub.lastSentAt = new Date().toISOString();
    await setSub(env, chatId, sub);
    if (lastSentAt) {
      filtered = filtered.filter((e) => (e.updatedAt || "") >= lastSentAt);
      if (!filtered.length) return;
    }
  }

  await send(env, chatId, formatDigest(filtered, genres, cities));
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

async function handleEventStart(env, chatId, eventId) {
  let events;
  try {
    events = await fetchEvents();
  } catch (e) {
    await send(env, chatId, "Не удалось загрузить события с сайта, попробуй позже 🙏", null, false);
    return;
  }
  const e = events.find((x) => x.id === eventId);
  if (!e) {
    await send(env, chatId, "Не нашёл это событие — возможно, оно уже прошло или отменено.", null, false);
    return;
  }
  await addEventSub(env, chatId, eventId);
  const place = [e.venue, e.sourceCity].filter(Boolean).map(esc).join(", ");
  const text =
    `Записал! <b>${esc(e.artist)}</b>\n${fmtWhen(e)}${place ? `\n📍 ${place}` : ""}\n\n` +
    "Напомню за неделю, за 3 дня и за день до концерта.";
  await send(env, chatId, text, cancelEventKb(eventId));
}

async function showModerationCard(env, chatId, msgId, position) {
  const queue = await fetchModeration();
  while (position < queue.length) {
    const event = queue[position];
    const decision = await getModerationDecision(env, event.id);
    if (!decision) {
      const image = event.image && (event.image.startsWith("http") ? event.image : `${SITE}${event.image}`);
      if (image) {
        const poster = await sendPhoto(env, chatId, image, "🎨 <b>Постер события</b>");
        if (!poster || !poster.ok) console.log("moderation poster failed", event.id);
      }
      await send(env, chatId, moderationCard(event, position, queue.length));
      if (event.description) {
        for (const part of splitForTelegram(event.description)) {
          await send(env, chatId, `📝 <b>Описание</b>\n${esc(part)}`);
        }
      }
      await send(env, chatId, moderationFooter(event) || "Проверьте карточку и примите решение.",
        moderationCardKb(event.id, position + 1));
      return;
    }
    position++;
  }
  await send(env, chatId,
    "✅ В очереди больше нет неразобранных карточек. Одобренные события публикуются автоматически.",
    null, false);
}

async function moderateEvent(env, cb, status, eventId, nextPosition) {
  const queue = await fetchModeration();
  const event = queue.find((item) => item.id === eventId);
  if (!event) {
    await answerCb(env, cb.id, "Карточка уже исчезла из очереди. Откройте следующую.", true);
    await showModerationCard(env, cb.message.chat.id, cb.message.message_id, nextPosition);
    return;
  }
  await setModerationDecision(env, eventId, {
    event_id: eventId,
    source_url: event.source_url || "",
    reasons: event.reasons || [],
    status,
    decided_at: new Date().toISOString(),
  });
  const publishStarted = await triggerModerationPublish(env);
  await answerCb(env, cb.id, status === "approved" ? "Одобрено" : "Отклонено");
  await editText(env, cb.message.chat.id, cb.message.message_id,
    status === "approved"
      ? (publishStarted ? "✅ Событие одобрено. Публикую на сайте…" : "✅ Событие одобрено.")
      : (publishStarted ? "❌ Событие отклонено. Обновляю сайт…" : "❌ Событие отклонено."),
    null, false);
  await showModerationCard(env, cb.message.chat.id, cb.message.message_id, nextPosition);
}

async function onCommand(env, chatId, userId, text) {
  const parts = text.split(/\s+/);
  const cmd = parts[0].replace("/", "").split("@")[0];
  if (cmd === "start") {
    const payload = parts[1] || "";
    if (payload.startsWith("event_")) {
      await handleEventStart(env, chatId, payload.slice("event_".length));
    } else {
      await send(env, chatId, WELCOME, MAIN_KB);
      await send(env, chatId, "Что хочешь сделать?", mainMenuKb(), false);
    }
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
  } else if (cmd === "publish_test") {
    if (userId !== Number(env.ADMIN_ID)) {
      await send(env, chatId, "Команда доступна только администратору.", null, false);
      return;
    }
    const started = await triggerModerationPublish(env);
    await send(env, chatId,
      started
        ? "✅ Тест публикации запущен. Проверь GitHub Actions: Publish moderation decision. Афиша не изменится, если новых решений нет."
        : "⚠️ Не удалось запустить тест публикации. Проверь секрет GITHUB_MODERATION_TOKEN и логи Worker-а.",
      null, false);
  } else if (cmd === "moderation") {
    if (userId !== Number(env.ADMIN_ID)) {
      await send(env, chatId, "Команда доступна только администратору.", null, false);
      return;
    }
    await send(env, chatId, "🔎 <b>Очередь модерации</b>\nНажми, чтобы начать разбор.", moderationStartKb());
  }
}

async function onCallback(env, cb) {
  const data = cb.data;
  const chatId = cb.message.chat.id;
  const msgId = cb.message.message_id;
  const userId = cb.from.id;

  if (data.startsWith("mod:")) {
    if (userId !== Number(env.ADMIN_ID)) {
      await answerCb(env, cb.id, "Модерация доступна только администратору.", true);
      return;
    }
    if (data === "mod:start") {
      await answerCb(env, cb.id);
      await showModerationCard(env, chatId, msgId, 0);
      return;
    }
    if (data.startsWith("mod:next:")) {
      await answerCb(env, cb.id);
      await editMarkup(env, chatId, msgId, { inline_keyboard: [] });
      await showModerationCard(env, chatId, msgId, Number(data.slice("mod:next:".length)) || 0);
      return;
    }
    const match = /^mod:([ar]):([^:]+):(\d+)$/.exec(data);
    if (match) {
      await moderateEvent(env, cb, match[1] === "a" ? "approved" : "rejected", match[2], Number(match[3]));
      return;
    }
    return;
  }

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
  } else if (data.startsWith("ev:cancel:")) {
    const eid = data.slice("ev:cancel:".length);
    await removeEventSub(env, chatId, eid);
    await editText(env, chatId, msgId, "Напоминания отменены.", null, false);
  } else if (data === "ev:list") {
    const evIds = await getUserEvents(env, chatId);
    if (!evIds.length) {
      await editText(env, chatId, msgId,
        "Пока нет подписок на события. Нажми «Хочу пойти» на странице интересного концерта на сайте.", mainMenuKb(), false);
      return;
    }
    let events;
    try { events = await fetchEvents(); } catch (e) { events = []; }
    const byId = Object.fromEntries(events.map((x) => [x.id, x]));
    const rows = evIds.map((eid) => {
      const e = byId[eid];
      const label = e ? `${e.artist} — ${fmtDateShort(e)}` : eid;
      return [btn(`❌ ${label}`, `ev:cancel:${eid}`)];
    });
    rows.push([btn("‹ Назад", "menu:back")]);
    await editText(env, chatId, msgId, "🎫 <b>Твои события</b>\nНажми, чтобы отменить напоминания:", { inline_keyboard: rows });
  } else if (data === "menu:back") {
    await editText(env, chatId, msgId, "Что хочешь сделать?", mainMenuKb(), false);
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
      try { await sendDigest(env, chatId, sub, false); } catch (e) { console.log("digest failed", chatId, e); }
    }
  }
}

// Напоминания «Хочу пойти» — за 7/3/1 день до события. Кроном бежим раз в
// сутки, поэтому просто сверяем разницу дат "в лоб": попадание ровно в 7/3/1
// происходит один раз на событие, дополнительный учёт "уже отправлено" не нужен.
async function runEventReminders(env) {
  let events;
  try {
    events = await fetchEvents();
  } catch (e) {
    console.log("event reminders: fetch failed", e);
    return;
  }
  const byId = Object.fromEntries(events.map((x) => [x.id, x]));
  const today = crimeaParts().iso;
  for (const [eventId, chats] of await iterEventSubs(env)) {
    const e = byId[eventId];
    if (!e) {
      // событие прошло, отменено или скрыто — снимаем все напоминания по нему
      for (const chatId of chats) await removeEventSub(env, chatId, eventId);
      continue;
    }
    const diffDays = Math.round((Date.parse(e.date) - Date.parse(today)) / 86400000);
    const kind = diffDays === 7 ? "t7" : diffDays === 3 ? "t3" : diffDays === 1 ? "t1" : null;
    if (!kind) continue;
    const text = reminderText(kind, e);
    for (const chatId of chats) {
      try { await send(env, chatId, text, cancelEventKb(eventId)); } catch (err) { console.log("reminder failed", chatId, eventId, err); }
    }
  }
}

// ---------------------------------------------------------------------------
// Точки входа Cloudflare Workers
// ---------------------------------------------------------------------------
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS" && url.pathname === EVENTS_API_PATH) {
      const headers = catalogCorsHeaders(request);
      headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
      return new Response(null, { status: 204, headers });
    }
    if (request.method === "GET" && url.pathname === EVENTS_API_PATH) {
      return eventsApiResponse(request, env);
    }
    if (request.method === "POST" && url.pathname === CATALOG_SYNC_PATH) {
      return catalogSyncResponse(request, env);
    }
    if (request.method === "GET" && url.pathname === ANALYTICS_PATH) {
      return weeklyAnalyticsResponse(request, env);
    }
    if (request.method === "GET" && url.pathname === "/moderation/decisions") {
      const auth = request.headers.get("Authorization");
      if (!env.MODERATION_SYNC_TOKEN || auth !== `Bearer ${env.MODERATION_SYNC_TOKEN}`) {
        return new Response("forbidden", { status: 403 });
      }
      return Response.json({ decisions: await listModerationDecisions(env) });
    }
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
    ctx.waitUntil(runEventReminders(env));
  },
};

// Named exports keep the date and authorization behaviour unit-testable. They
// are ignored by Cloudflare Workers at runtime.
export {
  analyticsPeriod, buildWeeklyAnalytics, lastCompletedWeek, weeklyAnalyticsResponse,
  catalogEvents, catalogSyncResponse, eventsApiResponse,
};
