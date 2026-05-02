#!/usr/bin/env python3
"""SEO static site generator for Местов.Нет.

Reads events.json and generates:
  - index.html          (с JSON-LD + статическим пре-рендером)
  - cities/{slug}.html  (страница каждого города)
  - sitemap.xml
  - robots.txt

Запускать после parser.py:
  python generate_pages.py
"""

import html as html_module
import json
import os
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

# ── Конфиг ──────────────────────────────────────────────────────────────────

BASE_DIR   = Path(__file__).parent
EVENTS_FILE = BASE_DIR / "events.json"
INDEX_FILE  = BASE_DIR / "index.html"
DOMAIN     = "https://mestov.net"

# ── Локализация ──────────────────────────────────────────────────────────────

MONTHS_GEN = [
    "января","февраля","марта","апреля","мая","июня",
    "июля","августа","сентября","октября","ноября","декабря",
]
MONTHS_NOM = [
    "Январь","Февраль","Март","Апрель","Май","Июнь",
    "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь",
]
DAYS_SHORT = ["вс","пн","вт","ср","чт","пт","сб"]

# ── Города ───────────────────────────────────────────────────────────────────

CITY_SLUGS: dict[str, str] = {
    "Симферополь":   "simferopol",
    "Ялта":          "yalta",
    "Севастополь":   "sevastopol",
    "Бахчисарай":    "bakhchisaray",
    "Судак":         "sudak",
    "Евпатория":     "evpatoriya",
    "Керчь":         "kerch",
    "Феодосия":      "feodosiya",
    "Алушта":        "alushta",
    "Саки":          "saki",
}

CITY_PREP = {                           # «в Симферополе», «в Ялте», …
    "Симферополь":   "в Симферополе",
    "Ялта":          "в Ялте",
    "Севастополь":   "в Севастополе",
    "Бахчисарай":    "в Бахчисарае",
    "Судак":         "в Судаке",
    "Евпатория":     "в Евпатории",
    "Керчь":         "в Керчи",
    "Феодосия":      "в Феодосии",
    "Алушта":        "в Алуште",
    "Саки":          "в Саках",
}

# ── Утилиты ──────────────────────────────────────────────────────────────────

def esc(text) -> str:
    return html_module.escape(str(text)) if text else ""

def today_str() -> str:
    return date.today().isoformat()

def fmt_date(ds: str) -> str:
    try:
        d = datetime.strptime(ds, "%Y-%m-%d")
        return f"{d.day} {MONTHS_GEN[d.month - 1]}, {DAYS_SHORT[d.weekday()]}"
    except Exception:
        return ds

def city_slug(city: str) -> str:
    return CITY_SLUGS.get(city, city.lower().replace(" ", "-"))

def price_fmt(price) -> tuple[str, str]:
    """Возвращает (текст, css-класс) для тега цены."""
    if not price or str(price) == "null":
        return "", ""
    if price == "бесплатно":
        return "бесплатно", "free"
    return str(price), "price"

def get_source_label(e: dict) -> str:
    ch = e.get("source_channel", "")
    if ch == "yandex_afisha":
        return "Яндекс.Афиша"
    if ch == "krymskiye_dela":
        return f"@{ch} (Instagram)"
    return f"@{ch}"

def get_source_href(e: dict) -> str:
    if e.get("source_url"):
        return e["source_url"]
    ch = e.get("source_channel", "")
    if ch == "krymskiye_dela":
        return f"https://www.instagram.com/{ch}/"
    return f"https://t.me/{ch}"

# ── CSS (извлекаем из index.html, чтобы не дублировать) ──────────────────────

def extract_css() -> str:
    try:
        src = INDEX_FILE.read_text(encoding="utf-8")
        m = re.search(r"<style>(.*?)</style>", src, re.DOTALL)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""

# ── Статический рендер карточки события ──────────────────────────────────────

