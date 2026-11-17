import os
import requests
import time
import logging
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import (
    BASE_URL,
    RULES_URL,
    STAFFOUNT_MANUAL_URL,
    SALARY_TEMPLATE_URL,
    BONUS_TEMPLATE_URL,
    FORM_TARGET_KEYS,
    HEALTH_PORT,
)

# ==================== ЛОГИ ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("salary-bot")

# ==================== СЕССИИ ====================
user_sessions = {}

# ==================== ХЕЛПЕРЫ ====================
def _get(upd, *path, default=None):
    cur = upd
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
        if cur is None:
            return default
    return cur if cur is not None else default

def get_sender_info(upd):
    user = _get(upd, "user") or {}
    return {
        "user_id": user.get("id"),
        "first_name": (user.get("firstName") or "").strip(),
        "last_name": (user.get("lastName") or "").strip(),
        "user_name": (user.get("userName") or "").strip(),
    }

def format_sender(info):
    un = info.get("user_name")
    if un:
        return f"@{un}"
    full = " ".join(x for x in (info.get("first_name"), info.get("last_name")) if x)
    if full:
        return full
    if info.get("user_id"):
        return f"user.id {info['user_id']}"
    return "—"

# ==================== ТЕКСТЫ ====================
WELCOME_TEXT = (
    "👋 [b]Добро пожаловать, коллега![/b]\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "Данный чат-бот создан для руководителей, а также HR-специалистов, "
    "и используется в процессах расчёта и выплаты новогодней премии, "
    "а также для пересмотра заработной платы сотрудникам в рамках "
    "периметра [b]G&S[/b] для всех гео и типов оформления.\n\n"
    "👇 [i]Выберите раздел в меню ниже:[/i]"
)

RULES_TEXT = (
    "⚠️ Перед отправкой формы на пересмотр оклада внимательно "
    "ознакомьтесь с правилами и описанием процесса по ссылке.\n\n"
    f"🔗 [url={RULES_URL}][b]Правила тут[/b][/url]"
)

STAFFOUNT_INTRO = (
    "📖 [b]Инструкции Staffount[/b]\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "Чтобы перенос процесса ежегодного пересмотра заработных плат "
    "и новогоднего премирования в Staffount стал проще и понятнее, "
    "мы подготовили инструкцию по работе с системой.\n\n"
    f"🔗 [url={STAFFOUNT_MANUAL_URL}][b]Открыть инструкцию[/b][/url] "
    "[i](для премий и для ЗП)[/i]\n\n"
    "👇 [i]Выберите раздел:[/i]"
)

SALARY_INSTRUCTION_TEXT = (
    "💰 [b]Заработная плата — процесс в Staffount[/b]\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "1️⃣ В каждом департаменте назначены ответственные HR-специалисты "
    "и/или руководители, подающие заявки на пересмотр заработных плат "
    "в Staffount.\n\n"
    "2️⃣ Ответственный, используя шаблон формы на пересмотр оклада "
    f"([url={SALARY_TEMPLATE_URL}]форма пересмотра ЗП[/url]), собирает данные "
    "по сотрудникам своего подразделения в форму. Заполненную форму "
    "отправляет для проверки HR BP в этот бот.\n\n"
    "3️⃣ После сверки HR BP ответственный переносит данные из формы "
    "на пересмотр окладов в Staffount и запускает цепочку согласований.\n\n"
    "4️⃣ Заявки в Staffount проходят установленную для вашего департамента "
    "цепочку согласования и доходят до HR BP.\n\n"
    "5️⃣ HR BP передаёт форму на верификацию C&B холдинга.\n\n"
    "6️⃣ После C&B верификации HR BP передаёт формы на пересмотр окладов "
    "на согласование C-level руководителю бизнес-юнита.\n\n"
    "7️⃣ C-level руководитель после своего одобрения направляет форму "
    "пересмотра окладов на согласование Управляющему партнёру.\n\n"
    "8️⃣ HR BP согласовывает или отклоняет заявки в Staffount исходя "
    "из согласованного Управляющим партнёром файла. По скорректированным "
    "суммам ответственные создают новые заявки на пересмотр в Staffount.\n\n"
    "9️⃣ После финального согласования заявки на пересмотр передаются "
    "ответственным по ГЕО и финансистам подразделения для проведения изменений.\n\n"
    "⚠️ [b]Важно:[/b] перед внесением заявок убедитесь в том, что все "
    "текущие заработные платы в Staffount внесены корректно.\n\n"
    "Если в процессе возникают сложности или ошибки, пожалуйста, обратитесь "
    "за помощью к [b]Olga T[/b] (Reddy: [code]89818711942[/code])."
)

