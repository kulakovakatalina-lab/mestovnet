/**
 * Телеграм-бот «Местов.Нет» для Deno Deploy.
 *
 * Serverless-версия: работает на webhook (Telegram сам шлёт апдейты),
 * рассылка по расписанию — через Deno.cron, подписки хранятся в Deno KV.
 *
 * Переменные окружения (задаются в панели Deno Deploy):
 *   BOT_TOKEN       — токен бота от @BotFather
 *   WEBHOOK_SECRET  — любая случайная строка (защита webhook)
 *   ADMIN_ID        — Telegram ID администратора для /stats (по умолчанию задан)
 */
import {
  Bot,
  InlineKeyboard,
  Keyboard,
  webhookCallback,
} from "https://deno.land/x/grammy@v1.30.0/mod.ts";

// ---------------------------------------------------------------------------
// Конфигурация
// ---------------------------------------------------------------------------
const SITE = "https://mestov.net";
const EVENTS_URL = `${SITE}/events.json`;
const SETTINGS_URL = `${SITE}/settings.json`;
const ADMIN_ID = Number(Deno.env.get("ADMIN_ID") ?? "267459702");
const MAX_EVENTS = 25;
const HORIZON_DAYS = 7; // подборка всегда на ближайшую неделю

// Маппинг «сырых» жанров в канонические — копия GENRE_MAP с сайта (genre.html)
const GENRE_MAP: Record<string, string> = {
  "джаз": "jazz",
  "рок": "rock", "русский рок": "rock", "панк-рок": "rock",
  "инди-рок": "rock", "метал": "rock", "инди": "rock", "авторская": "rock",
  "классика": "classic", "хоровая": "classic", "медитативная": "classic",
  "поп": "pop", "поп-рок": "pop", "лаунж": "pop", "хип-хоп": "pop",
  "каверы": "pop", "юмор": "pop", "шоу": "pop", "интерактив": "pop",
  "этно": "folk", "фолк-метал": "folk", "народная": "folk",
  "блюз": "blues",
};
const GENRE_LABELS: Record<string, string> = {
  jazz: "Джаз", rock: "Рок", folk: "Фолк",
  blues: "Блюз", classic: "Классика", pop: "Поп",
};
const GENRE_ORDER = ["jazz", "rock", "folk", "blues", "classic", "pop"];

const CITY_MAP: Record<string, string> = {
  "Севастополь": "sevastopol", "Симферополь": "simferopol", "Ялта": "yalta",
  "Судак": "sudak", "Керчь": "kerch", "Коктебель": "koktebel",
  "Бахчисарай": "bakhchisaray", "Евпатория": "evpatoria", "Крым": "all",
};
const CITY_LABELS: Record<string, string> = {
  sevastopol: "Севастополь", simferopol: "Симферополь", yalta: "Ялта",
  sudak: "Судак", kerch: "Керчь", koktebel: "Коктебель",
  bakhchisaray: "Бахчисарай", evpatoria: "Евпатория",
};
const CITY_ORDER = [
  "sevastopol", "simferopol", "yalta", "evpatoria",
  "kerch", "sudak", "koktebel", "bakhchisaray",
];

const MONTHS_GEN = ["янв", "фев", "мар", "апр", "мая", "июн",
  "июл", "авг", "сен", "окт", "ноя", "дек"];
const DOW = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
const WEEKDAY_LABELS = ["Понедельник", "Вторник", "Среда", "Четверг",
  "Пятница", "Суббота", "Воскресенье"];
const WEEKDAY_PLURAL = ["понедельникам", "вторникам", "средам", "четвергам",
  "пятницам", "субботам", "воскресеньям"];

function mapGenre(raw: string | undefined | null): string {
  return GENRE_MAP[(raw ?? "").toLowerCase()] ?? "pop";
}
function mapCity(raw: string | undefined | null): string {
  return CITY_MAP[raw ?? ""] ?? "all";
}
function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Дата в часовом поясе Крыма (UTC+3) как YYYY-MM-DD и день недели (Пн=0)
function crimeaNow(): { iso: string; weekday: number } {
  const d = new Date(Date.now() + 3 * 3600 * 1000);
  const iso = d.toISOString().slice(0, 10);
  const weekday = (d.getUTCDay() + 6) % 7;
  return { iso, weekday };
}

