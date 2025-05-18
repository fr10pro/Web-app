import os
import logging
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils.exceptions import BadRequest
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Load environment variables
load_dotenv()

# Configuration
class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]
    CHANNEL_ID = os.getenv("CHANNEL_ID", "")
    REFERRAL_REWARD = float(os.getenv("REFERRAL_REWARD", 0.20))
    MIN_WITHDRAWAL = float(os.getenv("MIN_WITHDRAWAL", 1.00))
    PAYMENT_DETAILS = os.getenv("PAYMENT_DETAILS", "PayPal: example@example.com")
    
    # Task rewards
    JOIN_CHANNEL_REWARD = 0.10
    VIEW_POST_15_REWARD = 0.05
    VIEW_POST_30_REWARD = 0.10
    VIEW_POST_60_REWARD = 0.15
    VIEW_POST_120_REWARD = 0.20

config = Config()

# Database setup
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    join_date = Column(DateTime, default=datetime.utcnow)
    balance = Column(Float, default=0.0)
    referral_code = Column(String, unique=True)
    referred_by = Column(Integer, default=None)
    
    referrals = relationship("Referral", back_populates="referrer")
    transactions = relationship("Transaction", back_populates="user")
    tasks = relationship("UserTask", back_populates="user")

class Referral(Base):
    __tablename__ = 'referrals'
    
    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, ForeignKey('users.id'))
    referred_id = Column(Integer, unique=True)
    date = Column(DateTime, default=datetime.utcnow)
    reward_paid = Column(Boolean, default=False)
    
    referrer = relationship("User", back_populates="referrals")

class Transaction(Base):
    __tablename__ = 'transactions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    amount = Column(Float)
    date = Column(DateTime, default=datetime.utcnow)
    type = Column(String)  # 'task', 'referral', 'withdrawal'
    status = Column(String, default='pending')  # 'pending', 'completed', 'rejected'
    details = Column(String)
    
    user = relationship("User", back_populates="transactions")

class UserTask(Base):
    __tablename__ = 'user_tasks'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    task_type = Column(String)  # 'join_channel', 'view_post'
    task_id = Column(Integer)
    completed_at = Column(DateTime, default=datetime.utcnow)
    reward = Column(Float)
    
    user = relationship("User", back_populates="tasks")

class Task(Base):
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True)
    task_type = Column(String)
    target_id = Column(String)  # channel ID or post URL
    reward = Column(Float)
    max_completions = Column(Integer)
    current_completions = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    active = Column(Boolean, default=True)

# Initialize database
def init_db():
    db_path = os.path.join(os.path.dirname(__file__), 'data.db')
    engine = create_engine(f'sqlite:///{db_path}')
    Base.metadata.create_all(engine)
    return engine

def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()

# State machines
class WithdrawalRequest(StatesGroup):
    amount = State()

class BotSettings(StatesGroup):
    payment_details = State()
    min_withdrawal = State()
    referral_reward = State()

class SearchUser(StatesGroup):
    user_id = State()

class EditBalance(StatesGroup):
    amount = State()

class AddTask(StatesGroup):
    task_type = State()
    target = State()
    reward = State()
    max_completions = State()

# Helper functions
def format_user_profile(session, user):
    referral_count = session.query(Referral).filter_by(referrer_id=user.id).count()
    tasks_completed = session.query(UserTask).filter_by(user_id=user.id).count()
    
    return {
        "name": f"{user.first_name} {user.last_name or ''}".strip(),
        "username": user.username,
        "user_id": user.user_id,
        "join_date": user.join_date.strftime("%Y-%m-%d %H:%M"),
        "referral_count": referral_count,
        "balance": user.balance,
        "tasks_completed": tasks_completed
    }

def format_transaction(transaction):
    return {
        "id": transaction.id,
        "amount": transaction.amount,
        "date": transaction.date.strftime("%Y-%m-%d %H:%M"),
        "type": transaction.type,
        "status": transaction.status,
        "details": transaction.details
    }

