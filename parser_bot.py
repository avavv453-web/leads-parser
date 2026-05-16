import os
import time
import hashlib
import logging
import schedule
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from telegram import Bot
from telegram.error import TelegramError

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

KEYWORDS = [
    "сайт", "лендінг", "лендинг", "посадкова", "посадочна",
    "розробка сайту", "зробити сайт", "потрібен сайт", "потрібний сайт",
    "інтернет магазин", "інтернет-магазин", "онлайн магазин",
    "wordpress", "вордпрес", "tilda", "тільда",
    "сделать сайт", "нужен сайт", "разработка сайта",
    "таргет", "таргетолог", "таргетована реклама", "налаштування реклами",
    "реклама facebook", "реклама instagram", "реклама фейсбук",
    "просування", "таргетированная реклама", "настройка рекламы",
    "розсилка", "email розсилка", "tg розсилка", "рассылка", "email рассылка",
    "дизайн сайту", "дизайн сайта", "веб дизайн", "ui дизайн",
    "логотип", "брендинг", "фірмовий стиль", "фирменный стиль",
    "банер", "баннер", "креатив", "крео",
    "smm", "ведення соцмереж", "ведение соцсетей", "контент план",
    "landing page", "web design", "website", "web developer",
    "facebook ads", "instagram ads", "google ads", "email marketing",
    "smm manager", "graphic design", "logo design", "branding",
    "потрібно", "потрібен", "потрібна", "шукаю", "замовити",
    "looking for", "need a", "need someone", "hire", "project",
    "нужен", "ищу", "требуется",
]

STOP_WORDS = [
    "$/hour", "$/hr", "/hour", "per hour", "hourly",
    "грн/год", "$/час", "uah/hour",
    "full-time", "fulltime", "full time",
    "part-time", "parttime", "part time",
    "permanent", "employee", "employment",
    "join our team", "join our company",
    "we are hiring", "we're hiring", "we are looking for a",
    "vacancy", "вакансія", "вакансия",
    "salary", "зарплата", "оклад", "ставка",
    "i offer", "i provide", "i am offering", "my services",
    "hire me", "check my portfolio", "i can help you",
    "пропоную послуги", "надаю послуги", "мої послуги",
    "предлагаю услуги", "мои услуги",
    "займ", "кредит", "казино", "ставки",
]

SEEN_IDS_FILE = "seen_ids.txt"
CHECK_INTERVAL_MINUTES = 15

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

def load_seen_ids():
    if not os.path.exists(SEEN_IDS_FILE):
        return set()
    with open(SEEN_IDS_FILE, "r") as f:
        return set(line.strip() for line in f.readlines())

def save_seen_id(uid):
    with open(SEEN_IDS_FILE, "a") as f:
        f.write(uid + "\n")

def make_id(text):
    return hashlib.md5(text.encode()).hexdigest()

def contains_keyword(text):
    t = text.lower()
    return any(kw.lower() in t for kw in KEYWORDS)

def is_spam(text):
    t = text.lower()
    return any(sw.lower() in t for sw in STOP_WORDS)

def send_to_telegram(message):
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info("Sent to Telegram")
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def format_message(source, title, description, link):
    msg = f"\U0001f514 <b>Новий запит [{source}]</b>\n\n"
    msg += f"\U0001f4cc <b>{title[:200]}</b>\n\n"
    if description and description.strip():
        desc = description.strip()[:500]
        if len(description.strip()) > 500:
            desc += "..."
        msg += f"{desc}\n\n"
    msg += f"\U0001f517 <a href='{link}'>Відкрити</a>"
    return msg

def parse_rss(source, url):
    seen = load_seen_ids()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"{source}: status {resp.status_code}")
            return
        root = ET.fromstring(resp.content)
        items = root.findall('.//item')
        if not items:
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            items = root.findall('.//atom:entry', ns)
        for item in items[:30]:
            title_el = item.find('title')
            link_el = item.find('link')
            desc_el = item.find('description') or item.find('summary')
            if title_el is None:
                continue
            title = (title_el.text or "").strip()
            link = ""
            if link_el is not None:
                link = link_el.text or link_el.get('href', '')
            link = (link or "").strip()
            desc = ""
            if desc_el is not None and desc_el.text:
                desc = BeautifulSoup(desc_el.text, "html.parser").get_text()
            uid = make_id(link or title)
            if uid in seen:
                continue
            full_text = title + " " + desc
            if contains_keyword(full_text) and not is_spam(full_text):
                send_to_telegram(format_message(source, title, desc, link))
                save_seen_id(uid)
                time.sleep(2)
        logger.info(f"{source}: OK")
    except Exception as e:
        logger.error(f"{source} error: {e}")