BONUS_INSTRUCTION_TEXT = (
    "🎁 [b]Премия — процесс в Staffount[/b]\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "1️⃣ В каждом департаменте назначены ответственные HR-специалисты "
    "и/или руководители, подающие заявки на премирование в Staffount.\n\n"
    "2️⃣ Ответственный, используя шаблон формы на премирование "
    f"([url={BONUS_TEMPLATE_URL}]форма Премия[/url]), собирает данные "
    "по сотрудникам своего подразделения в форму.\n\n"
    "3️⃣ Заполненные формы передаются на согласование руководителю "
    "департамента.\n\n"
    "4️⃣ Руководитель департамента в этот бот направляет HR BP "
    "согласованный файл для верификации.\n\n"
    "5️⃣ HR BP передаёт формы на премирование на согласование C-level "
    "руководителю бизнес-юнита.\n\n"
    "6️⃣ После полного согласования ответственный переносит данные из формы "
    "в ведомость на премирование в Staffount. Для крупных команд "
    "([b]200+ сотрудников[/b]) будет предоставлена возможность экспортировать "
    "данные формы в систему без ручного ввода.\n\n"
    "7️⃣ После финального согласования ведомости на премию передаются "
    "ответственным по ГЕО и финансистам подразделения для проведения выплаты.\n\n"
    "⚠️ [b]Важно:[/b] перед внесением заявок убедитесь в том, что все "
    "текущие заработные платы в Staffount внесены корректно.\n\n"
    "Если в процессе возникают сложности или ошибки, пожалуйста, обратитесь "
    "за помощью к [b]Olga T[/b] (Reddy: [code]89818711942[/code])."
)

TEMPLATES_TEXT = (
    "📋 [b]Шаблоны форм[/b]\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "⚠️ Перед началом работы с формами необходимо скопировать их для себя:\n\n"
    "1️⃣ В верхнем меню выберите пункт «Файл».\n\n"
    "2️⃣ Далее нажмите на «Создать копию». Таким образом, вы получите свою "
    "копию таблицы, с которой сможете работать.\n\n"
    "3️⃣ После того как таблица скопирована, откройте её в появившемся окне "
    "и нажмите на «Настройки доступа».\n\n"
    "4️⃣ В поле для ввода адресов электронной почты введите адрес "
    "[code]andreeva.ek@mailbox366.com[/code] и выберите уровень доступа "
    "«Редактирование». Далее — нажмите «Готово», чтобы сохранить настройки.\n\n"
    "5️⃣ После заполнения формы на пересмотр оклада необходимо через этот "
    "бот направить её на верификацию HR BP.\n\n"
    "6️⃣ [b]Форма на премирование направляется HR BP после согласования "
    "Руководителем департамента.[/b]\n\n"
    "📎 [b]Формы:[/b]\n"
    f"💰 [url={SALARY_TEMPLATE_URL}][b]Форма ЗП[/b][/url]\n"
    f"🎁 [url={BONUS_TEMPLATE_URL}][b]Форма Премии[/b][/url]"
)

DEADLINES_MENU_TEXT = (
    "📅 [b]Сроки подачи материалов[/b]\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "👇 [i]Выберите раздел:[/i]"
)