def create_or_get_user(session, tg_user):
    user = session.query(User).filter_by(user_id=tg_user.id).first()
    if not user:
        user = User(
            user_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            referral_code=f"ref_{tg_user.id}_{datetime.now().strftime('%Y%m%d')}"
        )
        session.add(user)
        session.commit()
    return user

async def check_channel_membership(bot, user_id, channel_id):
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception:
        return False

# Keyboard functions
def main_menu():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("💰 Balance", callback_data="balance"),
        types.InlineKeyboardButton("👥 Referral", callback_data="referral"),
        types.InlineKeyboardButton("📋 Tasks", callback_data="tasks"),
        types.InlineKeyboardButton("👤 Profile", callback_data="profile"),
        types.InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")
    )
    return keyboard

def back_to_main():
    return types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Back", callback_data="main_menu"))

def tasks_menu():
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        types.InlineKeyboardButton("📢 Join Channel", callback_data="task_join_channel"),
        types.InlineKeyboardButton("👀 View Post (15s)", callback_data="task_view_post_15"),
        types.InlineKeyboardButton("👀 View Post (30s)", callback_data="task_view_post_30"),
        types.InlineKeyboardButton("👀 View Post (60s)", callback_data="task_view_post_60"),
        types.InlineKeyboardButton("👀 View Post (120s)", callback_data="task_view_post_120"),
        types.InlineKeyboardButton("🔙 Back", callback_data="main_menu")
    )
    return keyboard

def confirm_join_channel(channel_id):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ I've Joined", callback_data=f"confirm_join_{channel_id}"),
        types.InlineKeyboardButton("🔙 Back", callback_data="tasks")
    )
    return keyboard

def view_post_timer(duration, task_id):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(f"⏳ {duration}s remaining", callback_data=f"timer_{duration}_{task_id}")
    )
    return keyboard

def referral_menu(user_id):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("📤 Share Link", switch_inline_query=f"Join using my referral link to earn ${config.REFERRAL_REWARD}!"),
        types.InlineKeyboardButton("🔙 Back", callback_data="main_menu")
    )
    return keyboard

def withdraw_menu(balance, min_withdrawal):
    keyboard = types.InlineKeyboardMarkup()
    if balance >= min_withdrawal:
        keyboard.add(types.InlineKeyboardButton("💳 Request Withdrawal", callback_data="request_withdrawal"))
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
    return keyboard

def admin_menu():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
        types.InlineKeyboardButton("👥 User Management", callback_data="admin_users"),
        types.InlineKeyboardButton("💵 Transactions", callback_data="admin_transactions"),
        types.InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings"),
        types.InlineKeyboardButton("📝 Add Task", callback_data="admin_add_task"),
        types.InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
    )
    return keyboard

def admin_settings_menu():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("✏️ Change Payment", callback_data="admin_change_payment"),
        types.InlineKeyboardButton("🔢 Min Withdrawal", callback_data="admin_min_withdrawal"),
        types.InlineKeyboardButton("💰 Referral Reward", callback_data="admin_referral_reward"),
        types.InlineKeyboardButton("🔙 Back", callback_data="admin_panel")
    )
    return keyboard

# Handlers
async def start_command(message: types.Message):
    session = message.bot.get('session')
    user = create_or_get_user(session, message.from_user)
    
    # Check if user was referred
    if len(message.text.split()) > 1:
        referral_code = message.text.split()[1]
        referrer = session.query(User).filter_by(referral_code=referral_code).first()
        if referrer and referrer.id != user.id:
            existing = session.query(Referral).filter_by(referred_id=user.id).first()
            if not existing:
                referral = Referral(referrer_id=referrer.id, referred_id=user.id)
                session.add(referral)
                
                transaction = Transaction(
                    user_id=referrer.id,
                    amount=config.REFERRAL_REWARD,
                    type='referral',
                    details=f"Referral from user {user.user_id}"
                )
                session.add(transaction)
                referrer.balance += config.REFERRAL_REWARD
                session.commit()
    
    await message.answer(
        "🎉 Welcome to the Refer & Earn Bot!\n\n"
        "💰 Earn money by completing simple tasks and referring friends!\n\n"
        "📋 Use the menu below to get started:",
        reply_markup=main_menu()
    )