def render_card(e: dict) -> str:
    artist   = e.get("artist") or ""
    venue    = e.get("venue") or e.get("source_channel") or ""
    city     = e.get("source_city") or ""
    time_    = e.get("time") or ""
    desc     = e.get("description") or ""
    evtype   = e.get("event_type") or ""
    cancelled = e.get("cancelled", False)
    src_href = esc(get_source_href(e))
    src_label = esc(get_source_label(e))
    image    = e.get("image") or ""

    label    = artist or venue
    venue_html = esc(venue) + (f'<span class="city">· {esc(city)}</span>' if artist else "")

    # Теги
    tags = ""
    if cancelled:
        tags += '<span class="tag cancelled-tag">перенесено</span>'
    if evtype:
        tags += f'<span class="tag type">{esc(evtype)}</span>'
    price_text, price_cls = price_fmt(e.get("price"))
    if price_text:
        tags += f'<span class="tag {price_cls}">{esc(price_text)}</span>'

    time_cls = "card-time" if time_ else "card-time no-time"
    time_disp = esc(time_) if time_ else "—"
    desc_html = f'<div class="card-description">{esc(desc)}</div>' if desc else ""
    img_html  = (f'<img class="card-thumb" src="{esc(image)}" alt="{esc(label)}"'
                 f' loading="lazy" onerror="this.remove()">' if image else "")
    cls_extra = " cancelled" if cancelled else ""

    return (
        f'<div class="card{cls_extra}" onclick="window.open(\'{src_href}\',\'_blank\')">'
        f'<div class="card-inner">'
        f'<div class="{time_cls}">{time_disp}</div>'
        f'<div class="card-body">'
        f'<div class="card-artist">{esc(label)}</div>'
        f'<div class="card-venue">{venue_html}</div>'
        f'{desc_html}'
        f'<div class="card-footer">{tags}</div>'
        f'<div class="card-source"><a class="src-link" href="{src_href}" target="_blank"'
        f' rel="noopener">{src_label}</a></div>'
        f'</div>{img_html}</div></div>'
    )

def render_event_list(events: list, today: str) -> str:
    future   = [e for e in events if e.get("date") and e["date"] >= today]
    no_date  = [e for e in events if not e.get("date")]

    if not future and not no_date:
        return '<div class="empty">Событий не найдено</div>'

    groups: dict[str, list] = defaultdict(list)
    for e in future:
        groups[e["date"]].append(e)
    for e in no_date:
        groups["no-date"].append(e)

    parts = []
    for key in sorted(groups, key=lambda k: ("1" if k == "no-date" else k)):
        grp = sorted(groups[key], key=lambda e: e.get("time") or "99:99")
        if key == "no-date":
            label = "Дата уточняется"
        elif key == today:
            label = f'<span class="today-badge">Сегодня</span>{fmt_date(key)}'
        else:
            label = fmt_date(key)
        cards = "\n".join(render_card(e) for e in grp)
        parts.append(f'<div class="date-group"><h2>{label}</h2>\n{cards}\n</div>')

    return "\n".join(parts)

# ── JSON-LD ───────────────────────────────────────────────────────────────────

def make_jsonld_events(events: list) -> str:
    items = []
    for e in events[:30]:
        if not e.get("date"):
            continue
        try:
            datetime.strptime(e["date"], "%Y-%m-%d")
        except ValueError:
            continue

        time_ = e.get("time") or "00:00"
        item: dict = {
            "@type":     "MusicEvent",
            "name":      e.get("artist") or e.get("venue") or "Концерт",
            "startDate": f'{e["date"]}T{time_}:00+03:00',
            "location":  {
                "@type": "MusicVenue",
                "name":  e.get("venue") or "Крым",
                "address": {
                    "@type":         "PostalAddress",
                    "addressLocality": e.get("source_city") or "Крым",
                    "addressCountry": "RU",
                },
            },
        }
        if e.get("description"):
            item["description"] = e["description"]
        if e.get("artist"):
            item["performer"] = {"@type": "MusicGroup", "name": e["artist"]}
        if e.get("image"):
            item["image"] = e["image"]

        price_text, _ = price_fmt(e.get("price"))
        if price_text:
            if price_text == "бесплатно":
                item["offers"] = {"@type": "Offer", "price": "0", "priceCurrency": "RUB",
                                  "availability": "https://schema.org/InStock"}
            else:
                item["offers"] = {"@type": "Offer", "name": price_text,
                                  "priceCurrency": "RUB",
                                  "availability": "https://schema.org/InStock"}

        items.append(item)

    if not items:
        return ""

    schema = {"@context": "https://schema.org", "@graph": items}
    return (
        '<script type="application/ld+json">\n'
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + "\n</script>"
    )