SALARY_DEADLINES_TEXT = (
    "📊 [b]Пересмотры заработных плат[/b]\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "☀️ [b]Летняя сессия[/b]\n\n"
    "1️⃣ [b]15.05 — 10.06[/b] — подготовка заявок по пересмотру, внесение "
    "в Staffount, передача HR BP.\n\n"
    "2️⃣ [b]10.06 — 20.06[/b] — согласование с C-level руководителем "
    "бизнес-юнита, включая все обязательные внутренние и верхнеуровневые "
    "согласования.\n\n"
    "3️⃣ [b]20.06 — 30.06[/b] — перенос данных в Staffount.\n\n"
    "4️⃣ [b]20.06 — 30.06[/b] — передача согласованных материалов "
    "ответственным по гео и подразделениям финансистам для проведения "
    "изменений.\n\n"
    "📌 Изменения вступают в силу с [b]01.07[/b].\n"
    "Таким образом, новую ЗП сотрудники получат в августе.\n\n"
    "❄️ [b]Зимняя сессия[/b]\n\n"
    "1️⃣ [b]16.11 — 30.11[/b] — подготовка заявок по пересмотру, внесение "
    "в Staffount, передача HR BP.\n\n"
    "2️⃣ [b]01.12 — 10.12[/b] — передача заявок на верификацию C&B холдинга.\n\n"
    "3️⃣ [b]10.12 — 14.12[/b] — согласование с C-level руководителем "
    "бизнес-юнита, включая все обязательные внутренние и верхнеуровневые "
    "согласования.\n\n"
    "4️⃣ [b]20.12 — 30.12[/b] — передача согласованных материалов "
    "ответственным по гео и подразделениям финансистам для проведения "
    "изменений.\n\n"
    "📌 Изменения вступают в силу с [b]01.01[/b].\n"
    "Таким образом, новую ЗП сотрудники получат в феврале."
)

BONUS_DEADLINES_TEXT = (
    "🎄 [b]Новогоднее премирование[/b]\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "1️⃣ [b]16.11 — 07.12[/b] — подготовка заявок на премии, передача HR BP.\n\n"
    "2️⃣ [b]07.12 — 11.12[/b] — согласование с C-level руководителем "
    "бизнес-юнита, включая все обязательные внутренние и верхнеуровневые "
    "согласования.\n\n"
    "3️⃣ [b]11.12 — 20.12[/b] — перенос данных в Staffount.\n\n"
    "4️⃣ [b]11.12 — 15.12[/b] — передача согласованных материалов "
    "ответственным по гео и подразделениям финансистам для проведения "
    "изменений."
)

SEND_FORM_PROMPT = (
    "📤 [b]Отправка формы на верификацию[/b]\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "Отправьте ссылку на заполненную форму (Google Sheets / Drive). "
    "Она будет направлена [b]HR BP[/b] на верификацию.\n\n"
    "⚠️ Убедитесь, что форма доступна по ссылке для просмотра "
    "(«Настройки доступа» → «Редактирование» для "
    "[code]andreeva.ek@mailbox366.com[/code])."
)

SEND_FORM_INVALID = (
    "⚠️ Похоже, это не ссылка. Пожалуйста, отправьте ссылку на форму "
    "(она начинается с [code]http[/code]).\n\n"
    "Или нажмите «Отмена», чтобы вернуться в меню."
)

SEND_FORM_OK = (
    "✅ [b]Ссылка отправлена HR BP на верификацию.[/b]\n\n"
    "Мы свяжемся с вами, если понадобятся уточнения."
)

SEND_FORM_NO_TARGET = (
    "⚠️ Получатель для форм не настроен. Обратитесь к администратору бота."
)

# ==================== КЛАВИАТУРЫ ====================
def main_menu_keyboard():
    return [
        [
            {"type": "action", "data": "menu_rules",
             "title": "📚 Правила пересмотра"},
            {"type": "action", "data": "menu_staffount",
             "title": "📖 Инструкции Staffount"},
        ],
        [
            {"type": "action", "data": "menu_templates",
             "title": "📋 Шаблоны форм"},
            {"type": "action", "data": "menu_deadlines",
             "title": "📅 Сроки подачи"},
        ],
        [
            {"type": "action", "data": "menu_send_form",
             "title": "📤 Отправить форму"},
        ],
    ]

