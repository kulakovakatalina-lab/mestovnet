/**
 * \u0422\u0435\u043b\u0435\u0433\u0440\u0430\u043c-\u0431\u043e\u0442 \u00ab\u041c\u0435\u0441\u0442\u043e\u0432.\u041d\u0435\u0442\u00bb \u0434\u043b\u044f Cloudflare Workers.
 *
 * \u041c\u0433\u043d\u043e\u0432\u0435\u043d\u043d\u044b\u0439 \u0431\u0435\u0441\u043f\u043b\u0430\u0442\u043d\u044b\u0439 serverless:
 *   \u2022 webhook \u2014 Telegram \u0448\u043b\u0451\u0442 \u0430\u043f\u0434\u0435\u0439\u0442\u044b \u043d\u0430 Worker (\u043c\u0433\u043d\u043e\u0432\u0435\u043d\u043d\u044b\u0439 \u043e\u0442\u0432\u0435\u0442);
 *   \u2022 Cron Trigger \u2014 \u0440\u0430\u0441\u0441\u044b\u043b\u043a\u0430 \u0432 13:20 UTC (16:20 \u041a\u0440\u044b\u043c);
 *   \u2022 \u0445\u0440\u0430\u043d\u0438\u043b\u0438\u0449\u0435 \u2014 Cloudflare KV (\u0431\u0438\u043d\u0434\u0438\u043d\u0433 \u0441 \u0438\u043c\u0435\u043d\u0435\u043c KV).
 *
 * \u041f\u0435\u0440\u0435\u043c\u0435\u043d\u043d\u044b\u0435/\u0441\u0435\u043a\u0440\u0435\u0442\u044b Worker:
 *   BOT_TOKEN, WEBHOOK_SECRET, ADMIN_ID
 * \u0411\u0438\u043d\u0434\u0438\u043d\u0433 KV namespace: KV
 */

const SITE = "https://mestov.net";
const EVENTS_URL = `${SITE}/events.json`;
const SETTINGS_URL = `${SITE}/settings.json`;
const MAX_EVENTS = 25;
const HORIZON_DAYS = 7;

const GENRE_MAP = {
  "\u0434\u0436\u0430\u0437": "jazz",
  "\u0440\u043e\u043a": "rock", "\u0440\u0443\u0441\u0441\u043a\u0438\u0439 \u0440\u043e\u043a": "rock", "\u043f\u0430\u043d\u043a-\u0440\u043e\u043a": "rock",
  "\u0438\u043d\u0434\u0438-\u0440\u043e\u043a": "rock", "\u043c\u0435\u0442\u0430\u043b": "rock", "\u0438\u043d\u0434\u0438": "rock", "\u0430\u0432\u0442\u043e\u0440\u0441\u043a\u0430\u044f": "rock",
  "\u043a\u043b\u0430\u0441\u0441\u0438\u043a\u0430": "classic", "\u0445\u043e\u0440\u043e\u0432\u0430\u044f": "classic", "\u043c\u0435\u0434\u0438\u0442\u0430\u0442\u0438\u0432\u043d\u0430\u044f": "classic",
  "\u043f\u043e\u043f": "pop", "\u043f\u043e\u043f-\u0440\u043e\u043a": "pop", "\u043b\u0430\u0443\u043d\u0436": "pop", "\u0445\u0438\u043f-\u0445\u043e\u043f": "pop",
  "\u043a\u0430\u0432\u0435\u0440\u044b": "pop", "\u044e\u043c\u043e\u0440": "pop", "\u0448\u043e\u0443": "pop", "\u0438\u043d\u0442\u0435\u0440\u0430\u043a\u0442\u0438\u0432": "pop",
  "\u044d\u0442\u043d\u043e": "folk", "\u0444\u043e\u043b\u043a-\u043c\u0435\u0442\u0430\u043b": "folk", "\u043d\u0430\u0440\u043e\u0434\u043d\u0430\u044f": "folk",
  "\u0431\u043b\u044e\u0437": "blues",
};
const GENRE_LABELS = { jazz: "\u0414\u0436\u0430\u0437", rock: "\u0420\u043e\u043a", folk: "\u0424\u043e\u043b\u043a", blues: "\u0411\u043b\u044e\u0437", classic: "\u041a\u043b\u0430\u0441\u0441\u0438\u043a\u0430", pop: "\u041f\u043e\u043f" };
const GENRE_ORDER = ["jazz", "rock", "folk", "blues", "classic", "pop"];