async def main_menu_callback(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🎉 Welcome to the Refer & Earn Bot!\n\n"
        "💰 Earn money by completing simple tasks and referring friends!\n\n"
        "📋 Use the menu below to get started:",
        reply_markup=main_menu()
    )
    await callback.answer()

async def balance_callback(callback: types.CallbackQuery):
    session = callback.bot.get('session')
    user = create_or_get_user(session, callback.from_user)
    
    await callback.message.edit_text(
        f"💰 Your current balance: ${user.balance:.4f}\n\n"
        f"💵 Minimum withdrawal: ${config.MIN_WITHDRAWAL:.4f}",
        reply_markup=back_to_main()
    )
    await callback.answer()

async def profile_callback(callback: types.CallbackQuery):
    session = callback.bot.get('session')
    user = create_or_get_user(session, callback.from_user)
    profile = format_user_profile(session, user)
    
    text = (
        f"👤 <b>Profile Information</b>\n\n"
        f"🆔 ID: <code>{profile['user_id']}</code>\n"
        f"👀 Name: {profile['name']}\n"
        f"📛 Username: @{profile['username'] or 'N/A'}\n"
        f"📅 Joined: {profile['join_date']}\n\n"
        f"👥 Referrals: {profile['referral_count']}\n"
        f"✅ Tasks Completed: {profile['tasks_completed']}\n"
        f"💰 Balance: ${profile['balance']:.4f}\n\n"
        f"🔗 Your referral link:\n"
        f"https://t.me/{callback.bot.username}?start={user.referral_code}"
    )
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("📋 Transactions", callback_data="transactions"))
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

async def transactions_callback(callback: types.CallbackQuery):
    session = callback.bot.get('session')
    user = create_or_get_user(session, callback.from_user)
    transactions = session.query(Transaction).filter_by(user_id=user.id).order_by(Transaction.date.desc()).limit(10).all()
    
    if not transactions:
        text = "📋 You don't have any transactions yet."
    else:
        text = "📋 <b>Your Recent Transactions</b>\n\n"
        for tx in transactions:
            status_emoji = "✅" if tx.status == 'completed' else "🔄" if tx.status == 'pending' else "❌"
            text += (
                f"{status_emoji} <b>{tx.type.capitalize()}</b>\n"
                f"Amount: ${tx.amount:.4f}\n"
                f"Date: {tx.date.strftime('%Y-%m-%d %H:%M')}\n"
                f"Status: {tx.status}\n\n"
            )
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="profile"))
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

async def referral_callback(callback: types.CallbackQuery):
    session = callback.bot.get('session')
    user = create_or_get_user(session, callback.from_user)
    
    text = (
        f"👥 <b>Referral Program</b>\n\n"
        f"🔗 Share your referral link and earn ${config.REFERRAL_REWARD:.2f} for each friend who joins!\n\n"
        f"📤 Your referral link:\n"
        f"https://t.me/{callback.bot.username}?start={user.referral_code}\n\n"
        f"👤 Total referrals: {session.query(Referral).filter_by(referrer_id=user.id).count()}\n"
        f"💰 Earned from referrals: ${session.query(Transaction).filter_by(user_id=user.id, type='referral', status='completed').with_entities(func.sum(Transaction.amount)).scalar() or 0:.2f}"
    )
    
    await callback.message.edit_text(text, reply_markup=referral_menu(user.user_id))
    await callback.answer()

async def tasks_callback(callback: types.CallbackQuery):
    text = (
        "📋 <b>Available Tasks</b>\n\n"
        "💰 Earn money by completing these simple tasks:\n\n"
        "1. 📢 Join Telegram channels\n"
        "2. 👀 View posts for a specified duration\n\n"
        "Select a task below to get started:"
    )
    
    await callback.message.edit_text(text, reply_markup=tasks_menu())
    await callback.answer()