def back_keyboard():
    return [[{"type": "command", "data": "/start", "title": "🏠 Главное меню"}]]

def cancel_keyboard():
    return [[{"type": "command", "data": "/cancel", "title": "❌ Отмена"}]]

def staffount_keyboard():
    return [
        [{"type": "action", "data": "staffount_salary",
          "title": "💰 Заработная плата"}],
        [{"type": "action", "data": "staffount_bonus",
          "title": "🎁 Премия"}],
        [{"type": "command", "data": "/start",
          "title": "🏠 Главное меню"}],
    ]

def deadlines_keyboard():
    return [
        [{"type": "action", "data": "deadlines_salary",
          "title": "📊 Пересмотры заработных плат"}],
        [{"type": "action", "data": "deadlines_bonus",
          "title": "🎄 Новогоднее премирование"}],
        [{"type": "command", "data": "/start",
          "title": "🏠 Главное меню"}],
    ]

# ==================== ОТПРАВКА ====================
def send_message(chat_id, text, keyboard=None):
    try:
        payload = {"chat": chat_id, "msg": text}
        if keyboard is not None:
            payload["keyboard"] = keyboard
        r = requests.post(f"{BASE_URL}/send", json=payload, timeout=10)
        if r.status_code != 200:
            log.error(f"/send {r.status_code} {r.text[:200]}")
        return r
    except Exception as e:
        log.exception(f"Ошибка отправки в {chat_id}: {e}")

def send_to_target(text, user_key, keyboard=None):
    try:
        payload = {"userKey": user_key, "msg": text}
        if keyboard is not None:
            payload["keyboard"] = keyboard
        r = requests.post(f"{BASE_URL}/send", json=payload, timeout=10)
        if r.status_code != 200:
            log.error(f"/send userKey={user_key} {r.status_code} {r.text[:200]}")
        return r
    except Exception as e:
        log.exception(f"Ошибка отправки userKey={user_key}: {e}")

# ==================== ХЕНДЛЕРЫ ====================
def handle_start(chat_id):
    user_sessions[chat_id] = {}
    send_message(chat_id, WELCOME_TEXT, main_menu_keyboard())

def handle_cancel(chat_id):
    if chat_id in user_sessions:
        user_sessions[chat_id].pop("scenario", None)
    send_message(chat_id, "❌ [b]Действие отменено.[/b]", main_menu_keyboard())

def handle_form_link(chat_id, text, sender_info):
    if "http" not in text:
        send_message(chat_id, SEND_FORM_INVALID, cancel_keyboard())
        return

    if not FORM_TARGET_KEYS:
        log.warning(f"FORM_TARGET_KEYS пуст, форма не отправлена. Link={text}")
        send_message(chat_id, SEND_FORM_NO_TARGET, main_menu_keyboard())
        user_sessions[chat_id].pop("scenario", None)
        return

    sender_name = format_sender(sender_info)
    user_id = sender_info.get("user_id")

    if user_id:
        sender_line = f"[user={user_id}]{sender_name}[/user]"
    else:
        sender_line = sender_name

    # Ссылка обёрнута в [url=...]...[/url] — так она кликабельна
    hr_msg = (
        "📤 [b]Новая форма на верификацию[/b]\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 [b]Ссылка:[/b] [url={text}]{text}[/url]\n\n"
        f"👤 [b]Отправитель:[/b] {sender_line}\n"
        f"🆔 [b]user.id:[/b] [code]{user_id or '—'}[/code]"
    )

    for key in FORM_TARGET_KEYS:
        send_to_target(hr_msg, key)

    send_message(chat_id, SEND_FORM_OK, main_menu_keyboard())
    user_sessions[chat_id].pop("scenario", None)