def make_jsonld_breadcrumbs(crumbs: list[tuple[str, str]]) -> str:
    """crumbs: [(label, path), ...]  path может быть пустым для текущей страницы"""
    items = []
    for i, (label, path) in enumerate(crumbs, 1):
        item = {"@type": "ListItem", "position": i, "name": label}
        if path:
            item["item"] = f"{DOMAIN}{path}"
        items.append(item)
    schema = {"@context": "https://schema.org", "@type": "BreadcrumbList",
              "itemListElement": items}
    return (
        '<script type="application/ld+json">\n'
        + json.dumps(schema, ensure_ascii=False)
        + "\n</script>"
    )

# ── Дополнительный CSS для страниц городов ───────────────────────────────────

EXTRA_CSS = """
    .breadcrumbs {
      padding: 8px 24px;
      font-size: 0.8rem;
      color: #999;
      background: #fff;
      border-bottom: 1px solid #f0eeea;
    }
    .breadcrumbs a { color: #999; text-decoration: none; }
    .breadcrumbs a:hover { color: #1a1a1a; }
    .breadcrumbs .sep { margin: 0 5px; }

    .city-nav {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      padding: 10px 24px 8px;
      background: #fff;
      border-bottom: 1px solid #e8e6e0;
      overflow-x: auto;
      scrollbar-width: none;
    }
    .city-nav::-webkit-scrollbar { display: none; }
    .city-nav-link {
      font-size: 0.8rem;
      color: #666;
      text-decoration: none;
      padding: 4px 12px;
      border: 1px solid #e0ddd8;
      border-radius: 16px;
      white-space: nowrap;
      flex-shrink: 0;
      transition: all 0.15s;
    }
    .city-nav-link:hover { border-color: #aaa; color: #1a1a1a; }
    .city-nav-link.current { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }
"""

# ── JS (общая логика для всех страниц) ───────────────────────────────────────

# Логика идентична index.html, но без fetch — события передаются через EVENTS_DATA.
# Для index.html оставляем fetch (для живой фильтрации), но добавляем статику в DOM.

