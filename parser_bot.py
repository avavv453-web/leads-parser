import os
import time
import hashlib
import logging
import schedule
import feedparser
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.error import TelegramError

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

KEYWORDS = [
    "сайт", "лендинг", "landing", "website", "веб", "web",
    "разработка сайта", "сделать сайт", "нужен сайт", "создать сайт",
    "интернет магазин", "интернет-магазин", "онлайн магазин",
    "wordpress", "вордпресс", "tilda", "тильда",
    "таргет", "таргетолог", "таргетированная реклама",
    "реклама facebook", "реклама instagram", "реклама вконтакте",
    "настройка рекламы", "реклама google", "контекстная реклама",
    "smm", "продвижение", "раскрутка",
    "рассылка", "email рассылка", "telegram рассылка", "тг рассылка",
    "вк рассылка", "мессенджер рассылка", "newsletter",
    "дизайн", "баннер", "креатив", "крео", "graphic design",
    "логотип", "фирменный стиль", "брендинг",
    "web developer", "web design", "frontend", "backend",
    "target ads", "facebook ads", "instagram ads", "google ads",
    "email marketing", "smm manager", "content manager",
    "freelance", "нужен фрилансер", "ищу исполнителя", "ищу подрядчика",
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
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in KEYWORDS)

def send_to_telegram(message):
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="HTML", disable_web_page_preview=True)
        logger.info("Отправлено в Telegram")
    except TelegramError as e:
        logger.error(f"Ошибка Telegram: {e}")

def format_message(source, title, description, link, contact=None):
    msg = f"🔔 <b>Новый запрос [{source}]</b>\n\n"
    msg += f"📌 <b>{title[:200]}</b>\n\n"
    if description:
        msg += f"{description[:500]}{'...' if len(description) > 500 else ''}\n\n"
    if contact:
        msg += f"👤 Контакт: {contact}\n"
    msg += f"🔗 <a href=\'{link}\'>Открыть</a>"
    return msg

def parse_rss(source, url):
    seen = load_seen_ids()
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            uid = make_id(entry.get("link", entry.get("title", "")))
            if uid in seen:
                continue
            title = entry.get("title", "")
            desc = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text()
            link = entry.get("link", "")
            if contains_keyword(title + " " + desc):
                send_to_telegram(format_message(source, title, desc, link))
                save_seen_id(uid)
                time.sleep(1)
        logger.info(f"{source}: проверено")
    except Exception as e:
        logger.error(f"{source} ошибка: {e}")

def parse_reddit():
    subreddits = ["forhire", "slavelabour", "ukraineforhire", "hiring", "freelance"]
    seen = load_seen_ids()
    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
            resp = requests.get(url, headers={**HEADERS, "User-Agent": "LeadParserBot/1.0"}, timeout=10)
            if resp.status_code != 200:
                continue
            posts = resp.json().get("data", {}).get("children", [])
            for post in posts:
                d = post.get("data", {})
                uid = d.get("id", "")
                if uid in seen:
                    continue
                title = d.get("title", "")
                desc = d.get("selftext", "")
                link = "https://reddit.com" + d.get("permalink", "")
                if contains_keyword(title + " " + desc):
                    send_to_telegram(format_message(f"Reddit r/{sub}", title, desc, link))
                    save_seen_id(uid)
                    time.sleep(1)
            logger.info(f"Reddit r/{sub}: проверено")
            time.sleep(2)
        except Exception as e:
            logger.error(f"Reddit r/{sub} ошибка: {e}")

def parse_telegram_channels():
    channels = [
        "freelance_ua", "freelance_jobs_ua", "tenders_ua",
        "web_freelance", "it_jobs_ukraine", "smm_freelance",
        "freelance_europe", "freelancers_chat",
    ]
    seen = load_seen_ids()
    for channel in channels:
        try:
            url = f"https://t.me/s/{channel}"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            messages = soup.find_all("div", class_="tgme_widget_message_text")
            links_els = soup.find_all("a", class_="tgme_widget_message_date")
            for i, msg in enumerate(messages[-20:]):
                text = msg.get_text()
                uid = make_id(channel + text[:100])
                if uid in seen:
                    continue
                if contains_keyword(text):
                    post_link = ""
                    try:
                        post_link = links_els[i].get("href", f"https://t.me/{channel}")
                    except:
                        post_link = f"https://t.me/{channel}"
                    send_to_telegram(format_message(f"Telegram @{channel}", text[:100], text, post_link))
                    save_seen_id(uid)
                    time.sleep(1)
            logger.info(f"Telegram @{channel}: проверено")
            time.sleep(2)
        except Exception as e:
            logger.error(f"Telegram @{channel} ошибка: {e}")

def run_all_parsers():
    logger.info("=" * 50)
    logger.info("Запуск парсинга всех источников...")
    parse_rss("FreelanceHunt", "https://freelancehunt.com/projects/feed")
    parse_rss("Kabanchik", "https://kabanchik.ua/ua/news/feed")
    parse_rss("FL.ru", "https://www.fl.ru/rss/all.xml")
    parse_rss("Weblancer", "https://www.weblancer.net/jobs/feed/rss/")
    parse_rss("PeoplePerHour", "https://www.peopleperhour.com/job-feed/rss")
    parse_rss("Freelancer Web", "https://www.freelancer.com/rss/category/3.xml")
    parse_rss("Freelancer Design", "https://www.freelancer.com/rss/category/4.xml")
    parse_rss("Freelancer Marketing", "https://www.freelancer.com/rss/category/7.xml")
    parse_rss("Upwork web", "https://www.upwork.com/ab/feed/jobs/rss?q=web+development&sort=recency")
    parse_rss("Upwork smm", "https://www.upwork.com/ab/feed/jobs/rss?q=smm&sort=recency")
    parse_rss("Upwork ads", "https://www.upwork.com/ab/feed/jobs/rss?q=facebook+ads&sort=recency")
    parse_rss("Upwork landing", "https://www.upwork.com/ab/feed/jobs/rss?q=landing+page&sort=recency")
    parse_reddit()
    parse_telegram_channels()
    logger.info("Парсинг завершён.")

if __name__ == "__main__":
    logger.info("Парсер лидов запущен.")
    run_all_parsers()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_all_parsers)
    while True:
        schedule.run_pending()
        time.sleep(30)