def parse_freelance_ua():
    """
    Парсер freelance.ua - UA фріланс біржа
    Категорії: сайти, дизайн, SMM, маркетинг, реклама, email
    Spec IDs:
      132 - Сайт под ключ
      131 - Интернет-магазины
      130 - Доработка сайтов
      129 - Верстка
      52  - Дизайн сайта
      58  - Логотипы
      136 - SMM (Продвижение в соцсетях)
      175 - Интернет-маркетинг
      176 - Email-маркетинг
      96  - Контекстная реклама
      114 - Веб-программирование
      49  - Баннеры
    """
    source = "freelance.ua"
    seen = load_seen_ids()

    # Формуємо URL з фільтром по потрібних категоріях
    spec_ids = [132, 131, 130, 129, 52, 58, 136, 175, 176, 96, 114, 49]
    params = "&".join([f"specs[]={sid}" for sid in spec_ids])
    url = f"https://freelance.ua/ru/orders/?{params}"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"{source}: status {resp.status_code}")
            return

        soup = BeautifulSoup(resp.text, "html.parser")
        orders = soup.find_all(class_="j-order")

        if not orders:
            logger.warning(f"{source}: no orders found on page")
            return

        for order in orders[:30]:
            # Заголовок та посилання
            title_el = order.find(class_="l-project-title")
            if not title_el:
                continue
            link_el = title_el.find("a")
            if not link_el:
                continue

            title = link_el.get_text(strip=True)
            link = link_el.get("href", "")
            if not link.startswith("http"):
                link = "https://freelance.ua" + link

            # Опис
            desc_el = order.find(class_="l-project-description")
            if not desc_el:
                desc_el = order.find("p")
            desc = desc_el.get_text(strip=True) if desc_el else ""

            # Теги
            tags_els = order.find_all(class_=lambda c: c and "tag" in c.lower())
            tags = " ".join([t.get_text(strip=True) for t in tags_els])

            uid = make_id(link or title)
            if uid in seen:
                continue

            full_text = title + " " + desc + " " + tags
            # freelance.ua вже відфільтрований по категоріях - беремо всі замовлення
            # але все одно перевіряємо стоп-слова (вакансії "в компанію")
            if not is_spam(full_text):
                msg_text = desc if desc else tags
                send_to_telegram(format_message(source, title, msg_text, link))
                save_seen_id(uid)
                time.sleep(2)

        logger.info(f"{source}: OK, found {len(orders)} orders")
    except Exception as e:
        logger.error(f"{source} error: {e}")

def parse_telegram_channels():
    channels = [
        "ukr_freelance_jobs",
        "freelance_ukraine",
        "zamovlennya_ua",
        "freelance_jobs_ua",
    ]
    seen = load_seen_ids()
    for channel in channels:
        try:
            url = f"https://t.me/s/{channel}"
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            messages = soup.find_all("div", class_="tgme_widget_message_text")
            date_links = soup.find_all("a", class_="tgme_widget_message_date")
            for i, msg_el in enumerate(messages[-25:]):
                text = msg_el.get_text(separator=" ").strip()
                if len(text) < 20:
                    continue
                uid = make_id(channel + text[:120])
                if uid in seen:
                    continue
                if contains_keyword(text) and not is_spam(text):
                    post_link = f"https://t.me/{channel}"
                    try:
                        real_i = len(messages) - 25 + i
                        if 0 <= real_i < len(date_links):
                            post_link = date_links[real_i].get("href", post_link)
                    except:
                        pass
                    send_to_telegram(format_message(f"Telegram @{channel}", text[:100], text, post_link))
                    save_seen_id(uid)
                    time.sleep(2)
            logger.info(f"TG @{channel}: OK")
            time.sleep(3)
        except Exception as e:
            logger.error(f"TG @{channel} error: {e}")

def run_all_parsers():
    logger.info("=" * 50)
    logger.info("Start parsing...")

    # ===== УКРАЇНА =====
    parse_freelance_ua()   # Головний UA джерело - з фільтром по категоріях
    parse_rss("FreelanceHunt", "https://freelancehunt.com/projects/feed")
    parse_rss("Kabanchik UA", "https://kabanchik.ua/ua/tasks/feed")
    parse_rss("Weblancer", "https://www.weblancer.net/jobs/feed/rss/")

    # ===== ЄВРОПА / МІЖНАРОДНІ =====
    parse_rss("PeoplePerHour", "https://www.peopleperhour.com/job-feed/rss")
    parse_rss("Freelancer Web", "https://www.freelancer.com/rss/category/3.xml")
    parse_rss("Freelancer Design", "https://www.freelancer.com/rss/category/4.xml")
    parse_rss("Freelancer Marketing", "https://www.freelancer.com/rss/category/7.xml")
    parse_rss("Guru.com", "https://www.guru.com/jobs/feed.aspx")
    parse_rss("Upwork webdev", "https://www.upwork.com/ab/feed/jobs/rss?q=web+development&sort=recency")
    parse_rss("Upwork landing", "https://www.upwork.com/ab/feed/jobs/rss?q=landing+page&sort=recency")
    parse_rss("Upwork smm", "https://www.upwork.com/ab/feed/jobs/rss?q=smm+social+media&sort=recency")
    parse_rss("Upwork design", "https://www.upwork.com/ab/feed/jobs/rss?q=web+design+logo&sort=recency")
    parse_rss("Upwork ads", "https://www.upwork.com/ab/feed/jobs/rss?q=facebook+instagram+ads&sort=recency")
    parse_rss("Upwork email", "https://www.upwork.com/ab/feed/jobs/rss?q=email+marketing&sort=recency")

    # ===== TELEGRAM =====
    parse_telegram_channels()

    logger.info("Parsing done.")

if __name__ == "__main__":
    logger.info("Parser started.")
    run_all_parsers()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_all_parsers)
    while True:
        schedule.run_pending()
        time.sleep(30)