async def withdraw_callback(callback: types.CallbackQuery):
    session = callback.bot.get('session')
    user = create_or_get_user(session, callback.from_user)
    
    text = (
        f"💸 <b>Withdrawal Request</b>\n\n"
        f"💰 Your balance: ${user.balance:.4f}\n"
        f"📉 Minimum withdrawal: ${config.MIN_WITHDRAWAL:.4f}\n\n"
        f"💳 Payment method: {config.PAYMENT_DETAILS}\n\n"
    )
    
    if user.balance >= config.MIN_WITHDRAWAL:
        text += "Click the button below to request a withdrawal."
    else:
        text += f"❌ You need ${config.MIN_WITHDRAWAL - user.balance:.4f} more to withdraw."
    
    await callback.message.edit_text(text, reply_markup=withdraw_menu(user.balance, config.MIN_WITHDRAWAL))
    await callback.answer()

async def request_withdrawal_callback(callback: types.CallbackQuery, state: FSMContext):
    session = callback.bot.get('session')
    user = create_or_get_user(session, callback.from_user)
    
    if user.balance < config.MIN_WITHDRAWAL:
        await callback.answer("❌ Your balance is below the minimum withdrawal amount.", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"💸 <b>Withdrawal Request</b>\n\n"
        f"💰 Available balance: ${user.balance:.4f}\n"
        f"💳 Payment method: {config.PAYMENT_DETAILS}\n\n"
        f"Please enter the amount you want to withdraw (max ${user.balance:.4f}):",
        reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔙 Cancel", callback_data="withdraw"))
    )
    
    await WithdrawalRequest.amount.set()
    await state.update_data(user_id=user.id, max_amount=user.balance)
    await callback.answer()

async def process_withdrawal_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        data = await state.get_data()
        
        if amount <= 0:
            await message.reply("❌ Amount must be greater than 0.")
            return
        if amount > data['max_amount']:
            await message.reply(f"❌ You can't withdraw more than your balance (${data['max_amount']:.4f}).")
            return
        
        session = message.bot.get('session')
        user = session.query(User).filter_by(user_id=data['user_id']).first()
        
        if not user or user.balance < amount:
            await message.reply("❌ Insufficient balance.")
            return
        
        transaction = Transaction(
            user_id=user.id,
            amount=amount,
            type='withdrawal',
            status='pending',
            details=f"Withdrawal request to {config.PAYMENT_DETAILS}"
        )
        session.add(transaction)
        user.balance -= amount
        session.commit()
        
        await message.answer(
            f"✅ Withdrawal request for ${amount:.4f} submitted!\n\n"
            f"💳 Payment method: {config.PAYMENT_DETAILS}\n"
            f"🔄 Status: Pending approval\n\n"
            f"We'll process your request within 24-48 hours.",
            reply_markup=main_menu()
        )
        
        admin_text = (
            "🔄 <b>New Withdrawal Request</b>\n\n"
            f"👤 User: {user.first_name} (@{user.username or 'N/A'})\n"
            f"🆔 ID: {user.user_id}\n"
            f"💰 Amount: ${amount:.4f}\n"
            f"💳 Method: {config.PAYMENT_DETAILS}\n\n"
            f"📋 Transaction ID: {transaction.id}"
        )
        
        for admin_id in config.ADMIN_IDS:
            try:
                await message.bot.send_message(admin_id, admin_text)
            except Exception:
                pass
        
    except ValueError:
        await message.reply("❌ Please enter a valid number.")
        return
    
    await state.finish()

async def task_join_channel_callback(callback: types.CallbackQuery):
    if not config.CHANNEL_ID:
        await callback.answer("❌ No channel task available at the moment.", show_alert=True)
        return
    
    session = callback.bot.get('session')
    user = create_or_get_user(session, callback.from_user)
    
    existing_task = session.query(UserTask).filter_by(
        user_id=user.id,
        task_type='join_channel',
        task_id=config.CHANNEL_ID
    ).first()
    
    if existing_task:
        await callback.answer("❌ You've already completed this task.", show_alert=True)
        return
    
    try:
        channel = await callback.bot.get_chat(config.CHANNEL_ID)
        text = (
            f"📢 <b>Join Channel Task</b>\n\n"
            f"Join the channel below and click the button to verify:\n\n"
            f"🔗 {channel.title}\n"
            f"👉 {channel.invite_link}\n\n"
            f"💰 Reward: ${config.JOIN_CHANNEL_REWARD:.4f}"
        )
        
        await callback.message.edit_text(
            text,
            reply_markup=confirm_join_channel(config.CHANNEL_ID)
        )
    except BadRequest:
        await callback.answer("❌ Channel not found.", show_alert=True)
    
    await callback.answer()

