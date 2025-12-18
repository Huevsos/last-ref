import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import sqlite3
import hashlib

# Настройки
TOKEN = "8126450707:AAE1grJdi8DReGgCHJdE2MzEa7ocNVClvq8"
ADMIN_ID = 7433757951  # Ваш ID в Telegram

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# База данных
def init_db():
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        referrer_id INTEGER,
        join_date TIMESTAMP,
        referrals_count INTEGER DEFAULT 0
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS referrals_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER,
        referred_id INTEGER,
        click_time TIMESTAMP,
        converted BOOLEAN DEFAULT FALSE
    )
    ''')
    
    conn.commit()
    conn.close()

def generate_referral_link(user_id):
    """Генерация уникальной реферальной ссылки"""
    secret = "YOUR_SECRET_KEY"  # Измените на свой секретный ключ
    data = f"{user_id}{secret}"
    return hashlib.md5(data.encode()).hexdigest()[:8]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = user.id
    
    # Проверяем реферальный параметр
    args = context.args
    referrer_id = None
    
    if args and len(args) > 0:
        try:
            # Парсим реферальный код
            referrer_code = args[0]
            # Здесь должна быть логика декодирования referrer_id из кода
            # Для примера используем простой вариант
            referrer_id = int(referrer_code) if referrer_code.isdigit() else None
        except:
            referrer_id = None
    
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    
    # Проверяем, есть ли пользователь в базе
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user_exists = cursor.fetchone()
    
    if not user_exists:
        # Регистрируем нового пользователя
        cursor.execute('''
        INSERT INTO users (user_id, username, referrer_id, join_date) 
        VALUES (?, ?, ?, ?)
        ''', (user_id, user.username, referrer_id, datetime.now()))
        
        # Логируем реферальный переход
        if referrer_id:
            cursor.execute('''
            INSERT INTO referrals_log (referrer_id, referred_id, click_time, converted)
            VALUES (?, ?, ?, ?)
            ''', (referrer_id, user_id, datetime.now(), True))
            
            # Увеличиваем счетчик рефералов у пригласившего
            cursor.execute('''
            UPDATE users SET referrals_count = referrals_count + 1 
            WHERE user_id = ?
            ''', (referrer_id,))
            
            # Уведомляем реферера о новом реферале
            try:
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"🎉 По вашей ссылке зарегистрировался новый пользователь: @{user.username}"
                )
            except:
                pass
        
        conn.commit()
        
        await update.message.reply_text(
            f"👋 Привет, {user.first_name}!\n\n"
            f"Добро пожаловать! Вы были зарегистрированы в системе."
        )
    else:
        await update.message.reply_text(
            f"С возвращением, {user.first_name}!"
        )
    
    # Показываем реферальную ссылку
    referral_code = generate_referral_link(user_id)
    bot_username = context.bot.username
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    keyboard = [
        [InlineKeyboardButton("📊 Мои рефералы", callback_data='my_refs')],
        [InlineKeyboardButton("📢 Поделиться ссылкой", url=f"https://t.me/share/url?url={referral_link}")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🔗 Ваша реферальная ссылка:\n`{referral_link}`\n\n"
        f"Приглашайте друзей и получайте уведомления!",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    conn.close()

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика рефералов"""
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT referrals_count FROM users WHERE user_id = ?
    ''', (user_id,))
    
    result = cursor.fetchone()
    referrals_count = result[0] if result else 0
    
    cursor.execute('''
    SELECT username, join_date FROM referrals_log 
    JOIN users ON referrals_log.referred_id = users.user_id
    WHERE referrer_id = ? AND converted = TRUE
    ORDER BY click_time DESC
    LIMIT 10
    ''', (user_id,))
    
    recent_refs = cursor.fetchall()
    conn.close()
    
    text = f"📊 Ваша статистика:\n\n"
    text += f"👥 Всего рефералов: {referrals_count}\n\n"
    
    if recent_refs:
        text += "Последние рефералы:\n"
        for ref in recent_refs:
            username = ref[0] or "без username"
            date = ref[1][:10] if ref[1] else "неизвестно"
            text += f"• @{username} - {date}\n"
    else:
        text += "У вас пока нет рефералов\n"
    
    await update.message.reply_text(text)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика для админа"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM users WHERE referrer_id IS NOT NULL')
    ref_users = cursor.fetchone()[0]
    
    cursor.execute('''
    SELECT users.username, users.referrals_count 
    FROM users 
    ORDER BY referrals_count DESC 
    LIMIT 10
    ''')
    top_refs = cursor.fetchall()
    
    conn.close()
    
    text = f"📈 Общая статистика:\n\n"
    text += f"👥 Всего пользователей: {total_users}\n"
    text += f"📨 Реферальных регистраций: {ref_users}\n\n"
    text += "Топ-10 по рефералам:\n"
    
    for i, (username, count) in enumerate(top_refs, 1):
        username_display = username or f"user_{i}"
        text += f"{i}. @{username_display} - {count} рефералов\n"
    
    await update.message.reply_text(text)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'my_refs':
        await stats(update, context)

async def link_click_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Логирование кликов по ссылке (обработка глубоких ссылок)"""
    # Эта функция будет вызвана при любом переходе по ссылке
    user = update.effective_user
    
    # Логируем в консоль
    logging.info(f"Пользователь {user.id} (@{user.username}) перешел по ссылке")
    
    # Можно также сохранить в базу данных
    conn = sqlite3.connect('referrals.db')
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO referrals_log (referrer_id, referred_id, click_time, converted)
    VALUES (?, ?, ?, ?)
    ''', (None, user.id, datetime.now(), False))
    conn.commit()
    conn.close()

def main():
    """Запуск бота"""
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("admin", admin_stats))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Логирование всех сообщений для отслеживания кликов
    application.add_handler(CommandHandler("help", link_click_log))
    
    # Запуск бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