// ---------------------------------------------------------------------------
// Типы и хранилище (Deno KV)
// ---------------------------------------------------------------------------
interface Sub {
  genres: string[];
  cities: string[];
  freq: "daily" | "weekly" | "ondemand";
  weekday: number;
}
interface Ev {
  id: string;
  date: string; // YYYY-MM-DD
  time: string;
  artist: string;
  venue: string;
  price: string;
  sourceCity: string;
  genre: string;
  city: string;
}

const kv = await Deno.openKv();

async function getSub(chatId: number): Promise<Sub | null> {
  return (await kv.get<Sub>(["sub", chatId])).value;
}
async function setSub(chatId: number, sub: Sub): Promise<void> {
  await kv.set(["sub", chatId], sub);
}
async function delSub(chatId: number): Promise<void> {
  await kv.delete(["sub", chatId]);
}
async function getDraft(chatId: number): Promise<Sub> {
  return (await kv.get<Sub>(["draft", chatId])).value ??
    { genres: [], cities: [], freq: "ondemand", weekday: 4 };
}
async function setDraft(chatId: number, draft: Sub): Promise<void> {
  await kv.set(["draft", chatId], draft);
}
async function bumpCounter(name: string): Promise<void> {
  await kv.atomic().sum(["stats", name], 1n).commit();
}
async function getCounter(name: string): Promise<number> {
  const v = (await kv.get<bigint>(["stats", name])).value;
  return v ? Number(v) : 0;
}

// ---------------------------------------------------------------------------
// Загрузка и фильтрация событий
// ---------------------------------------------------------------------------
async function fetchEvents(): Promise<Ev[]> {
  const [evResp, setResp] = await Promise.all([
    fetch(EVENTS_URL),
    fetch(SETTINGS_URL).catch(() => null),
  ]);
  const data = await evResp.json() as Record<string, unknown>[];
  let settings: Record<string, Record<string, string>> = {};
  if (setResp && setResp.ok) {
    settings = await setResp.json().catch(() => ({}));
  }
  const hidden = new Set(((settings.hidden as unknown) as string[]) ?? []);
  const ov = (k: string) => (settings[k] ?? {}) as Record<string, string>;
  const ovNames = ov("names"), ovTimes = ov("times"), ovPrices = ov("prices");
  const ovCities = ov("cities"), ovVenues = ov("venues"), ovGenres = ov("genres");

  const today = crimeaNow().iso;
  const out: Ev[] = [];
  for (const e of data) {
    const url = (e.source_url as string) ?? "";
    const date = e.date as string;
    if (hidden.has(url) || !date) continue;
    if (date < today) continue;
    const rawGenre = ovGenres[url] ?? (e.genre as string);
    const rawCity = ovCities[url] ?? (e.source_city as string);
    out.push({
      id: e.id as string,
      date,
      time: ovTimes[url] ?? (e.time as string) ?? "",
      artist: ovNames[url] ?? (e.artist as string) ?? "Концерт",
      venue: ovVenues[url] ?? (e.venue as string) ?? "",
      price: ovPrices[url] ?? (e.price as string) ?? "",
      sourceCity: rawCity ?? "",
      genre: mapGenre(rawGenre),
      city: mapCity(rawCity),
    });
  }
  out.sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));
  return out;
}

function filterEvents(events: Ev[], genres: string[], cities: string[]): Ev[] {
  const today = crimeaNow().iso;
  const horizon = new Date(Date.now() + 3 * 3600 * 1000);
  horizon.setUTCDate(horizon.getUTCDate() + HORIZON_DAYS);
  const horizonIso = horizon.toISOString().slice(0, 10);
  const allGenres = genres.length === 0 || genres.includes("all");
  const allCities = cities.length === 0 || cities.includes("all");
  return events.filter((e) => {
    if (!allGenres && !genres.includes(e.genre)) return false;
    // Крым-wide события (city === 'all') показываем всегда
    if (!allCities && e.city !== "all" && !cities.includes(e.city)) return false;
    return e.date >= today && e.date <= horizonIso;
  });
}