CITY_PAGE_JS = r"""
const MONTHS     = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"];
const MONTHS_NOM = ["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"];
const DAYS = ["вс","пн","вт","ср","чт","пт","сб"];

const today = new Date();
today.setHours(0,0,0,0);
const todayStr = toDateStr(today);

let activePreset   = "";
let activeDateFrom = "";
let activeDateTo   = "";
let calStart = "", calEnd = "", calHover = "";
let viewYear = today.getFullYear(), viewMonth = today.getMonth();

function toDateStr(d) {
  return [d.getFullYear(), String(d.getMonth()+1).padStart(2,"0"), String(d.getDate()).padStart(2,"0")].join("-");
}
function fmtShort(ds) {
  const d = new Date(ds+"T00:00:00");
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}
function getPresetRange(preset) {
  const day = today.getDay();
  if (preset==="today") return {from:todayStr,to:todayStr};
  if (preset==="week") { const e=new Date(today); e.setDate(e.getDate()+6); return {from:todayStr,to:toDateStr(e)}; }
  if (preset==="weekend") {
    let dts = day===6?0:(6-day+7)%7;
    if(dts===0&&day===0) dts=6;
    const sat=new Date(today); sat.setDate(sat.getDate()+dts);
    const sun=new Date(sat); sun.setDate(sun.getDate()+1);
    return day===0?{from:todayStr,to:todayStr}:{from:toDateStr(sat),to:toDateStr(sun)};
  }
  return {from:"",to:""};
}
function setPreset(preset) {
  activePreset = preset;
  if (preset && preset!=="custom") { const r=getPresetRange(preset); activeDateFrom=r.from; activeDateTo=r.to; }
  else if (!preset) { activeDateFrom=""; activeDateTo=""; }
  document.querySelectorAll(".preset-btn").forEach(b=>b.classList.toggle("active",b.dataset.preset===preset));
  updateCustomBtnLabel();
  render();
}
function updateCustomBtnLabel() {
  const btn = document.getElementById("btn-custom");
  if (!btn) return;
  if (activePreset==="custom"&&(activeDateFrom||activeDateTo)) {
    if (activeDateFrom&&activeDateTo&&activeDateFrom!==activeDateTo)
      btn.textContent=`${fmtShort(activeDateFrom)} — ${fmtShort(activeDateTo)}`;
    else btn.textContent=fmtShort(activeDateFrom||activeDateTo);
  } else { btn.textContent="Выбрать даты"; }
}
function openCalendar() {
  viewYear=activeDateFrom?new Date(activeDateFrom+"T00:00:00").getFullYear():today.getFullYear();
  viewMonth=activeDateFrom?new Date(activeDateFrom+"T00:00:00").getMonth():today.getMonth();
  calStart=activeDateFrom; calEnd=activeDateTo; calHover="";
  renderCalendar(); document.getElementById("cal-overlay").classList.add("open");
}
function closeCalendar() { document.getElementById("cal-overlay").classList.remove("open"); calHover=""; }
function renderCalendar() {
  const c=document.getElementById("cal-months"); c.innerHTML="";
  for(let i=0;i<2;i++){let m=viewMonth+i,y=viewYear; if(m>11){m-=12;y++;} c.appendChild(buildMonth(y,m));}
  updateCalLabel();
}
function buildMonth(year,month) {
  const wrap=document.createElement("div"); wrap.className="cal-month";
  const title=document.createElement("div"); title.className="cal-month-title";
  title.textContent=`${MONTHS_NOM[month]} ${year}`; wrap.appendChild(title);
  const grid=document.createElement("div"); grid.className="cal-grid";
  ["пн","вт","ср","чт","пт","сб","вс"].forEach(d=>{const dn=document.createElement("div");dn.className="cal-day-name";dn.textContent=d;grid.appendChild(dn);});
  const firstDay=new Date(year,month,1),startPad=(firstDay.getDay()+6)%7,totalDays=new Date(year,month+1,0).getDate();
  for(let i=0;i<startPad;i++){const el=document.createElement("div");el.className="cal-day cal-empty";grid.appendChild(el);}
  for(let d=1;d<=totalDays;d++){
    const ds=toDateStr(new Date(year,month,d)),el=document.createElement("div");
    el.className="cal-day"; el.textContent=d; el.dataset.date=ds;
    if(ds<todayStr) el.classList.add("cal-past"); else if(ds===todayStr) el.classList.add("cal-today");
    applyDayRange(el,ds); grid.appendChild(el);
  }
  grid.addEventListener("mouseover",e=>{const day=e.target.closest("[data-date]");if(!day||day.classList.contains("cal-past"))return;if(calStart&&!calEnd){calHover=day.dataset.date;refreshAllDays();}});
  grid.addEventListener("mouseleave",()=>{if(calStart&&!calEnd){calHover="";refreshAllDays();}});
  grid.addEventListener("click",e=>{
    const day=e.target.closest("[data-date]");
    if(!day||day.classList.contains("cal-past")||day.classList.contains("cal-empty"))return;
    const ds=day.dataset.date;
    if(!calStart||(calStart&&calEnd)){calStart=ds;calEnd="";calHover="";}
    else{if(ds<=calStart){calEnd=calStart;calStart=ds;}else calEnd=ds;calHover="";}
    refreshAllDays(); updateCalLabel();
  });
  wrap.appendChild(grid); return wrap;
}
function applyDayRange(el,ds){
  el.classList.remove("cal-start","cal-end","cal-in-range");
  const eff=calEnd||calHover; if(!calStart)return;
  const s=calStart<=(eff||calStart)?calStart:eff, e=calStart<=(eff||calStart)?eff:calStart;
  if(!e){if(ds===s)el.classList.add("cal-start","cal-end");return;}
  if(ds===s&&ds===e)el.classList.add("cal-start","cal-end");
  else if(ds===s)el.classList.add("cal-start");
  else if(ds===e)el.classList.add("cal-end");
  else if(ds>s&&ds<e)el.classList.add("cal-in-range");
}
function refreshAllDays(){document.querySelectorAll(".cal-day[data-date]").forEach(el=>applyDayRange(el,el.dataset.date));}
function updateCalLabel(){
  const label=document.getElementById("cal-label");
  if(!calStart&&!calEnd){label.textContent="Выберите даты";return;}
  if(calStart&&!calEnd){label.textContent=fmtShort(calStart);return;}
  const s=calStart<=calEnd?calStart:calEnd,e=calStart<=calEnd?calEnd:calStart;
  label.textContent=s===e?fmtShort(s):`${fmtShort(s)} — ${fmtShort(e)}`;
}
function inDateRange(event) {
  if(!event.date) return true;
  if(event.date<todayStr) return false;
  if(activeDateFrom&&event.date<activeDateFrom) return false;
  if(activeDateTo&&event.date>activeDateTo) return false;
  return true;
}
function isToday(ds){return new Date(ds+"T00:00:00").getTime()===today.getTime();}
function formatDate(ds){const d=new Date(ds+"T00:00:00");return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${DAYS[d.getDay()]}`;}
function getSourceHref(e){
  if(e.source_url) return e.source_url;
  if(e.source_channel==="krymskiye_dela") return `https://www.instagram.com/${e.source_channel}/`;
  return `https://t.me/${e.source_channel}`;
}
function getSourceLabel(e){
  if(e.source_channel==="yandex_afisha") return "Яндекс.Афиша";
  if(e.source_channel==="krymskiye_dela") return `@${e.source_channel} (Instagram)`;
  return `@${e.source_channel}`;
}
function render() {
  const main=document.getElementById("main"); main.innerHTML="";
  const filtered=EVENTS.filter(e=>inDateRange(e));
  if(filtered.length===0){main.innerHTML='<div class="empty">Событий не найдено</div>';return;}
  const groups={};
  filtered.forEach(e=>{const k=e.date||"no-date";if(!groups[k])groups[k]=[];groups[k].push(e);});
  Object.keys(groups).sort((a,b)=>{if(a==="no-date")return 1;if(b==="no-date")return -1;return a.localeCompare(b);}).forEach(key=>{
    const group=document.createElement("div"); group.className="date-group";
    const h2=document.createElement("h2");
    if(key==="no-date"){h2.textContent="Дата уточняется";}
    else if(isToday(key)){const badge=document.createElement("span");badge.className="today-badge";badge.textContent="Сегодня";h2.appendChild(badge);h2.appendChild(document.createTextNode(formatDate(key)));}
    else{h2.textContent=formatDate(key);}
    group.appendChild(h2);
    groups[key].slice().sort((a,b)=>{const ta=a.time,tb=b.time;if(ta&&tb)return ta.localeCompare(tb);if(ta)return -1;if(tb)return 1;return 0;}).forEach(event=>{group.appendChild(makeCard(event));});
    main.appendChild(group);
  });
}
function makeCard(e) {
  const card=document.createElement("div"); card.className="card"+(e.cancelled?" cancelled":"");
  const srcHref=getSourceHref(e);
  card.addEventListener("click",ev=>{if(!ev.target.closest("a"))window.open(srcHref,"_blank");});
  const inner=document.createElement("div"); inner.className="card-inner";
  const time=document.createElement("div"); time.className=e.time?"card-time":"card-time no-time"; time.textContent=e.time||"—"; inner.appendChild(time);
  const body=document.createElement("div"); body.className="card-body";
  const artist=document.createElement("div"); artist.className="card-artist"; artist.textContent=e.artist||e.venue||""; body.appendChild(artist);
  const venue=document.createElement("div"); venue.className="card-venue";
  venue.innerHTML=(e.venue||e.source_channel||"")+(e.artist?`<span class="city">· ${e.source_city}</span>`:"");
  body.appendChild(venue);
  if(e.description){const desc=document.createElement("div");desc.className="card-description";desc.textContent=e.description;body.appendChild(desc);}
  const footer=document.createElement("div"); footer.className="card-footer";
  if(e.cancelled) addTag(footer,"перенесено","cancelled-tag");
  if(e.event_type) addTag(footer,e.event_type,"type");
  if(e.price&&e.price!=="null"){const cls=e.price==="бесплатно"?"free":"price";addTag(footer,e.price==="бесплатно"?"бесплатно":e.price,cls);}
  body.appendChild(footer);
  const srcDiv=document.createElement("div"); srcDiv.className="card-source";
  const srcLink=document.createElement("a"); srcLink.className="src-link"; srcLink.href=srcHref; srcLink.target="_blank"; srcLink.textContent=getSourceLabel(e);
  srcDiv.appendChild(srcLink); body.appendChild(srcDiv); inner.appendChild(body);
  if(e.image){const img=document.createElement("img");img.className="card-thumb";img.src=e.image;img.alt=e.artist||e.venue;img.loading="lazy";img.onerror=()=>img.remove();inner.appendChild(img);}
  card.appendChild(inner); return card;
}
function addTag(container,text,cls){const t=document.createElement("span");t.className=`tag ${cls}`;t.textContent=text;container.appendChild(t);}

// Инит
document.getElementById("date-filter").addEventListener("click",e=>{
  const preset=e.target.closest("[data-preset]"); if(!preset) return;
  const p=preset.dataset.preset;
  if(p==="custom"){openCalendar();return;}
  activePreset===p?setPreset(""):setPreset(p);
});
document.getElementById("cal-overlay").addEventListener("click",e=>{if(e.target===e.currentTarget)closeCalendar();});
document.getElementById("cal-prev").addEventListener("click",()=>{viewMonth--;if(viewMonth<0){viewMonth=11;viewYear--;}renderCalendar();});
document.getElementById("cal-next").addEventListener("click",()=>{viewMonth++;if(viewMonth>11){viewMonth=0;viewYear++;}renderCalendar();});
document.getElementById("cal-btn-clear").addEventListener("click",()=>{calStart="";calEnd="";calHover="";renderCalendar();});
document.getElementById("cal-btn-apply").addEventListener("click",()=>{
  if(calStart||calEnd){
    const s=(!calEnd||calStart<=calEnd)?calStart:calEnd, e=(!calEnd||calStart<=calEnd)?calEnd:calStart;
    activeDateFrom=s||e; activeDateTo=e||s; activePreset="custom";
    document.querySelectorAll(".preset-btn").forEach(b=>b.classList.toggle("active",b.dataset.preset==="custom"));
    updateCustomBtnLabel();
  } else { activeDateFrom=""; activeDateTo=""; setPreset(""); }
  closeCalendar(); render();
});
render();
"""