def handle_button(chat_id, button_data):
    if button_data == "menu_rules":
        send_message(chat_id, RULES_TEXT, back_keyboard())

    elif button_data == "menu_staffount":
        send_message(chat_id, STAFFOUNT_INTRO, staffount_keyboard())

    elif button_data == "staffount_salary":
        send_message(chat_id, SALARY_INSTRUCTION_TEXT, staffount_keyboard())

    elif button_data == "staffount_bonus":
        send_message(chat_id, BONUS_INSTRUCTION_TEXT, staffount_keyboard())

    elif button_data == "menu_templates":
        send_message(chat_id, TEMPLATES_TEXT, back_keyboard())

    elif button_data == "menu_deadlines":
        send_message(chat_id, DEADLINES_MENU_TEXT, deadlines_keyboard())

    elif button_data == "deadlines_salary":
        send_message(chat_id, SALARY_DEADLINES_TEXT, deadlines_keyboard())

    elif button_data == "deadlines_bonus":
        send_message(chat_id, BONUS_DEADLINES_TEXT, deadlines_keyboard())

    elif button_data == "menu_send_form":
        user_sessions.setdefault(chat_id, {})["scenario"] = "send_form"
        send_message(chat_id, SEND_FORM_PROMPT, cancel_keyboard())

    else:
        handle_start(chat_id)

def process_update(upd):
    upd_type = _get(upd, "type")
    chat_id = _get(upd, "chat", "id")
    if not chat_id:
        return

    if upd_type == "message":
        text = (_get(upd, "message", "msg") or "").strip()
        log.info(f"message chat={chat_id} text={text!r}")

        if text == "/cancel":
            handle_cancel(chat_id)
        elif user_sessions.get(chat_id, {}).get("scenario") == "send_form":
            handle_form_link(chat_id, text, get_sender_info(upd))
        else:
            handle_start(chat_id)

    elif upd_type == "buttonAction":
        button_data = _get(upd, "button", "data")
        log.info(f"button chat={chat_id} data={button_data!r}")
        if button_data:
            handle_button(chat_id, button_data)

    elif upd_type in ("inlineRequest", "inlineChoice"):
        pass
    elif upd_type == "messageEdited":
        pass

# ==================== ОСНОВНОЙ ЦИКЛ (LONG POLLING) ====================
def bot_loop():
    log.info("✅ Salary Bot G&S запущен (Long Polling)")
    seen = set()

    while True:
        try:
            r = requests.get(f"{BASE_URL}/getupdate", timeout=60)

            if r.status_code == 200:
                updates = r.json()
                if isinstance(updates, list):
                    for upd in updates:
                        if not isinstance(upd, dict):
                            continue

                        key = (
                            _get(upd, "type"),
                            _get(upd, "ts"),
                            _get(upd, "chat", "id"),
                            _get(upd, "message", "id"),
                            _get(upd, "button", "messageId"),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        if len(seen) > 5000:
                            seen.clear()

                        try:
                            process_update(upd)
                        except Exception:
                            log.exception(f"Ошибка обработки update: {upd}")

            elif r.status_code == 429:
                log.warning("429 rate limit, sleep 5s")
                time.sleep(5)
            elif r.status_code == 404:
                log.error(f"404 — бот не в чате или неверный BOT_TOKEN/DOMAIN: {r.text[:200]}")
                time.sleep(10)
            else:
                log.error(f"/getupdate {r.status_code} {r.text[:200]}")
                time.sleep(3)

        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            log.exception(f"Ошибка в цикле: {e}")
            time.sleep(3)

        time.sleep(1)

# ==================== HEALTHCHECK ====================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, fmt, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", HEALTH_PORT))
    log.info(f"Healthcheck listening on 0.0.0.0:{port}")
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

# ==================== ТОЧКА ВХОДА ====================
if __name__ == "__main__":
    Thread(target=run_health_server, daemon=True).start()
    bot_loop()