function priceText(p: string): string {
  const low = (p ?? "").toLowerCase();
  if (!p || low.includes("бесплат") || low === "вход свободный") return "бесплатно";
  return p;
}

function formatDigest(events: Ev[], genres: string[], cities: string[]): string {
  if (events.length === 0) {
    return "На ближайшую неделю по твоим фильтрам событий не нашлось 🤷\n" +
      "Загляни позже или измени подписку — /start\n\n" +
      `👉 <a href="${SITE}">Больше на Местов.Нет</a>`;
  }
  const gLabel = genres.length === 0 || genres.includes("all")
    ? "любые жанры"
    : GENRE_ORDER.filter((g) => genres.includes(g)).map((g) => GENRE_LABELS[g]).join(", ");
  const cLabel = cities.length === 0 || cities.includes("all")
    ? "весь Крым"
    : CITY_ORDER.filter((c) => cities.includes(c)).map((c) => CITY_LABELS[c]).join(", ");

  const lines = ["🎶 <b>Подборка живой музыки</b>",
    `<i>${escapeHtml(gLabel)} · ${escapeHtml(cLabel)}</i>`, ""];

  for (const e of events.slice(0, MAX_EVENTS)) {
    const [y, m, dd] = e.date.split("-").map(Number);
    const wd = (new Date(Date.UTC(y, m - 1, dd)).getUTCDay() + 6) % 7;
    let when = `${String(dd).padStart(2, "0")} ${MONTHS_GEN[m - 1]} (${DOW[wd]})`;
    if (e.time) when += ` ${e.time}`;
    const place = [e.sourceCity, e.venue, priceText(e.price)]
      .filter(Boolean).map((x) => escapeHtml(x)).join(" · ");
    const link = `${SITE}/event/${e.id}`;
    lines.push(`📅 ${when} — <a href="${link}"><b>${escapeHtml(e.artist)}</b></a>\n📍 ${place}\n`);
  }
  if (events.length > MAX_EVENTS) {
    lines.push(`…и ещё ${events.length - MAX_EVENTS}. Все события — <a href="${SITE}">Местов.Нет</a>`);
  }
  if (genres.length && !genres.includes("all")) {
    const glinks = GENRE_ORDER.filter((g) => genres.includes(g))
      .map((g) => `<a href="${SITE}/genre.html?g=${g}">${GENRE_LABELS[g]}</a>`).join(" · ");
    lines.push(`\n🔎 На сайте: ${glinks}`);
  }
  lines.push(`\n👉 <a href="${SITE}">Больше на Местов.Нет</a>`);
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Клавиатуры
// ---------------------------------------------------------------------------
const BTN_MENU = "☰ Меню";
const BTN_DIGEST = "📩 Подборка сейчас";
const MAIN_KB = new Keyboard([[BTN_MENU, BTN_DIGEST]]).resized().persistent();

function mainMenuKb(): InlineKeyboard {
  return new InlineKeyboard()
    .text("✏️ Настроить подписку", "cfg:start").row()
    .text("📩 Прислать подборку сейчас", "digest:now").row()
    .text("👀 Моя подписка", "sub:show").row()
    .text("🔕 Отписаться", "sub:stop");
}

function genresKb(selected: string[]): InlineKeyboard {
  const kb = new InlineKeyboard();
  GENRE_ORDER.forEach((g, i) => {
    const mark = selected.includes(g) ? "✅ " : "";
    kb.text(`${mark}${GENRE_LABELS[g]}`, `g:${g}`);
    if (i % 2 === 1) kb.row();
  });
  kb.row().text(`${selected.includes("all") ? "✅ " : ""}Все жанры`, "g:all");
  kb.row().text("Далее ▶", "g:next");
  return kb;
}

function citiesKb(selected: string[]): InlineKeyboard {
  const kb = new InlineKeyboard();
  CITY_ORDER.forEach((c, i) => {
    const mark = selected.includes(c) ? "✅ " : "";
    kb.text(`${mark}${CITY_LABELS[c]}`, `c:${c}`);
    if (i % 2 === 1) kb.row();
  });
  kb.row().text(`${selected.includes("all") ? "✅ " : ""}Весь Крым`, "c:all");
  kb.row().text("Далее ▶", "c:next");
  return kb;
}

function freqKb(): InlineKeyboard {
  return new InlineKeyboard()
    .text("📅 Каждый день", "f:daily").row()
    .text("🗓 Раз в неделю", "f:weekly").row()
    .text("✋ Только по запросу", "f:ondemand");
}

function weekdayKb(): InlineKeyboard {
  const kb = new InlineKeyboard();
  for (let i = 0; i < 7; i++) kb.text(WEEKDAY_LABELS[i], `w:${i}`).row();
  return kb;
}

function toggle(selected: string[], value: string): string[] {
  if (value === "all") return selected.includes("all") ? [] : ["all"];
  selected = selected.filter((x) => x !== "all");
  return selected.includes(value)
    ? selected.filter((x) => x !== value)
    : [...selected, value];
}

function summaryText(sub: Sub): string {
  const g = sub.genres.includes("all") || sub.genres.length === 0
    ? "любые"
    : GENRE_ORDER.filter((x) => sub.genres.includes(x)).map((x) => GENRE_LABELS[x]).join(", ");
  const c = sub.cities.includes("all") || sub.cities.length === 0
    ? "весь Крым"
    : CITY_ORDER.filter((x) => sub.cities.includes(x)).map((x) => CITY_LABELS[x]).join(", ");
  let when: string;
  if (sub.freq === "daily") when = "каждый день в 16:20";
  else if (sub.freq === "weekly") when = `по ${WEEKDAY_PLURAL[sub.weekday]} в 16:20`;
  else when = "только по запросу (/digest)";
  return `📋 <b>Твоя подписка</b>\nЖанры: ${escapeHtml(g)}\nГорода: ${escapeHtml(c)}\nЧастота: ${when}`;
}

// ---------------------------------------------------------------------------
// Бот
// ---------------------------------------------------------------------------
const token = Deno.env.get("BOT_TOKEN");
if (!token) throw new Error("Не задан BOT_TOKEN");
const bot = new Bot(token);

const WELCOME =
  "Привет! Я бот <b>Местов.Нет</b> 🎸\n" +
  "Присылаю подборки живой музыки Крыма под твой вкус.\n\n" +
  "Выбери жанры, города и как часто слать — а дальше я сам.\n" +
  `Источник: ${SITE}`;

const htmlNoPreview = {
  parse_mode: "HTML" as const,
  link_preview_options: { is_disabled: true },
};

async function sendDigest(chatId: number, sub: Sub | null) {
  const genres = sub ? sub.genres : ["all"];
  const cities = sub ? sub.cities : ["all"];
  let events: Ev[];
  try {
    events = await fetchEvents();
  } catch (_e) {
    await bot.api.sendMessage(chatId, "Не удалось загрузить события с сайта, попробуй позже 🙏");
    return;
  }
  const filtered = filterEvents(events, genres, cities);
  await bot.api.sendMessage(chatId, formatDigest(filtered, genres, cities), htmlNoPreview);
}

bot.command("start", async (ctx) => {
  await ctx.reply(WELCOME, { parse_mode: "HTML", reply_markup: MAIN_KB });
  await ctx.reply("Что хочешь сделать?", { reply_markup: mainMenuKb() });
});

bot.command("help", async (ctx) => {
  await ctx.reply(
    "Команды:\n/start — меню и настройка подписки\n" +
      "/digest — прислать подборку сейчас\n/stop — отписаться",
    { reply_markup: mainMenuKb() },
  );
});

bot.command("digest", async (ctx) => {
  await sendDigest(ctx.chat.id, await getSub(ctx.chat.id));
});

bot.command("stop", async (ctx) => {
  if (await getSub(ctx.chat.id)) {
    await delSub(ctx.chat.id);
    await bumpCounter("total_unsubscribed");
    await ctx.reply("Отписал. Вернуться — /start");
  } else {
    await ctx.reply("У тебя и не было подписки. /start");
  }
});

bot.command("stats", async (ctx) => {
  if (ctx.from?.id !== ADMIN_ID) {
    await ctx.reply("Команда доступна только администратору.");
    return;
  }
  let total = 0;
  const freq = { daily: 0, weekly: 0, ondemand: 0 } as Record<string, number>;
  const genreCount: Record<string, number> = {};
  const cityCount: Record<string, number> = {};
  let genreAll = 0, cityAll = 0;
  GENRE_ORDER.forEach((g) => genreCount[g] = 0);
  CITY_ORDER.forEach((c) => cityCount[c] = 0);
  for await (const entry of kv.list<Sub>({ prefix: ["sub"] })) {
    const s = entry.value;
    total++;
    freq[s.freq] = (freq[s.freq] ?? 0) + 1;
    if (s.genres.includes("all") || s.genres.length === 0) genreAll++;
    else s.genres.forEach((g) => { if (g in genreCount) genreCount[g]++; });
    if (s.cities.includes("all") || s.cities.length === 0) cityAll++;
    else s.cities.forEach((c) => { if (c in cityCount) cityCount[c]++; });
  }
  const totalSub = await getCounter("total_subscribed");
  const totalUnsub = await getCounter("total_unsubscribed");
  const lines = [
    "📊 <b>Статистика</b>", "",
    `👥 Активных подписчиков: <b>${total}</b>`,
    `➕ Всего подписалось: ${totalSub}`,
    `➖ Всего отписалось: ${totalUnsub}`, "",
    "<b>По частоте:</b>",
    `• каждый день: ${freq.daily}`,
    `• раз в неделю: ${freq.weekly}`,
    `• по запросу: ${freq.ondemand}`, "",
    "<b>По жанрам:</b>", `• любые: ${genreAll}`,
    ...GENRE_ORDER.map((g) => `• ${GENRE_LABELS[g]}: ${genreCount[g]}`),
    "", "<b>По городам:</b>", `• весь Крым: ${cityAll}`,
    ...CITY_ORDER.map((c) => `• ${CITY_LABELS[c]}: ${cityCount[c]}`),
  ];
  await ctx.reply(lines.join("\n"), { parse_mode: "HTML" });
});

bot.on("callback_query:data", async (ctx) => {
  const data = ctx.callbackQuery.data;
  const chatId = ctx.chat!.id;
  await ctx.answerCallbackQuery();

  if (data === "cfg:start") {
    const sub = await getSub(chatId);
    const draft: Sub = sub
      ? { ...sub }
      : { genres: [], cities: [], freq: "ondemand", weekday: 4 };
    await setDraft(chatId, draft);
    await ctx.editMessageText(
      "Шаг 1/3. Какие <b>жанры</b> интересны? Можно несколько. Потом нажми «Далее».",
      { parse_mode: "HTML", reply_markup: genresKb(draft.genres) },
    );
    return;
  }

  if (data.startsWith("g:")) {
    const val = data.slice(2);
    const draft = await getDraft(chatId);
    if (val === "next") {
      if (draft.genres.length === 0) {
        await ctx.answerCallbackQuery({ text: "Выбери хотя бы один жанр (или «Все жанры»)", show_alert: true });
        return;
      }
      await ctx.editMessageText("Шаг 2/3. В каких <b>городах</b>? Можно несколько.",
        { parse_mode: "HTML", reply_markup: citiesKb(draft.cities) });
      return;
    }
    draft.genres = toggle(draft.genres, val);
    await setDraft(chatId, draft);
    await ctx.editMessageReplyMarkup({ reply_markup: genresKb(draft.genres) });
    return;
  }

  if (data.startsWith("c:")) {
    const val = data.slice(2);
    const draft = await getDraft(chatId);
    if (val === "next") {
      if (draft.cities.length === 0) {
        await ctx.answerCallbackQuery({ text: "Выбери хотя бы один город (или «Весь Крым»)", show_alert: true });
        return;
      }
      await ctx.editMessageText("Шаг 3/3. Как часто присылать подборку?",
        { parse_mode: "HTML", reply_markup: freqKb() });
      return;
    }
    draft.cities = toggle(draft.cities, val);
    await setDraft(chatId, draft);
    await ctx.editMessageReplyMarkup({ reply_markup: citiesKb(draft.cities) });
    return;
  }

  if (data.startsWith("f:")) {
    const freq = data.slice(2) as Sub["freq"];
    const draft = await getDraft(chatId);
    draft.freq = freq;
    await setDraft(chatId, draft);
    if (freq === "weekly") {
      await ctx.editMessageText("В какой день недели присылать?", { reply_markup: weekdayKb() });
      return;
    }
    await finishSub(ctx, chatId, draft);
    return;
  }

  if (data.startsWith("w:")) {
    const draft = await getDraft(chatId);
    draft.weekday = Number(data.slice(2));
    await finishSub(ctx, chatId, draft);
    return;
  }

  if (data === "digest:now") {
    await sendDigest(chatId, await getSub(chatId));
    return;
  }

  if (data === "sub:show") {
    const sub = await getSub(chatId);
    await ctx.editMessageText(
      sub ? summaryText(sub) : "Подписки пока нет. Нажми «Настроить подписку».",
      { parse_mode: "HTML", reply_markup: mainMenuKb() },
    );
    return;
  }

  if (data === "sub:stop") {
    if (await getSub(chatId)) {
      await delSub(chatId);
      await bumpCounter("total_unsubscribed");
      await ctx.editMessageText("Отписал. Вернуться — /start");
    } else {
      await ctx.editMessageText("Подписки и не было. /start");
    }
    return;
  }
});

async function finishSub(ctx: any, chatId: number, draft: Sub) {
  const existed = await getSub(chatId);
  if (!existed) await bumpCounter("total_subscribed");
  const sub: Sub = {
    genres: draft.genres, cities: draft.cities,
    freq: draft.freq, weekday: draft.weekday,
  };
  await setSub(chatId, sub);
  await kv.delete(["draft", chatId]);
  if (sub.freq === "ondemand") {
    await ctx.editMessageText(summaryText(sub) + "\n\nБуду ждать команды /digest 👌",
      { parse_mode: "HTML" });
  } else {
    await ctx.editMessageText(
      summaryText(sub) + "\n\nГотово! Первая подборка придёт по расписанию. Прислать сейчас — /digest",
      { parse_mode: "HTML" });
  }
}

bot.on("message:text", async (ctx) => {
  const text = (ctx.message.text ?? "").trim();
  if (text === BTN_DIGEST) {
    await sendDigest(ctx.chat.id, await getSub(ctx.chat.id));
  } else {
    await ctx.reply("Что хочешь сделать?", { reply_markup: mainMenuKb() });
  }
});

// ---------------------------------------------------------------------------
// Расписание: каждый день в 13:20 UTC = 16:20 по Крыму
// ---------------------------------------------------------------------------
Deno.cron("digest", "20 13 * * *", async () => {
  const { weekday } = crimeaNow();
  for await (const entry of kv.list<Sub>({ prefix: ["sub"] })) {
    const sub = entry.value;
    const chatId = Number(entry.key[1]);
    if (sub.freq === "daily" || (sub.freq === "weekly" && sub.weekday === weekday)) {
      try {
        await sendDigest(chatId, sub);
      } catch (e) {
        console.error("digest failed for", chatId, e);
      }
    }
  }
});

// ---------------------------------------------------------------------------
// Webhook (Deno Deploy)
// ---------------------------------------------------------------------------
const SECRET = Deno.env.get("WEBHOOK_SECRET") ?? "";
const handleUpdate = webhookCallback(bot, "std/http", { secretToken: SECRET });

Deno.serve(async (req) => {
  if (req.method === "POST") {
    try {
      return await handleUpdate(req);
    } catch (_e) {
      return new Response("error", { status: 200 });
    }
  }
  return new Response("Местов.Нет бот работает 🎸");
});
