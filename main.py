import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# ========== НАСТРОЙКИ ==========
TOKEN = "8126450707:AAE1grJdi8DReGgCHJdE2MzEa7ocNVClvq8"  # Получите у @BotFather
ADMIN_ID = 7433757951  # Ваш Telegram ID (узнать у @userinfobot)
REFERRAL_BONUS = 350  # Бонус за приглашенного пользователя
MIN_WITHDRAWAL = 5000  # Минимальная сумма для вывода

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_file="referral_bot.db"):
        self.db_file = db_file
        self.create_tables()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn
    
    def create_tables(self):
        with self.get_connection() as conn:
            # Пользователи
            conn.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                balance REAL DEFAULT 0.0,
                referrals INTEGER DEFAULT 0,
                referral_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Транзакции
            conn.execute('''CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                type TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Выплаты
            conn.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                method TEXT,
                details TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            conn.commit()
    
    def add_user(self, user_id, username, first_name, last_name, referral_id=None):
        with self.get_connection() as conn:
            # Проверяем, существует ли пользователь
            cursor = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            if cursor.fetchone():
                return False
            
            # Добавляем пользователя
            conn.execute('''INSERT INTO users (user_id, username, first_name, last_name, referral_id) 
                          VALUES (?, ?, ?, ?, ?)''',
                       (user_id, username, first_name, last_name, referral_id))
            
            # Если есть реферер, начисляем бонус
            if referral_id:
                # Начисляем бонус рефереру
                conn.execute("UPDATE users SET balance = balance + ?, referrals = referrals + 1 WHERE user_id = ?",
                           (REFERRAL_BONUS, referral_id))
                
                # Добавляем запись о транзакции
                conn.execute('''INSERT INTO transactions (user_id, amount, type, description)
                              VALUES (?, ?, ?, ?)''',
                           (referral_id, REFERRAL_BONUS, 'referral', f'Бонус за приглашение пользователя {user_id}'))
            
            conn.commit()
            return True
    
    def get_user(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_balance(self, user_id):
        user = self.get_user(user_id)
        return user['balance'] if user else 0.0
    
    def get_referrals(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.execute('''SELECT user_id, username, first_name, created_at 
                                   FROM users WHERE referral_id = ? ORDER BY created_at DESC''',
                                (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_referral_stats(self, user_id):
        with self.get_connection() as conn:
            cursor = conn.execute('''SELECT COUNT(*) as count, SUM(balance) as earned 
                                   FROM users WHERE referral_id = ?''', (user_id,))
            return dict(cursor.fetchone())
    
    def create_withdrawal(self, user_id, amount, method, details):
        with self.get_connection() as conn:
            # Списываем средства
            conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
            
            # Создаем заявку на вывод
            cursor = conn.execute('''INSERT INTO withdrawals (user_id, amount, method, details)
                                   VALUES (?, ?, ?, ?)''',
                                (user_id, amount, method, details))
            
            # Добавляем транзакцию
            conn.execute('''INSERT INTO transactions (user_id, amount, type, description)
                          VALUES (?, ?, ?, ?)''',
                       (user_id, -amount, 'withdrawal', f'Запрос на вывод #{cursor.lastrowid}'))
            
            conn.commit()
            return cursor.lastrowid
    
    def get_withdrawals(self, user_id=None, status=None):
        with self.get_connection() as conn:
            query = "SELECT * FROM withdrawals"
            params = []
            
            if user_id:
                query += " WHERE user_id = ?"
                params.append(user_id)
                if status:
                    query += " AND status = ?"
                    params.append(status)
            elif status:
                query += " WHERE status = ?"
                params.append(status)
            
            query += " ORDER BY created_at DESC"
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def update_withdrawal_status(self, withdrawal_id, status):
        with self.get_connection() as conn:
            # Получаем информацию о выплате
            cursor = conn.execute("SELECT user_id, amount FROM withdrawals WHERE id = ?", (withdrawal_id,))
            withdrawal = cursor.fetchone()
            
            if not withdrawal:
                return False
            
            user_id, amount = withdrawal['user_id'], withdrawal['amount']
            
            # Обновляем статус
            conn.execute("UPDATE withdrawals SET status = ? WHERE id = ?", (status, withdrawal_id))
            
            # Если отклоняем, возвращаем средства
            if status == 'rejected':
                conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                conn.execute('''INSERT INTO transactions (user_id, amount, type, description)
                              VALUES (?, ?, ?, ?)''',
                           (user_id, amount, 'refund', f'Возврат средств по заявке #{withdrawal_id}'))
            
            conn.commit()
            return True
    
    def get_all_users(self):
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT user_id, username, first_name, balance, created_at FROM users ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]
    
    def get_stats(self):
        with self.get_connection() as conn:
            cursor = conn.execute('''SELECT 
                COUNT(*) as total_users,
                SUM(balance) as total_balance,
                SUM(referrals) as total_referrals,
                (SELECT COUNT(*) FROM withdrawals WHERE status = 'pending') as pending_withdrawals,
                (SELECT SUM(amount) FROM withdrawals WHERE status = 'paid') as total_paid
            FROM users''')
            return dict(cursor.fetchone())

# Инициализируем базу данных
db = Database()

# ========== КЛАВИАТУРЫ ==========
def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="👥 Мои рефералы")],
            [KeyboardButton(text="💸 Вывод средств"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="ℹ️ Помощь")]
        ],
        resize_keyboard=True
    )

def withdrawal_methods():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💳 Банковская карта", callback_data="withdraw_card"),
                InlineKeyboardButton(text="🥝 QIWI", callback_data="withdraw_qiwi")
            ],
            [
                InlineKeyboardButton(text="📱 ЮMoney", callback_data="withdraw_yoomoney"),
                InlineKeyboardButton(text="₿ Криптовалюта", callback_data="withdraw_crypto")
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_withdraw")]
        ]
    )

def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Общая статистика")],
            [KeyboardButton(text="👥 Все пользователи"), KeyboardButton(text="⏳ Заявки на вывод")],
            [KeyboardButton(text="📢 Рассылка")],
            [KeyboardButton(text="⬅️ В главное меню")]
        ],
        resize_keyboard=True
    )

# ========== СОСТОЯНИЯ ==========
class WithdrawalStates(StatesGroup):
    choosing_amount = State()
    entering_details = State()

class BroadcastState(StatesGroup):
    waiting_for_message = State()

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    args = message.text.split()
    
    # Извлекаем реферальный ID из аргументов команды
    referral_id = None
    if len(args) > 1:
        try:
            referral_id = int(args[1])
            # Проверяем, что реферер существует и это не сам пользователь
            if referral_id == user.id or not db.get_user(referral_id):
                referral_id = None
        except ValueError:
            referral_id = None
    
    # Добавляем пользователя
    is_new = db.add_user(user.id, user.username, user.first_name, user.last_name, referral_id)
    
    # Формируем ответ
    welcome_text = ""
    if is_new:
        welcome_text = "🎉 Добро пожаловать! Вы успешно зарегистрированы.\n"
        if referral_id:
            welcome_text += f"Вы были приглашены пользователем с ID: {referral_id}\n"
    else:
        welcome_text = "👋 С возвращением!\n"
    
    # Реферальная ссылка
    ref_link = f"https://t.me/{message.bot.username}?start={user.id}"
    
    welcome_text += f"""
📌 Ваша реферальная ссылка:
<code>{ref_link}</code>

💰 За каждого приглашенного друга вы получаете <b>{REFERRAL_BONUS}₽</b>
💸 Минимальная сумма для вывода: <b>{MIN_WITHDRAWAL}₽</b>

👥 Приглашайте друзей и зарабатывайте!
    """
    
    await message.answer(welcome_text, reply_markup=main_menu(), parse_mode='HTML')

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У вас нет прав администратора.")
        return
    
    await message.answer("👑 Панель администратора", reply_markup=admin_menu())

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """
🤖 <b>Справка по боту</b>

💰 <b>Заработок:</b>
• Приглашайте друзей по своей реферальной ссылке
• За каждого приглашенного: <b>{REFERRAL_BONUS}₽</b>

💸 <b>Вывод средств:</b>
• Минимальная сумма: <b>{MIN_WITHDRAWAL}₽</b>
• Доступные методы: карта, QIWI, ЮMoney, крипто
• Вывод в течение 24 часов после одобрения

👥 <b>Реферальная система:</b>
• Ваша ссылка есть в меню "Мои рефералы"
• Вы получаете бонус сразу после регистрации друга

📊 <b>Команды:</b>
/start - Начать работу
/help - Эта справка
/admin - Панель администратора (только для админа)
    """.format(REFERRAL_BONUS=REFERRAL_BONUS, MIN_WITHDRAWAL=MIN_WITHDRAWAL)
    
    await message.answer(help_text, parse_mode='HTML')

# ========== ОБРАБОТЧИКИ КНОПОК ==========
@dp.message(F.text == "💰 Баланс")
async def show_balance(message: types.Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Пожалуйста, сначала нажмите /start")
        return
    
    balance = user['balance']
    referrals = user['referrals']
    
    text = f"""
💰 <b>Ваш баланс:</b> {balance:.2f}₽
👥 <b>Приглашено друзей:</b> {referrals}
🎁 <b>Заработано на рефералах:</b> {referrals * REFERRAL_BONUS}₽

💸 <b>Минимальный вывод:</b> {MIN_WITHDRAWAL}₽
💎 <b>Доступно для вывода:</b> {balance if balance >= MIN_WITHDRAWAL else "Недостаточно средств"}
    """
    
    await message.answer(text, parse_mode='HTML')

@dp.message(F.text == "👥 Мои рефералы")
async def show_referrals(message: types.Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Пожалуйста, сначала нажмите /start")
        return
    
    referrals = db.get_referrals(message.from_user.id)
    stats = db.get_referral_stats(message.from_user.id)
    
    # Реферальная ссылка
    ref_link = f"https://t.me/{message.bot.username}?start={message.from_user.id}"
    
    text = f"👥 <b>Ваши рефералы</b>\n\n"
    
    if referrals:
        text += f"Всего приглашено: {stats['count'] or 0} человек\n"
        text += "Список:\n"
        for i, ref in enumerate(referrals[:20], 1):  # Показываем первые 20
            username = f"@{ref['username']}" if ref['username'] else f"ID: {ref['user_id']}"
            date = ref['created_at'][:10] if ref['created_at'] else "N/A"
            text += f"{i}. {username} ({ref['first_name']}) - {date}\n"
        
        if len(referrals) > 20:
            text += f"\n... и еще {len(referrals) - 20} рефералов"
    else:
        text += "У вас пока нет приглашенных друзей.\n"
    
    text += f"\n🔗 <b>Ваша реферальная ссылка:</b>\n<code>{ref_link}</code>"
    text += f"\n\n💰 <b>За каждого приглашенного:</b> {REFERRAL_BONUS}₽"
    
    await message.answer(text, parse_mode='HTML')

@dp.message(F.text == "💸 Вывод средств")
async def start_withdrawal(message: types.Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Пожалуйста, сначала нажмите /start")
        return
    
    balance = user['balance']
    
    if balance < MIN_WITHDRAWAL:
        await message.answer(
            f"❌ Недостаточно средств для вывода.\n"
            f"Минимальная сумма: {MIN_WITHDRAWAL}₽\n"
            f"Ваш баланс: {balance:.2f}₽\n\n"
            f"Пригласите друзей, чтобы заработать больше!"
        )
        return
    
    await message.answer(
        f"💰 <b>Доступно для вывода:</b> {balance:.2f}₽\n"
        f"💸 <b>Минимальная сумма:</b> {MIN_WITHDRAWAL}₽\n\n"
        f"Выберите способ вывода средств:",
        reply_markup=withdrawal_methods(),
        parse_mode='HTML'
    )

@dp.callback_query(F.data.startswith("withdraw_"))
async def choose_withdrawal_method(callback: types.CallbackQuery, state: FSMContext):
    method = callback.data.replace("withdraw_", "")
    method_names = {
        'card': '💳 Банковская карта',
        'qiwi': '🥝 QIWI',
        'yoomoney': '📱 ЮMoney',
        'crypto': '₿ Криптовалюта (USDT TRC20)'
    }
    
    await state.update_data(method=method, method_name=method_names[method])
    
    await callback.message.edit_text(
        f"Выбран способ: <b>{method_names[method]}</b>\n\n"
        f"Введите сумму для вывода (от {MIN_WITHDRAWAL}₽ до {db.get_balance(callback.from_user.id):.2f}₽):",
        parse_mode='HTML'
    )
    
    await state.set_state(WithdrawalStates.choosing_amount)

@dp.message(WithdrawalStates.choosing_amount)
async def enter_withdrawal_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        user_balance = db.get_balance(message.from_user.id)
        
        if amount < MIN_WITHDRAWAL:
            await message.answer(
                f"❌ Минимальная сумма вывода: {MIN_WITHDRAWAL}₽\n"
                f"Пожалуйста, введите сумму еще раз:"
            )
            return
        
        if amount > user_balance:
            await message.answer(
                f"❌ Недостаточно средств.\n"
                f"Ваш баланс: {user_balance:.2f}₽\n"
                f"Введите сумму еще раз:"
            )
            return
        
        await state.update_data(amount=amount)
        data = await state.get_data()
        
        # Запрашиваем реквизиты в зависимости от метода
        if data['method'] == 'card':
            prompt = "💳 Введите номер банковской карты (формат: 0000 0000 0000 0000):"
        elif data['method'] == 'qiwi':
            prompt = "🥝 Введите номер QIWI кошелька:"
        elif data['method'] == 'yoomoney':
            prompt = "📱 Введите номер ЮMoney кошелька:"
        else:  # crypto
            prompt = "₿ Введите адрес крипто-кошелька (USDT TRC20):"
        
        await message.answer(prompt)
        await state.set_state(WithdrawalStates.entering_details)
        
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректную сумму (например: 150.50):")

@dp.message(WithdrawalStates.entering_details)
async def enter_withdrawal_details(message: types.Message, state: FSMContext):
    details = message.text.strip()
    data = await state.get_data()
    user_id = message.from_user.id
    
    # Создаем заявку на вывод
    withdrawal_id = db.create_withdrawal(user_id, data['amount'], data['method'], details)
    
    # Уведомляем пользователя
    await message.answer(
        f"✅ <b>Заявка на вывод #{withdrawal_id} создана!</b>\n\n"
        f"💰 Сумма: {data['amount']:.2f}₽\n"
        f"💳 Способ: {data['method_name']}\n"
        f"📝 Реквизиты: {details}\n\n"
        f"⏳ Заявка будет обработана в течение 24 часов.\n"
        f"Статус можно отслеживать в разделе 'Статистика'.",
        reply_markup=main_menu(),
        parse_mode='HTML'
    )
    
    # Уведомляем администратора
    user = db.get_user(user_id)
    username = f"@{user['username']}" if user['username'] else f"ID: {user_id}"
    
    admin_text = (
        f"🆕 <b>НОВАЯ ЗАЯВКА НА ВЫВОД #{withdrawal_id}</b>\n\n"
        f"👤 <b>Пользователь:</b> {username} ({user['first_name']})\n"
        f"💰 <b>Сумма:</b> {data['amount']:.2f}₽\n"
        f"💳 <b>Способ:</b> {data['method_name']}\n"
        f"📝 <b>Реквизиты:</b> {details}\n"
        f"🆔 <b>ID пользователя:</b> {user_id}\n\n"
        f"✅ Одобрить: /approve_{withdrawal_id}\n"
        f"❌ Отклонить: /reject_{withdrawal_id}"
    )
    
    try:
        await bot.send_message(ADMIN_ID, admin_text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление админу: {e}")
    
    await state.clear()

@dp.callback_query(F.data == "cancel_withdraw")
async def cancel_withdrawal(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Вывод средств отменен.")
    await callback.message.answer("Главное меню:", reply_markup=main_menu())

@dp.message(F.text == "📊 Статистика")
async def show_statistics(message: types.Message):
    user = db.get_user(message.from_user.id)
    if not user:
        await message.answer("Пожалуйста, сначала нажмите /start")
        return
    
    referrals = db.get_referrals(message.from_user.id)
    
    # Получаем историю выводов пользователя
    withdrawals = db.get_withdrawals(user_id=message.from_user.id)
    
    text = f"""
📊 <b>Ваша статистика</b>

👤 <b>Личные данные:</b>
├ ID: {user['user_id']}
├ Имя: {user['first_name']}
├ Баланс: {user['balance']:.2f}₽
└ Рефералов: {user['referrals']}

💰 <b>Заработок:</b>
├ На рефералах: {user['referrals'] * REFERRAL_BONUS}₽
└ Доступно для вывода: {'Да' if user['balance'] >= MIN_WITHDRAWAL else 'Нет'}

📋 <b>Заявки на вывод:</b>
"""
    
    if withdrawals:
        for w in withdrawals[:5]:  # Показываем последние 5 заявок
            status_icons = {'pending': '⏳', 'paid': '✅', 'rejected': '❌'}
            text += f"{status_icons.get(w['status'], '❓')} #{w['id']}: {w['amount']:.2f}₽ - {w['status']}\n"
        
        if len(withdrawals) > 5:
            text += f"... и еще {len(withdrawals) - 5} заявок\n"
    else:
        text += "Нет заявок на вывод\n"
    
    await message.answer(text, parse_mode='HTML')

@dp.message(F.text == "ℹ️ Помощь")
async def show_help(message: types.Message):
    await cmd_help(message)

# ========== АДМИН ФУНКЦИИ ==========
@dp.message(F.text == "📊 Общая статистика")
async def admin_overall_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    stats = db.get_stats()
    
    text = f"""
👑 <b>ОБЩАЯ СТАТИСТИКА БОТА</b>

👥 <b>Пользователи:</b>
├ Всего: {stats['total_users'] or 0}
├ Общий баланс: {stats['total_balance'] or 0:.2f}₽
└ Всего рефералов: {stats['total_referrals'] or 0}

💸 <b>Выплаты:</b>
├ Ожидает: {stats['pending_withdrawals'] or 0} заявок
└ Выплачено: {stats['total_paid'] or 0:.2f}₽

⚙️ <b>Настройки:</b>
├ Реферальный бонус: {REFERRAL_BONUS}₽
└ Мин. вывод: {MIN_WITHDRAWAL}₽
    """
    
    await message.answer(text, parse_mode='HTML')

@dp.message(F.text == "👥 Все пользователи")
async def admin_all_users(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    users = db.get_all_users()
    
    if not users:
        await message.answer("📭 В базе нет пользователей")
        return
    
    text = f"👥 <b>Все пользователи ({len(users)}):</b>\n\n"
    
    for i, user in enumerate(users[:50], 1):  # Показываем первые 50
        username = f"@{user['username']}" if user['username'] else f"ID: {user['user_id']}"
        date = user['created_at'][:10] if user['created_at'] else "N/A"
        text += f"{i}. {username} - {user['balance']:.2f}₽ - {date}\n"
    
    if len(users) > 50:
        text += f"\n... и еще {len(users) - 50} пользователей"
    
    await message.answer(text, parse_mode='HTML')

@dp.message(F.text == "⏳ Заявки на вывод")
async def admin_pending_withdrawals(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    withdrawals = db.get_withdrawals(status='pending')
    
    if not withdrawals:
        await message.answer("✅ Нет pending заявок на вывод.")
        return
    
    text = "⏳ <b>Заявки на вывод (ожидают обработки):</b>\n\n"
    
    for w in withdrawals:
        user = db.get_user(w['user_id'])
        username = f"@{user['username']}" if user and user['username'] else f"ID: {w['user_id']}"
        
        method_names = {
            'card': '💳 Карта',
            'qiwi': '🥝 QIWI',
            'yoomoney': '📱 ЮMoney',
            'crypto': '₿ Крипто'
        }
        
        text += (
            f"🆔 <b>#{w['id']}</b>\n"
            f"👤 {username}\n"
            f"💰 {w['amount']:.2f}₽\n"
            f"💳 {method_names.get(w['method'], w['method'])}\n"
            f"📝 {w['details']}\n"
            f"📅 {w['created_at'][:19] if w['created_at'] else 'N/A'}\n"
            f"✅ /approve_{w['id']}  ❌ /reject_{w['id']}\n\n"
        )
    
    await message.answer(text, parse_mode='HTML')

@dp.message(F.text.startswith("/approve_"))
async def admin_approve_withdrawal(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        withdrawal_id = int(message.text.replace("/approve_", ""))
        
        if db.update_withdrawal_status(withdrawal_id, 'paid'):
            # Получаем информацию о выплате
            withdrawals = db.get_withdrawals()
            withdrawal = next((w for w in withdrawals if w['id'] == withdrawal_id), None)
            
            if withdrawal:
                # Уведомляем пользователя
                await bot.send_message(
                    withdrawal['user_id'],
                    f"✅ Ваша заявка на вывод #{withdrawal_id} на сумму {withdrawal['amount']:.2f}₽ одобрена!\n"
                    f"Средства будут зачислены в течение 24 часов."
                )
            
            await message.answer(f"✅ Заявка #{withdrawal_id} одобрена.")
        else:
            await message.answer(f"❌ Заявка #{withdrawal_id} не найдена.")
            
    except ValueError:
        await message.answer("❌ Неверный формат команды. Используйте: /approve_123")

@dp.message(F.text.startswith("/reject_"))
async def admin_reject_withdrawal(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        withdrawal_id = int(message.text.replace("/reject_", ""))
        
        if db.update_withdrawal_status(withdrawal_id, 'rejected'):
            # Получаем информацию о выплате
            withdrawals = db.get_withdrawals()
            withdrawal = next((w for w in withdrawals if w['id'] == withdrawal_id), None)
            
            if withdrawal:
                # Уведомляем пользователя
                await bot.send_message(
                    withdrawal['user_id'],
                    f"❌ Ваша заявка на вывод #{withdrawal_id} на сумму {withdrawal['amount']:.2f}₽ отклонена.\n"
                    f"Средства возвращены на баланс."
                )
            
            await message.answer(f"❌ Заявка #{withdrawal_id} отклонена.")
        else:
            await message.answer(f"❌ Заявка #{withdrawal_id} не найдена.")
            
    except ValueError:
        await message.answer("❌ Неверный формат команды. Используйте: /reject_123")

@dp.message(F.text == "📢 Рассылка")
async def admin_start_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    await message.answer(
        "📢 <b>Отправьте сообщение для рассылки</b>\n\n"
        "Вы можете использовать HTML-разметку.\n"
        "Для отмены отправьте /cancel",
        parse_mode='HTML'
    )
    await state.set_state(BroadcastState.waiting_for_message)

@dp.message(BroadcastState.waiting_for_message, Command("cancel"))
async def admin_cancel_broadcast(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Рассылка отменена.", reply_markup=admin_menu())

@dp.message(BroadcastState.waiting_for_message)
async def admin_send_broadcast(message: types.Message, state: FSMContext):
    users = db.get_all_users()
    total = len(users)
    success = 0
    failed = 0
    
    await message.answer(f"📤 Начинаю рассылку для {total} пользователей...")
    
    for user in users:
        try:
            await bot.send_message(user['user_id'], message.text, parse_mode='HTML')
            success += 1
            await asyncio.sleep(0.05)  # Задержка, чтобы не превысить лимиты Telegram
        except Exception as e:
            failed += 1
            logger.error(f"Не удалось отправить сообщение пользователю {user['user_id']}: {e}")
    
    await message.answer(
        f"✅ Рассылка завершена!\n\n"
        f"📊 Статистика:\n"
        f"• Всего пользователей: {total}\n"
        f"• Успешно отправлено: {success}\n"
        f"• Не удалось отправить: {failed}",
        reply_markup=admin_menu()
    )
    await state.clear()

@dp.message(F.text == "⬅️ В главное меню")
async def admin_back_to_main(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu())

# ========== ЗАПУСК БОТА ==========
async def main():
    logger.info("=" * 50)
    logger.info("🤖 ЗАПУСК РЕФЕРАЛЬНОГО БОТА")
    logger.info(f"👑 Админ ID: {ADMIN_ID}")
    logger.info(f"💰 Реферальный бонус: {REFERRAL_BONUS}₽")
    logger.info(f"💸 Минимальный вывод: {MIN_WITHDRAWAL}₽")
    logger.info("=" * 50)
    
    # Проверяем токен бота
    if TOKEN == "ВАШ_ТОКЕН_БОТА":
        logger.error("❌ ОШИБКА: Токен бота не установлен!")
        logger.info("Получите токен у @BotFather и вставьте его в переменную TOKEN")
        return
    
    # Проверяем ID администратора
    if ADMIN_ID == 123456789:
        logger.warning("⚠️ ВНИМАНИЕ: ID администратора не установлен!")
        logger.info("Узнайте свой ID у @userinfobot и вставьте его в переменную ADMIN_ID")
    
    try:
        # Запускаем бота
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")

if __name__ == "__main__":
    asyncio.run(main())