# ── Шаблон страницы города ───────────────────────────────────────────────────

def make_city_page(
    city: str,
    events: list,
    all_cities: list[str],
    css: str,
) -> str:
    today = today_str()
    slug  = city_slug(city)
    prep  = CITY_PREP.get(city, f"в {city}")
    count = len([e for e in events if (e.get("date") or "") >= today])

    title       = f"Живая музыка и концерты {prep} — Местов.Нет"
    description = (f"Афиша концертов и живой музыки {prep}: "
                   f"ближайшие {count} событий в клубах, барах и на площадках. "
                   f"Обновляется ежедневно.")

    static_content = render_event_list(events, today)
    jsonld_events  = make_jsonld_events([e for e in events if (e.get("date") or "") >= today])
    jsonld_bc      = make_jsonld_breadcrumbs([
        ("Местов.Нет", "/"),
        (city, ""),
    ])

    # Навигация по городам
    nav_links = []
    for c in sorted(all_cities):
        s = city_slug(c)
        cls = " current" if c == city else ""
        nav_links.append(
            f'<a class="city-nav-link{cls}" href="/{("" if c == city else "cities/"+s+".html")}">'
            f'{esc(c)}</a>'
        )
    nav_html = (
        '<nav class="city-nav" aria-label="Города">'
        f'<a class="city-nav-link" href="/">← Все города</a>'
        + "".join(nav_links)
        + "</nav>"
    )

    events_js = json.dumps(events, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" type="image/png" href="/images/fav.png">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:type" content="website">
  <link rel="canonical" href="{DOMAIN}/cities/{slug}.html">
  <style>{css}{EXTRA_CSS}</style>
  {jsonld_events}
  {jsonld_bc}
</head>
<body>
<header>
  <h1><a href="/" style="text-decoration:none;color:inherit">Местов.Нет</a></h1>
  <p>Живая музыка {prep}</p>
</header>

<nav class="breadcrumbs" aria-label="Хлебные крошки">
  <a href="/">Местов.Нет</a>
  <span class="sep">/</span>
  <span>{esc(city)}</span>
</nav>

{nav_html}

<div class="toolbar" id="toolbar">
  <div class="date-filter" id="date-filter">
    <button class="preset-btn" data-preset="today">Сегодня</button>
    <button class="preset-btn" data-preset="weekend">Выходные</button>
    <button class="preset-btn" data-preset="week">Неделя</button>
    <button class="preset-btn" data-preset="custom" id="btn-custom">Выбрать даты</button>
  </div>
</div>

<div class="cal-overlay" id="cal-overlay">
  <div class="cal-modal" id="cal-modal">
    <div class="cal-nav-row">
      <button class="cal-nav" id="cal-prev">&#8249;</button>
      <div class="cal-months" id="cal-months"></div>
      <button class="cal-nav" id="cal-next">&#8250;</button>
    </div>
    <div class="cal-actions">
      <button class="cal-btn-clear" id="cal-btn-clear">Сбросить</button>
      <span class="cal-range-label" id="cal-label">Выберите даты</span>
      <button class="cal-btn-apply" id="cal-btn-apply">Применить</button>
    </div>
  </div>
</div>

<main id="main">
{static_content}
</main>

<script>
let EVENTS = {events_js};
{CITY_PAGE_JS}
</script>
</body>
</html>"""

# ── Обновление index.html ─────────────────────────────────────────────────────

def update_index(events: list, css_exists: bool) -> str:
    """Читает текущий index.html и добавляет JSON-LD + статический пре-рендер."""
    src = INDEX_FILE.read_text(encoding="utf-8")
    today = today_str()
    future = [e for e in events if (e.get("date") or "") >= today]

    # JSON-LD для событий
    jsonld_events = make_jsonld_events(future)

    # Улучшенный title и description
    count = len(future)
    new_title = "Местов.Нет — живая музыка в Крыму"
    new_desc  = (f"Афиша концертов и живой музыки в Крыму: {count} ближайших событий "
                 f"в Симферополе, Ялте, Севастополе и других городах. "
                 f"Клубы, бары, площадки — всё в одном месте.")

    # Обновляем <title>
    src = re.sub(
        r"<title>.*?</title>",
        f"<title>{esc(new_title)}</title>",
        src,
    )

    # Добавляем/заменяем <meta name="description"
    if '<meta name="description"' in src:
        src = re.sub(
            r'<meta name="description"[^>]+>',
            f'<meta name="description" content="{esc(new_desc)}">',
            src,
        )
    else:
        src = src.replace(
            '<meta name="viewport"',
            f'<meta name="description" content="{esc(new_desc)}">\n  <meta name="viewport"',
        )

    # Canonical
    canonical_tag = f'<link rel="canonical" href="{DOMAIN}/">'
    if '<link rel="canonical"' not in src:
        src = src.replace("</head>", f"  {canonical_tag}\n</head>")

    # Open Graph
    og_tags = (
        f'<meta property="og:title" content="{esc(new_title)}">\n'
        f'  <meta property="og:description" content="{esc(new_desc)}">\n'
        f'  <meta property="og:type" content="website">\n'
    )
    if '<meta property="og:title"' not in src:
        src = src.replace("</head>", f"  {og_tags}</head>")

    # JSON-LD: вставляем перед </head>
    if '<script type="application/ld+json">' not in src and jsonld_events:
        src = src.replace("</head>", f"  {jsonld_events}\n</head>")

    # Статический пре-рендер событий: заменяем скелетоны в <main>
    static_html = render_event_list(future, today)
    src = re.sub(
        r'(<main id="main">)(.*?)(</main>)',
        lambda m: f'{m.group(1)}\n{static_html}\n{m.group(3)}',
        src,
        flags=re.DOTALL,
    )

    return src

# ── sitemap.xml ───────────────────────────────────────────────────────────────

def make_sitemap(cities: list[str]) -> str:
    today = today_str()
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']

    def url(loc, freq, priority):
        return (f"  <url><loc>{loc}</loc>"
                f"<changefreq>{freq}</changefreq>"
                f"<priority>{priority}</priority>"
                f"<lastmod>{today}</lastmod></url>")

    lines.append(url(f"{DOMAIN}/", "daily", "1.0"))
    for c in sorted(cities):
        s = city_slug(c)
        lines.append(url(f"{DOMAIN}/cities/{s}.html", "daily", "0.8"))

    lines.append("</urlset>")
    return "\n".join(lines)

# ── robots.txt ────────────────────────────────────────────────────────────────

def make_robots() -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {DOMAIN}/sitemap.xml\n"

# ── Главная функция ───────────────────────────────────────────────────────────

def main() -> None:
    print("📖  Читаем events.json …")
    events: list[dict] = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    print(f"    {len(events)} событий загружено")

    today  = today_str()
    css    = extract_css()

    # Города, для которых есть события
    cities_with_events: list[str] = sorted(
        {e["source_city"] for e in events if e.get("source_city")}
    )

    # 1. Обновляем index.html
    print("📝  Обновляем index.html …")
    new_index = update_index(events, bool(css))
    INDEX_FILE.write_text(new_index, encoding="utf-8")
    print("    ✓ index.html обновлён")

    # 2. Генерируем страницы городов
    cities_dir = BASE_DIR / "cities"
    cities_dir.mkdir(exist_ok=True)
    print(f"🏙   Генерируем страницы городов ({len(cities_with_events)}) …")
    for city in cities_with_events:
        city_events = [e for e in events if e.get("source_city") == city]
        slug = city_slug(city)
        page = make_city_page(city, city_events, cities_with_events, css)
        out  = cities_dir / f"{slug}.html"
        out.write_text(page, encoding="utf-8")
        future_count = len([e for e in city_events if (e.get("date") or "") >= today])
        print(f"    ✓ cities/{slug}.html  ({future_count} событий)")

    # 3. sitemap.xml
    print("🗺   Генерируем sitemap.xml …")
    sitemap = make_sitemap(cities_with_events)
    (BASE_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    print("    ✓ sitemap.xml")

    # 4. robots.txt
    robots = make_robots()
    (BASE_DIR / "robots.txt").write_text(robots, encoding="utf-8")
    print("    ✓ robots.txt")

    print("\n✅  Готово! Все страницы сгенерированы.")
    print(f"    Города: {', '.join(cities_with_events)}")
    print(f"\n💡  Следующий шаг: отправьте sitemap.xml в Яндекс.Вебмастер и Google Search Console:")
    print(f"    {DOMAIN}/sitemap.xml")


if __name__ == "__main__":
    main()