const CITY_MAP = {
  "\u0421\u0435\u0432\u0430\u0441\u0442\u043e\u043f\u043e\u043b\u044c": "sevastopol", "\u0421\u0438\u043c\u0444\u0435\u0440\u043e\u043f\u043e\u043b\u044c": "simferopol", "\u042f\u043b\u0442\u0430": "yalta",
  "\u0421\u0443\u0434\u0430\u043a": "sudak", "\u041a\u0435\u0440\u0447\u044c": "kerch", "\u041a\u043e\u043a\u0442\u0435\u0431\u0435\u043b\u044c": "koktebel",
  "\u0411\u0430\u0445\u0447\u0438\u0441\u0430\u0440\u0430\u0439": "bakhchisaray", "\u0415\u0432\u043f\u0430\u0442\u043e\u0440\u0438\u044f": "evpatoria", "\u041a\u0440\u044b\u043c": "all",
};
const CITY_LABELS = {
  sevastopol: "\u0421\u0435\u0432\u0430\u0441\u0442\u043e\u043f\u043e\u043b\u044c", simferopol: "\u0421\u0438\u043c\u0444\u0435\u0440\u043e\u043f\u043e\u043b\u044c", yalta: "\u042f\u043b\u0442\u0430",
  sudak: "\u0421\u0443\u0434\u0430\u043a", kerch: "\u041a\u0435\u0440\u0447\u044c", koktebel: "\u041a\u043e\u043a\u0442\u0435\u0431\u0435\u043b\u044c",
  bakhchisaray: "\u0411\u0430\u0445\u0447\u0438\u0441\u0430\u0440\u0430\u0439", evpatoria: "\u0415\u0432\u043f\u0430\u0442\u043e\u0440\u0438\u044f",
};
const CITY_ORDER = ["sevastopol", "simferopol", "yalta", "evpatoria", "kerch", "sudak", "koktebel", "bakhchisaray"];

const MONTHS_GEN = ["\u044f\u043d\u0432", "\u0444\u0435\u0432", "\u043c\u0430\u0440", "\u0430\u043f\u0440", "\u043c\u0430\u044f", "\u0438\u044e\u043d", "\u0438\u044e\u043b", "\u0430\u0432\u0433", "\u0441\u0435\u043d", "\u043e\u043a\u0442", "\u043d\u043e\u044f", "\u0434\u0435\u043a"];
const DOW = ["\u043f\u043d", "\u0432\u0442", "\u0441\u0440", "\u0447\u0442", "\u043f\u0442", "\u0441\u0431", "\u0432\u0441"];
const WEEKDAY_LABELS = ["\u041f\u043e\u043d\u0435\u0434\u0435\u043b\u044c\u043d\u0438\u043a", "\u0412\u0442\u043e\u0440\u043d\u0438\u043a", "\u0421\u0440\u0435\u0434\u0430", "\u0427\u0435\u0442\u0432\u0435\u0440\u0433", "\u041f\u044f\u0442\u043d\u0438\u0446\u0430", "\u0421\u0443\u0431\u0431\u043e\u0442\u0430", "\u0412\u043e\u0441\u043a\u0440\u0435\u0441\u0435\u043d\u044c\u0435"];
const WEEKDAY_PLURAL = ["\u043f\u043e\u043d\u0435\u0434\u0435\u043b\u044c\u043d\u0438\u043a\u0430\u043c", "\u0432\u0442\u043e\u0440\u043d\u0438\u043a\u0430\u043c", "\u0441\u0440\u0435\u0434\u0430\u043c", "\u0447\u0435\u0442\u0432\u0435\u0440\u0433\u0430\u043c", "\u043f\u044f\u0442\u043d\u0438\u0446\u0430\u043c", "\u0441\u0443\u0431\u0431\u043e\u0442\u0430\u043c", "\u0432\u043e\u0441\u043a\u0440\u0435\u0441\u0435\u043d\u044c\u044f\u043c"];