async def confirm_join_channel_callback(callback: types.CallbackQuery):
    channel_id = callback.data.split('_')[-1]
    session = callback.bot.get('session')
    user = create_or_get_user(session, callback.from_user)
    
    is_member = await check_channel_membership(callback.bot, user.user_id, channel_id)
    
    if not is_member:
        await callback.answer("❌ You haven't joined the channel yet.", show_alert=True)
        return
    
    existing_task = session.query(UserTask).filter_by(
        user_id=user.id,
        task_type='join_channel',
        task_id=channel_id
    ).first()
    
    if existing_task:
        await callback.answer("❌ You've already completed this task.", show_alert=True)
        return
    
    task = UserTask(
        user_id=user.id,
        task_type='join_channel',
        task_id=channel_id,
        reward=config.JOIN_CHANNEL_REWARD
    )
    session.add(task)
    
    transaction = Transaction(
        user_id=user.id,
        amount=config.JOIN_CHANNEL_REWARD,
        type='task',
        status='completed',
        details=f"Joined channel {channel_id}"
    )
    session.add(transaction)
    user.balance += config.JOIN_CHANNEL_REWARD
    session.commit()
    
    await callback.message.edit_text(
        f"✅ Task Completed!\n\n"
        f"💰 You've earned ${config.JOIN_CHANNEL_REWARD:.4f}\n\n"
        f"Your new balance: ${user.balance:.4f}",
        reply_markup=back_to_main()
    )
    await callback.answer()

async def task_view_post_callback(callback: types.CallbackQuery):
    duration = int(callback.data.split('_')[-1])
    session = callback.bot.get('session')
    user = create_or_get_user(session, callback.from_user)
    
    task = session.query(Task).filter_by(
        task_type='view_post',
        active=True
    ).order_by(func.random()).first()
    
    if not task:
        await callback.answer("❌ No post viewing tasks available at the moment.", show_alert=True)
        return
    
    existing_task = session.query(UserTask).filter_by(
        user_id=user.id,
        task_type='view_post',
        task_id=task.id
    ).first()
    
    if existing_task:
        await callback.answer("❌ You've already completed this task.", show_alert=True)
        return
    
    reward = getattr(config, f"VIEW_POST_{duration}_REWARD")
    
    text = (
        f"👀 <b>View Post Task ({duration}s)</b>\n\n"
        f"Stay on this post for {duration} seconds to earn ${reward:.4f}!\n\n"
        f"Post URL: {task.target_id}\n\n"
        f"Timer will start when you click 'Start'."
    )
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("⏳ Start Timer", callback_data=f"start_timer_{duration}_{task.id}"))
    keyboard.add(types.InlineKeyboardButton("🔙 Back", callback_data="tasks"))
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