const BTN_MENU = "\u2630 \u041c\u0435\u043d\u044e";
const BTN_DIGEST = "\ud83d\udce9 \u041f\u043e\u0434\u0431\u043e\u0440\u043a\u0430 \u0441\u0435\u0439\u0447\u0430\u0441";

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
// \u0425\u0440\u0430\u043d\u0438\u043b\u0438\u0449\u0435 (Cloudflare KV)
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
// \u0421\u043e\u0431\u044b\u0442\u0438\u044f
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
      artist: ovNames[url] ?? e.artist ?? "\u041a\u043e\u043d\u0446\u0435\u0440\u0442",
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
  if (!p || low.includes("\u0431\u0435\u0441\u043f\u043b\u0430\u0442") || low === "\u0432\u0445\u043e\u0434 \u0441\u0432\u043e\u0431\u043e\u0434\u043d\u044b\u0439") return "\u0431\u0435\u0441\u043f\u043b\u0430\u0442\u043d\u043e";
  return p;
}

function formatDigest(events, genres, cities) {
  if (!events.length) {
    return "\u041d\u0430 \u0431\u043b\u0438\u0436\u0430\u0439\u0448\u0443\u044e \u043d\u0435\u0434\u0435\u043b\u044e \u043f\u043e \u0442\u0432\u043e\u0438\u043c \u0444\u0438\u043b\u044c\u0442\u0440\u0430\u043c \u0441\u043e\u0431\u044b\u0442\u0438\u0439 \u043d\u0435 \u043d\u0430\u0448\u043b\u043e\u0441\u044c \ud83e\udd37\n" +
      "\u0417\u0430\u0433\u043b\u044f\u043d\u0438 \u043f\u043e\u0437\u0436\u0435 \u0438\u043b\u0438 \u0438\u0437\u043c\u0435\u043d\u0438 \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443 \u2014 /start\n\n" +
      `\ud83d\udc49 <a href="${SITE}">\u0411\u043e\u043b\u044c\u0448\u0435 \u043d\u0430 \u041c\u0435\u0441\u0442\u043e\u0432.\u041d\u0435\u0442</a>`;
  }
  const gLabel = !genres.length || genres.includes("all")
    ? "\u043b\u044e\u0431\u044b\u0435 \u0436\u0430\u043d\u0440\u044b" : GENRE_ORDER.filter((g) => genres.includes(g)).map((g) => GENRE_LABELS[g]).join(", ");
  const cLabel = !cities.length || cities.includes("all")
    ? "\u0432\u0435\u0441\u044c \u041a\u0440\u044b\u043c" : CITY_ORDER.filter((c) => cities.includes(c)).map((c) => CITY_LABELS[c]).join(", ");
  const lines = ["\ud83c\udfb6 <b>\u041f\u043e\u0434\u0431\u043e\u0440\u043a\u0430 \u0436\u0438\u0432\u043e\u0439 \u043c\u0443\u0437\u044b\u043a\u0438</b>", `<i>${esc(gLabel)} \u00b7 ${esc(cLabel)}</i>`, ""];
  for (const e of events.slice(0, MAX_EVENTS)) {
    const [y, m, d] = e.date.split("-").map(Number);
    const wd = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
    let when = `${String(d).padStart(2, "0")} ${MONTHS_GEN[m - 1]} (${DOW[wd]})`;
    if (e.time) when += ` ${e.time}`;
    const place = [e.sourceCity, e.venue, priceText(e.price)].filter(Boolean).map(esc).join(" \u00b7 ");
    const link = `${SITE}/event.html?id=${e.id}`;
    lines.push(`\ud83d\udcc5 ${when} \u2014 <a href="${link}"><b>${esc(e.artist)}</b></a>\n\ud83d\udccd ${place}\n`);
  }
  if (events.length > MAX_EVENTS)
    lines.push(`\u2026\u0438 \u0435\u0449\u0451 ${events.length - MAX_EVENTS}. \u0412\u0441\u0435 \u0441\u043e\u0431\u044b\u0442\u0438\u044f \u2014 <a href="${SITE}">\u041c\u0435\u0441\u0442\u043e\u0432.\u041d\u0435\u0442</a>`);
  if (genres.length && !genres.includes("all")) {
    const gl = GENRE_ORDER.filter((g) => genres.includes(g))
      .map((g) => `<a href="${SITE}/genre.html?g=${g}">${GENRE_LABELS[g]}</a>`).join(" \u00b7 ");
    lines.push(`\n\ud83d\udd0e \u041d\u0430 \u0441\u0430\u0439\u0442\u0435: ${gl}`);
  }
  lines.push(`\n\ud83d\udc49 <a href="${SITE}">\u0411\u043e\u043b\u044c\u0448\u0435 \u043d\u0430 \u041c\u0435\u0441\u0442\u043e\u0432.\u041d\u0435\u0442</a>`);
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// \u041a\u043b\u0430\u0432\u0438\u0430\u0442\u0443\u0440\u044b
// ---------------------------------------------------------------------------
const btn = (text, data) => ({ text, callback_data: data });
const MAIN_KB = { keyboard: [[{ text: BTN_MENU }, { text: BTN_DIGEST }]], resize_keyboard: true, is_persistent: true };

const mainMenuKb = () => ({
  inline_keyboard: [
    [btn("\u270f\ufe0f \u041d\u0430\u0441\u0442\u0440\u043e\u0438\u0442\u044c \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443", "cfg:start")],
    [btn("\ud83d\udce9 \u041f\u0440\u0438\u0441\u043b\u0430\u0442\u044c \u043f\u043e\u0434\u0431\u043e\u0440\u043a\u0443 \u0441\u0435\u0439\u0447\u0430\u0441", "digest:now")],
    [btn("\ud83d\udc40 \u041c\u043e\u044f \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430", "sub:show")],
    [btn("\ud83d\udd15 \u041e\u0442\u043f\u0438\u0441\u0430\u0442\u044c\u0441\u044f", "sub:stop")],
  ],
});

function genresKb(selected) {
  const rows = [];
  let row = [];
  for (const g of GENRE_ORDER) {
    row.push(btn((selected.includes(g) ? "\u2705 " : "") + GENRE_LABELS[g], `g:${g}`));
    if (row.length === 2) { rows.push(row); row = []; }
  }
  if (row.length) rows.push(row);
  rows.push([btn((selected.includes("all") ? "\u2705 " : "") + "\u0412\u0441\u0435 \u0436\u0430\u043d\u0440\u044b", "g:all")]);
  rows.push([btn("\u0414\u0430\u043b\u0435\u0435 \u25b6", "g:next")]);
  return { inline_keyboard: rows };
}

function citiesKb(selected) {
  const rows = [];
  let row = [];
  for (const c of CITY_ORDER) {
    row.push(btn((selected.includes(c) ? "\u2705 " : "") + CITY_LABELS[c], `c:${c}`));
    if (row.length === 2) { rows.push(row); row = []; }
  }
  if (row.length) rows.push(row);
  rows.push([btn((selected.includes("all") ? "\u2705 " : "") + "\u0412\u0435\u0441\u044c \u041a\u0440\u044b\u043c", "c:all")]);
  rows.push([btn("\u0414\u0430\u043b\u0435\u0435 \u25b6", "c:next")]);
  return { inline_keyboard: rows };
}

const freqKb = () => ({
  inline_keyboard: [
    [btn("\ud83d\udcc5 \u041a\u0430\u0436\u0434\u044b\u0439 \u0434\u0435\u043d\u044c", "f:daily")],
    [btn("\ud83d\uddd3 \u0420\u0430\u0437 \u0432 \u043d\u0435\u0434\u0435\u043b\u044e", "f:weekly")],
    [btn("\u270b \u0422\u043e\u043b\u044c\u043a\u043e \u043f\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u0443", "f:ondemand")],
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
    ? "\u043b\u044e\u0431\u044b\u0435" : GENRE_ORDER.filter((x) => sub.genres.includes(x)).map((x) => GENRE_LABELS[x]).join(", ");
  const c = sub.cities.includes("all") || !sub.cities.length
    ? "\u0432\u0435\u0441\u044c \u041a\u0440\u044b\u043c" : CITY_ORDER.filter((x) => sub.cities.includes(x)).map((x) => CITY_LABELS[x]).join(", ");
  let when;
  if (sub.freq === "daily") when = "\u043a\u0430\u0436\u0434\u044b\u0439 \u0434\u0435\u043d\u044c \u0432 16:20";
  else if (sub.freq === "weekly") when = `\u043f\u043e ${WEEKDAY_PLURAL[sub.weekday]} \u0432 16:20`;
  else when = "\u0442\u043e\u043b\u044c\u043a\u043e \u043f\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u0443 (/digest)";
  return `\ud83d\udccb <b>\u0422\u0432\u043e\u044f \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0430</b>\n\u0416\u0430\u043d\u0440\u044b: ${esc(g)}\n\u0413\u043e\u0440\u043e\u0434\u0430: ${esc(c)}\n\u0427\u0430\u0441\u0442\u043e\u0442\u0430: ${when}`;
}

// ---------------------------------------------------------------------------
// \u041b\u043e\u0433\u0438\u043a\u0430
// ---------------------------------------------------------------------------
const WELCOME =
  "\u041f\u0440\u0438\u0432\u0435\u0442! \u042f \u0431\u043e\u0442 <b>\u041c\u0435\u0441\u0442\u043e\u0432.\u041d\u0435\u0442</b> \ud83c\udfb8\n" +
  "\u041f\u0440\u0438\u0441\u044b\u043b\u0430\u044e \u043f\u043e\u0434\u0431\u043e\u0440\u043a\u0438 \u0436\u0438\u0432\u043e\u0439 \u043c\u0443\u0437\u044b\u043a\u0438 \u041a\u0440\u044b\u043c\u0430 \u043f\u043e\u0434 \u0442\u0432\u043e\u0439 \u0432\u043a\u0443\u0441.\n\n" +
  "\u0412\u044b\u0431\u0435\u0440\u0438 \u0436\u0430\u043d\u0440\u044b, \u0433\u043e\u0440\u043e\u0434\u0430 \u0438 \u043a\u0430\u043a \u0447\u0430\u0441\u0442\u043e \u0441\u043b\u0430\u0442\u044c \u2014 \u0430 \u0434\u0430\u043b\u044c\u0448\u0435 \u044f \u0441\u0430\u043c.\n" +
  `\u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a: ${SITE}`;

async function sendDigest(env, chatId, sub) {
  const genres = sub ? sub.genres : ["all"];
  const cities = sub ? sub.cities : ["all"];
  let events;
  try {
    events = await fetchEvents();
  } catch (e) {
    await send(env, chatId, "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0441\u043e\u0431\u044b\u0442\u0438\u044f \u0441 \u0441\u0430\u0439\u0442\u0430, \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u043f\u043e\u0437\u0436\u0435 \ud83d\ude4f", null, false);
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
    ? "\n\n\u0411\u0443\u0434\u0443 \u0436\u0434\u0430\u0442\u044c \u043a\u043e\u043c\u0430\u043d\u0434\u044b /digest \ud83d\udc4c"
    : "\n\n\u0413\u043e\u0442\u043e\u0432\u043e! \u041f\u0435\u0440\u0432\u0430\u044f \u043f\u043e\u0434\u0431\u043e\u0440\u043a\u0430 \u043f\u0440\u0438\u0434\u0451\u0442 \u043f\u043e \u0440\u0430\u0441\u043f\u0438\u0441\u0430\u043d\u0438\u044e. \u041f\u0440\u0438\u0441\u043b\u0430\u0442\u044c \u0441\u0435\u0439\u0447\u0430\u0441 \u2014 /digest";
  await editText(env, chatId, msgId, summaryText(sub) + tail);
}

async function onStats(env, chatId, userId) {
  if (userId !== Number(env.ADMIN_ID)) {
    await send(env, chatId, "\u041a\u043e\u043c\u0430\u043d\u0434\u0430 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u0442\u043e\u043b\u044c\u043a\u043e \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0443.", null, false);
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
    "\ud83d\udcca <b>\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430</b>", "",
    `\ud83d\udc65 \u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u043f\u043e\u0434\u043f\u0438\u0441\u0447\u0438\u043a\u043e\u0432: <b>${total}</b>`,
    `\u2795 \u0412\u0441\u0435\u0433\u043e \u043f\u043e\u0434\u043f\u0438\u0441\u0430\u043b\u043e\u0441\u044c: ${await getCounter(env, "total_subscribed")}`,
    `\u2796 \u0412\u0441\u0435\u0433\u043e \u043e\u0442\u043f\u0438\u0441\u0430\u043b\u043e\u0441\u044c: ${await getCounter(env, "total_unsubscribed")}`, "",
    "<b>\u041f\u043e \u0447\u0430\u0441\u0442\u043e\u0442\u0435:</b>",
    `\u2022 \u043a\u0430\u0436\u0434\u044b\u0439 \u0434\u0435\u043d\u044c: ${freq.daily}`, `\u2022 \u0440\u0430\u0437 \u0432 \u043d\u0435\u0434\u0435\u043b\u044e: ${freq.weekly}`, `\u2022 \u043f\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u0443: ${freq.ondemand}`, "",
    "<b>\u041f\u043e \u0436\u0430\u043d\u0440\u0430\u043c:</b>", `\u2022 \u043b\u044e\u0431\u044b\u0435: ${gAll}`,
    ...GENRE_ORDER.map((g) => `\u2022 ${GENRE_LABELS[g]}: ${gc[g]}`),
    "", "<b>\u041f\u043e \u0433\u043e\u0440\u043e\u0434\u0430\u043c:</b>", `\u2022 \u0432\u0435\u0441\u044c \u041a\u0440\u044b\u043c: ${cAll}`,
    ...CITY_ORDER.map((c) => `\u2022 ${CITY_LABELS[c]}: ${cc[c]}`),
  ];
  await send(env, chatId, lines.join("\n"));
}

async function onCommand(env, chatId, userId, text) {
  const cmd = text.split(/\s+/)[0].replace("/", "").split("@")[0];
  if (cmd === "start") {
    await send(env, chatId, WELCOME, MAIN_KB);
    await send(env, chatId, "\u0427\u0442\u043e \u0445\u043e\u0447\u0435\u0448\u044c \u0441\u0434\u0435\u043b\u0430\u0442\u044c?", mainMenuKb(), false);
  } else if (cmd === "help") {
    await send(env, chatId, "\u041a\u043e\u043c\u0430\u043d\u0434\u044b:\n/start \u2014 \u043c\u0435\u043d\u044e\n/digest \u2014 \u043f\u043e\u0434\u0431\u043e\u0440\u043a\u0430 \u0441\u0435\u0439\u0447\u0430\u0441\n/stop \u2014 \u043e\u0442\u043f\u0438\u0441\u0430\u0442\u044c\u0441\u044f", mainMenuKb(), false);
  } else if (cmd === "digest") {
    await sendDigest(env, chatId, await getSub(env, chatId));
  } else if (cmd === "stop") {
    if (await getSub(env, chatId)) {
      await delSub(env, chatId);
      await bumpCounter(env, "total_unsubscribed");
      await send(env, chatId, "\u041e\u0442\u043f\u0438\u0441\u0430\u043b. \u0412\u0435\u0440\u043d\u0443\u0442\u044c\u0441\u044f \u2014 /start", null, false);
    } else {
      await send(env, chatId, "\u0423 \u0442\u0435\u0431\u044f \u0438 \u043d\u0435 \u0431\u044b\u043b\u043e \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438. /start", null, false);
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
      "\u0428\u0430\u0433 1/3. \u041a\u0430\u043a\u0438\u0435 <b>\u0436\u0430\u043d\u0440\u044b</b> \u0438\u043d\u0442\u0435\u0440\u0435\u0441\u043d\u044b? \u041c\u043e\u0436\u043d\u043e \u043d\u0435\u0441\u043a\u043e\u043b\u044c\u043a\u043e. \u041f\u043e\u0442\u043e\u043c \u043d\u0430\u0436\u043c\u0438 \u00ab\u0414\u0430\u043b\u0435\u0435\u00bb.", genresKb(draft.genres));
  } else if (data.startsWith("g:")) {
    const val = data.slice(2);
    const draft = await getDraft(env, chatId);
    if (val === "next") {
      if (!draft.genres.length) { await answerCb(env, cb.id, "\u0412\u044b\u0431\u0435\u0440\u0438 \u0445\u043e\u0442\u044f \u0431\u044b \u043e\u0434\u0438\u043d \u0436\u0430\u043d\u0440 (\u0438\u043b\u0438 \u00ab\u0412\u0441\u0435 \u0436\u0430\u043d\u0440\u044b\u00bb)", true); return; }
      await editText(env, chatId, msgId, "\u0428\u0430\u0433 2/3. \u0412 \u043a\u0430\u043a\u0438\u0445 <b>\u0433\u043e\u0440\u043e\u0434\u0430\u0445</b>? \u041c\u043e\u0436\u043d\u043e \u043d\u0435\u0441\u043a\u043e\u043b\u044c\u043a\u043e.", citiesKb(draft.cities));
    } else {
      draft.genres = toggle(draft.genres, val);
      await setDraft(env, chatId, draft);
      await editMarkup(env, chatId, msgId, genresKb(draft.genres));
    }
  } else if (data.startsWith("c:")) {
    const val = data.slice(2);
    const draft = await getDraft(env, chatId);
    if (val === "next") {
      if (!draft.cities.length) { await answerCb(env, cb.id, "\u0412\u044b\u0431\u0435\u0440\u0438 \u0445\u043e\u0442\u044f \u0431\u044b \u043e\u0434\u0438\u043d \u0433\u043e\u0440\u043e\u0434 (\u0438\u043b\u0438 \u00ab\u0412\u0435\u0441\u044c \u041a\u0440\u044b\u043c\u00bb)", true); return; }
      await editText(env, chatId, msgId, "\u0428\u0430\u0433 3/3. \u041a\u0430\u043a \u0447\u0430\u0441\u0442\u043e \u043f\u0440\u0438\u0441\u044b\u043b\u0430\u0442\u044c \u043f\u043e\u0434\u0431\u043e\u0440\u043a\u0443?", freqKb());
    } else {
      draft.cities = toggle(draft.cities, val);
      await setDraft(env, chatId, draft);
      await editMarkup(env, chatId, msgId, citiesKb(draft.cities));
    }
  } else if (data.startsWith("f:")) {
    const draft = await getDraft(env, chatId);
    draft.freq = data.slice(2);
    await setDraft(env, chatId, draft);
    if (draft.freq === "weekly") await editText(env, chatId, msgId, "\u0412 \u043a\u0430\u043a\u043e\u0439 \u0434\u0435\u043d\u044c \u043d\u0435\u0434\u0435\u043b\u0438 \u043f\u0440\u0438\u0441\u044b\u043b\u0430\u0442\u044c?", weekdayKb(), false);
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
      sub ? summaryText(sub) : "\u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0438 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442. \u041d\u0430\u0436\u043c\u0438 \u00ab\u041d\u0430\u0441\u0442\u0440\u043e\u0438\u0442\u044c \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0443\u00bb.", mainMenuKb());
  } else if (data === "sub:stop") {
    if (await getSub(env, chatId)) {
      await delSub(env, chatId);
      await bumpCounter(env, "total_unsubscribed");
      await editText(env, chatId, msgId, "\u041e\u0442\u043f\u0438\u0441\u0430\u043b. \u0412\u0435\u0440\u043d\u0443\u0442\u044c\u0441\u044f \u2014 /start", null, false);
    } else {
      await editText(env, chatId, msgId, "\u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0438 \u0438 \u043d\u0435 \u0431\u044b\u043b\u043e. /start", null, false);
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
    else await send(env, chatId, "\u0427\u0442\u043e \u0445\u043e\u0447\u0435\u0448\u044c \u0441\u0434\u0435\u043b\u0430\u0442\u044c?", mainMenuKb(), false);
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
// \u0422\u043e\u0447\u043a\u0438 \u0432\u0445\u043e\u0434\u0430 Cloudflare Workers
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
    return new Response("\u041c\u0435\u0441\u0442\u043e\u0432.\u041d\u0435\u0442 \u0431\u043e\u0442 \u0440\u0430\u0431\u043e\u0442\u0430\u0435\u0442 \ud83c\udfb8");
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(runCron(env));
  },
};