async def start_timer_callback(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    duration = int(parts[2])
    task_id = int(parts[3])
    
    session = callback.bot.get('session')
    user = create_or_get_user(session, callback.from_user)
    task = session.query(Task).get(task_id)
    
    if not task or not task.active:
        await callback.answer("❌ This task is no longer available.", show_alert=True)
        return
    
    existing_task = session.query(UserTask).filter_by(
        user_id=user.id,
        task_type='view_post',
        task_id=task.id
    ).first()
    
    if existing_task:
        await callback.answer("❌ You've already completed this task.", show_alert=True)
        return
    
    reward = getattr(config, f"VIEW_POST_{duration}_REWARD")
    
    remaining = duration
    message = await callback.message.edit_text(
        f"⏳ Timer started! Stay on this page for {duration} seconds.\n\n"
        f"Remaining: {remaining}s",
        reply_markup=view_post_timer(remaining, task.id)
    )
    
    while remaining > 0:
        await asyncio.sleep(1)
        remaining -= 1
        try:
            await message.edit_text(
                f"⏳ Timer started! Stay on this page for {duration} seconds.\n\n"
                f"Remaining: {remaining}s",
                reply_markup=view_post_timer(remaining, task.id)
            )
        except:
            break
    
    if remaining <= 0:
        task_record = UserTask(
            user_id=user.id,
            task_type='view_post',
            task_id=task.id,
            reward=reward
        )
        session.add(task_record)
        
        transaction = Transaction(
            user_id=user.id,
            amount=reward,
            type='task',
            status='completed',
            details=f"Viewed post for {duration}s"
        )
        session.add(transaction)
        
        task.current_completions += 1
        if task.max_completions and task.current_completions >= task.max_completions:
            task.active = False
        
        user.balance += reward
        session.commit()
        
        await message.edit_text(
            f"✅ Task Completed!\n\n"
            f"💰 You've earned ${reward:.4f}\n\n"
            f"Your new balance: ${user.balance:.4f}",
            reply_markup=back_to_main()
        )
    else:
        await message.edit_text(
            "❌ Task not completed. You left the page too early.",
            reply_markup=back_to_main()
        )

async def admin_panel_command(message: types.Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Access denied.")
        return
    
    session = message.bot.get('session')
    
    total_users = session.query(User).count()
    active_users = session.query(User).filter(
        func.date(User.join_date) >= func.date('now', '-7 days')
    ).count()
    total_referrals = session.query(Referral).count()
    completed_tasks = session.query(UserTask).count()
    pending_withdrawals = session.query(Transaction).filter_by(
        type='withdrawal',
        status='pending'
    ).count()
    
    text = (
        "👨‍💻 <b>Admin Panel</b>\n\n"
        f"👥 Total Users: {total_users}\n"
        f"🚀 Active Users (7d): {active_users}\n"
        f"📤 Total Referrals: {total_referrals}\n"
        f"✅ Completed Tasks: {completed_tasks}\n"
        f"🔄 Pending Withdrawals: {pending_withdrawals}\n\n"
        "Use the menu below to manage the bot:"
    )
    
    await message.answer(text, reply_markup=admin_menu())

# [Previous code continues with all admin handlers...]

# Main function
async def main():
    logging.basicConfig(level=logging.INFO)
    
    # Initialize bot and dispatcher
    bot = Bot(token=config.BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    
    # Initialize database
    engine = init_db()
    dp['session'] = get_session(engine)
    
    # Register handlers
    dp.register_message_handler(start_command, commands=['start'])
    dp.register_callback_query_handler(main_menu_callback, text="main_menu")
    dp.register_callback_query_handler(balance_callback, text="balance")
    dp.register_callback_query_handler(profile_callback, text="profile")
    dp.register_callback_query_handler(transactions_callback, text="transactions")
    dp.register_callback_query_handler(referral_callback, text="referral")
    dp.register_callback_query_handler(tasks_callback, text="tasks")
    dp.register_callback_query_handler(withdraw_callback, text="withdraw")
    dp.register_callback_query_handler(request_withdrawal_callback, text="request_withdrawal", state="*")
    dp.register_message_handler(process_withdrawal_amount, state=WithdrawalRequest.amount)
    dp.register_callback_query_handler(task_join_channel_callback, text_startswith="task_join_channel")
    dp.register_callback_query_handler(confirm_join_channel_callback, text_startswith="confirm_join_")
    dp.register_callback_query_handler(task_view_post_callback, text_startswith="task_view_post_")
    dp.register_callback_query_handler(start_timer_callback, text_startswith="start_timer_")
    dp.register_message_handler(admin_panel_command, commands=['adminpanel'])
    
    # Start the bot
    try:
        await dp.start_polling()
    finally:
        await dp.storage.close()
        await dp.storage.wait_closed()

if __name__ == '__main__':
    asyncio.run(main())
