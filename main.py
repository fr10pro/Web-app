import os
import time
import datetime
import logging
from typing import Dict, List, Optional, Tuple
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, User
)
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MongoDB setup
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client["refer_earn_bot"]
users_collection = db["users"]
tasks_collection = db["tasks"]
transactions_collection = db["transactions"]
settings_collection = db["settings"]

# Initialize bot
app = Client(
    "refer_earn_bot",
    api_id=os.getenv("API_ID"),
    api_hash=os.getenv("API_HASH"),
    bot_token=os.getenv("BOT_TOKEN")
)

# Constants
DEFAULT_REFERRAL_REWARD = 0.200
DEFAULT_MIN_WITHDRAWAL = 1.000
TASK_TYPES = {
    "join_channel": "Join Channel",
    "view_post": "View Post"
}
TASK_DURATIONS = {
    "15s": 15,
    "30s": 30,
    "60s": 60,
    "120s": 120
}

# Initialize default settings if not exists
if not settings_collection.find_one({"name": "app_settings"}):
    settings_collection.insert_one({
        "name": "app_settings",
        "referral_reward": DEFAULT_REFERRAL_REWARD,
        "min_withdrawal": DEFAULT_MIN_WITHDRAWAL,
        "payment_details": "Send your withdrawal request to our PayPal: example@example.com",
        "channel_to_join": os.getenv("DEFAULT_CHANNEL"),
        "admin_ids": [int(admin_id) for admin_id in os.getenv("ADMIN_IDS").split(",")]
    })

# Helper functions
def get_user(user_id: int) -> Dict:
    user = users_collection.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "balance": 0.0,
            "referral_count": 0,
            "referral_code": str(user_id),
            "joined_at": datetime.datetime.now(),
            "completed_tasks": [],
            "pending_withdrawal": 0.0
        }
        users_collection.insert_one(user)
    return user

def update_user(user_id: int, update_data: Dict):
    users_collection.update_one({"user_id": user_id}, {"$set": update_data})

def add_transaction(user_id: int, amount: float, transaction_type: str, details: str = ""):
    transactions_collection.insert_one({
        "user_id": user_id,
        "amount": amount,
        "type": transaction_type,
        "details": details,
        "created_at": datetime.datetime.now(),
        "status": "completed" if transaction_type != "withdrawal" else "pending"
    })

def get_settings() -> Dict:
    return settings_collection.find_one({"name": "app_settings"})

def update_settings(update_data: Dict):
    settings_collection.update_one({"name": "app_settings"}, {"$set": update_data})

def format_balance(balance: float) -> str:
    return f"{balance:.4f}$"

def create_task(task_type: str, **kwargs) -> str:
    task = {
        "type": task_type,
        "created_at": datetime.datetime.now(),
        "is_active": True,
        **kwargs
    }
    result = tasks_collection.insert_one(task)
    return str(result.inserted_id)

def get_active_tasks() -> List[Dict]:
    return list(tasks_collection.find({"is_active": True}))

async def is_member(user_id: int, channel_id: int) -> bool:
    try:
        member = await app.get_chat_member(channel_id, user_id)
        return member.status not in [enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED]
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False

# Bot commands and handlers
@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    args = message.text.split()
    
    # Check if this is a referral
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != user_id:
            referrer = get_user(referrer_id)
            if referrer:
                settings = get_settings()
                reward = settings.get("referral_reward", DEFAULT_REFERRAL_REWARD)
                
                # Update referrer's balance
                users_collection.update_one(
                    {"user_id": referrer_id},
                    {
                        "$inc": {
                            "balance": reward,
                            "referral_count": 1
                        }
                    }
                )
                
                # Add transaction for referrer
                add_transaction(
                    referrer_id,
                    reward,
                    "referral",
                    f"Referral from user {user_id}"
                )
    
    user = get_user(user_id)
    
    # Update user info if changed
    update_data = {}
    if message.from_user.first_name != user.get("first_name"):
        update_data["first_name"] = message.from_user.first_name
    if message.from_user.last_name != user.get("last_name"):
        update_data["last_name"] = message.from_user.last_name
    if message.from_user.username != user.get("username"):
        update_data["username"] = message.from_user.username
    
    if update_data:
        update_user(user_id, update_data)
    
    # Send welcome message
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("📊 Profile", callback_data="profile")],
        [InlineKeyboardButton("🎯 Tasks", callback_data="tasks"),
         InlineKeyboardButton("👥 Refer Friends", callback_data="refer")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]
    ])
    
    await message.reply_text(
        f"👋 Welcome to the Refer & Earn Bot!\n\n"
        f"Earn money by completing simple tasks and referring friends.\n\n"
        f"💰 Your current balance: {format_balance(user['balance'])}\n"
        f"👥 Your referrals: {user['referral_count']}\n\n"
        f"Use the buttons below to navigate:",
        reply_markup=keyboard
    )

@app.on_callback_query(filters.regex("^balance$"))
async def balance_callback(client: Client, callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    settings = get_settings()
    
    await callback.edit_message_text(
        f"💰 Your Balance\n\n"
        f"Current balance: {format_balance(user['balance'])}\n"
        f"Pending withdrawal: {format_balance(user['pending_withdrawal'])}\n\n"
        f"Minimum withdrawal: {format_balance(settings['min_withdrawal'])}\n\n"
        f"Complete tasks and refer friends to earn more!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
        ])
    )

@app.on_callback_query(filters.regex("^profile$"))
async def profile_callback(client: Client, callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    join_date = user['joined_at'].strftime("%Y-%m-%d %H:%M:%S")
    
    text = (
        f"👤 Your Profile\n\n"
        f"🆔 ID: {user['user_id']}\n"
        f"👤 Name: {callback.from_user.first_name}\n"
        f"📛 Username: @{callback.from_user.username}\n"
        f"📅 Joined: {join_date}\n\n"
        f"👥 Referrals: {user['referral_count']}\n"
        f"✅ Completed tasks: {len(user['completed_tasks'])}\n"
        f"💰 Balance: {format_balance(user['balance'])}\n"
    )
    
    await callback.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 Transactions", callback_data="transactions")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
        ])
    )

@app.on_callback_query(filters.regex("^transactions$"))
async def transactions_callback(client: Client, callback: CallbackQuery):
    transactions = list(transactions_collection.find(
        {"user_id": callback.from_user.id}
    ).sort("created_at", -1).limit(10))
    
    if not transactions:
        await callback.answer("No transactions found!", show_alert=True)
        return
    
    text = "📜 Your Last 10 Transactions\n\n"
    for tx in transactions:
        date = tx['created_at'].strftime("%Y-%m-%d")
        amount = format_balance(tx['amount'])
        status = tx.get('status', 'completed')
        text += f"⏰ {date} | {amount} | {tx['type'].capitalize()} | {status}\n"
        if tx.get('details'):
            text += f"   📝 {tx['details']}\n"
        text += "\n"
    
    await callback.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="profile")]
        ])
    )

@app.on_callback_query(filters.regex("^tasks$"))
async def tasks_callback(client: Client, callback: CallbackQuery):
    active_tasks = get_active_tasks()
    
    if not active_tasks:
        await callback.edit_message_text(
            "No tasks available at the moment. Please check back later!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
            ])
        )
        return
    
    buttons = []
    for task in active_tasks[:5]:  # Show max 5 tasks at a time
        task_type = TASK_TYPES.get(task['type'], task['type'])
        buttons.append([InlineKeyboardButton(
            f"{task_type} - {task.get('reward', '0.0000')}$",
            callback_data=f"view_task_{task['_id']}"
        )])
    
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    
    await callback.edit_message_text(
        "🎯 Available Tasks\n\n"
        "Complete these tasks to earn money:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex("^view_task_(.*)"))
async def view_task_callback(client: Client, callback: CallbackQuery):
    task_id = callback.matches[0].group(1)
    task = tasks_collection.find_one({"_id": task_id})
    
    if not task or not task.get('is_active', False):
        await callback.answer("This task is no longer available!", show_alert=True)
        return
    
    user = get_user(callback.from_user.id)
    
    # Check if user already completed this task
    if task_id in user.get('completed_tasks', []):
        await callback.answer("You've already completed this task!", show_alert=True)
        return
    
    if task['type'] == 'join_channel':
        channel_id = task.get('channel_id', get_settings().get('channel_to_join'))
        
        # Check if user is already a member
        is_member_already = await is_member(callback.from_user.id, channel_id)
        
        if is_member_already:
            # User is already a member, give reward immediately
            reward = task.get('reward', 0.1)
            
            # Update user balance
            users_collection.update_one(
                {"user_id": callback.from_user.id},
                {
                    "$inc": {"balance": reward},
                    "$push": {"completed_tasks": task_id}
                }
            )
            
            # Add transaction
            add_transaction(
                callback.from_user.id,
                reward,
                "task_reward",
                f"Completed join channel task {task_id}"
            )
            
            await callback.edit_message_text(
                f"✅ Task Completed!\n\n"
                f"You've earned {format_balance(reward)} for joining the channel!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎯 More Tasks", callback_data="tasks"),
                     InlineKeyboardButton("💰 Balance", callback_data="balance")]
                ])
            )
        else:
            # Ask user to join channel
            try:
                channel = await client.get_chat(channel_id)
                await callback.edit_message_text(
                    f"📢 Join Channel Task\n\n"
                    f"To complete this task and earn {format_balance(task.get('reward', 0.1))}, "
                    f"you need to join this channel:\n\n"
                    f"📢 {channel.title}\n"
                    f"👥 Members: {channel.members_count}\n\n"
                    f"After joining, click the button below to verify:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Join Channel", url=f"https://t.me/{channel.username}")],
                        [InlineKeyboardButton("✅ I've Joined", callback_data=f"verify_join_{task_id}")],
                        [InlineKeyboardButton("🔙 Back", callback_data="tasks")]
                    ])
                )
            except Exception as e:
                logger.error(f"Error getting channel info: {e}")
                await callback.answer("Error loading task. Please try again later.", show_alert=True)
    
    elif task['type'] == 'view_post':
        post_url = task.get('post_url')
        duration = task.get('duration', 30)
        
        await callback.edit_message_text(
            f"📰 View Post Task\n\n"
            f"To complete this task and earn {format_balance(task.get('reward', 0.1))}, "
            f"you need to view this post for {duration} seconds:\n\n"
            f"Click the button below to open the post, then return here and wait for the timer.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Open Post", url=post_url)],
                [InlineKeyboardButton(f"Start {duration}s Timer", callback_data=f"start_timer_{task_id}_{duration}")],
                [InlineKeyboardButton("🔙 Back", callback_data="tasks")]
            ])
        )

@app.on_callback_query(filters.regex("^verify_join_(.*)"))
async def verify_join_callback(client: Client, callback: CallbackQuery):
    task_id = callback.matches[0].group(1)
    task = tasks_collection.find_one({"_id": task_id})
    
    if not task or not task.get('is_active', False):
        await callback.answer("This task is no longer available!", show_alert=True)
        return
    
    user = get_user(callback.from_user.id)
    
    # Check if user already completed this task
    if task_id in user.get('completed_tasks', []):
        await callback.answer("You've already completed this task!", show_alert=True)
        return
    
    channel_id = task.get('channel_id', get_settings().get('channel_to_join'))
    is_member_now = await is_member(callback.from_user.id, channel_id)
    
    if is_member_now:
        reward = task.get('reward', 0.1)
        
        # Update user balance
        users_collection.update_one(
            {"user_id": callback.from_user.id},
            {
                "$inc": {"balance": reward},
                "$push": {"completed_tasks": task_id}
            }
        )
        
        # Add transaction
        add_transaction(
            callback.from_user.id,
            reward,
            "task_reward",
            f"Completed join channel task {task_id}"
        )
        
        await callback.edit_message_text(
            f"✅ Task Completed!\n\n"
            f"You've earned {format_balance(reward)} for joining the channel!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎯 More Tasks", callback_data="tasks"),
                 InlineKeyboardButton("💰 Balance", callback_data="balance")]
            ])
        )
    else:
        await callback.answer("You haven't joined the channel yet!", show_alert=True)

@app.on_callback_query(filters.regex("^start_timer_(.*)_(.*)"))
async def start_timer_callback(client: Client, callback: CallbackQuery):
    task_id = callback.matches[0].group(1)
    duration = int(callback.matches[0].group(2))
    task = tasks_collection.find_one({"_id": task_id})
    
    if not task or not task.get('is_active', False):
        await callback.answer("This task is no longer available!", show_alert=True)
        return
    
    user = get_user(callback.from_user.id)
    
    # Check if user already completed this task
    if task_id in user.get('completed_tasks', []):
        await callback.answer("You've already completed this task!", show_alert=True)
        return
    
    # Start the countdown
    message = await callback.edit_message_text(
        f"⏳ Timer Started\n\n"
        f"Please keep this window open for {duration} seconds...\n\n"
        f"Time remaining: {duration}s",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data=f"cancel_timer_{task_id}")]
        ])
    )
    
    start_time = time.time()
    remaining = duration
    
    while remaining > 0:
        if time.time() - start_time >= duration:
            break
        
        await asyncio.sleep(1)
        remaining = max(0, duration - int(time.time() - start_time))
        
        try:
            await message.edit_text(
                f"⏳ Timer Started\n\n"
                f"Please keep this window open for {duration} seconds...\n\n"
                f"Time remaining: {remaining}s",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Cancel", callback_data=f"cancel_timer_{task_id}")]
                ])
            )
        except:
            # User might have closed the message or there was an edit conflict
            return
    
    # Task completed successfully
    reward = task.get('reward', 0.1)
    
    # Update user balance
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {
            "$inc": {"balance": reward},
            "$push": {"completed_tasks": task_id}
        }
    )
    
    # Add transaction
    add_transaction(
        callback.from_user.id,
        reward,
        "task_reward",
        f"Completed view post task {task_id}"
    )
    
    await message.edit_text(
        f"✅ Task Completed!\n\n"
        f"You've earned {format_balance(reward)} for viewing the post!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 More Tasks", callback_data="tasks"),
             InlineKeyboardButton("💰 Balance", callback_data="balance")]
        ])
    )

@app.on_callback_query(filters.regex("^cancel_timer_(.*)"))
async def cancel_timer_callback(client: Client, callback: CallbackQuery):
    await callback.answer("Task cancelled!", show_alert=True)
    await callback.edit_message_text(
        "Task cancelled. You can try again later.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 More Tasks", callback_data="tasks")]
        ])
    )

@app.on_callback_query(filters.regex("^refer$"))
async def refer_callback(client: Client, callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    settings = get_settings()
    reward = settings.get("referral_reward", DEFAULT_REFERRAL_REWARD)
    
    bot_username = (await client.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={callback.from_user.id}"
    
    await callback.edit_message_text(
        f"👥 Refer Friends & Earn\n\n"
        f"Invite your friends to join this bot using your referral link below:\n\n"
        f"🔗 Your referral link:\n"
        f"<code>{referral_link}</code>\n\n"
        f"💰 You earn {format_balance(reward)} for each friend who joins using your link!\n\n"
        f"👥 Total referrals: {user['referral_count']}\n"
        f"💰 Earned from referrals: {format_balance(user['referral_count'] * reward)}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={referral_link}&text=Join%20this%20awesome%20bot%20and%20earn%20money!")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
        ])
    )

@app.on_callback_query(filters.regex("^withdraw$"))
async def withdraw_callback(client: Client, callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    settings = get_settings()
    min_withdrawal = settings.get("min_withdrawal", DEFAULT_MIN_WITHDRAWAL)
    payment_details = settings.get("payment_details", "")
    
    if user['balance'] < min_withdrawal:
        await callback.edit_message_text(
            f"💸 Withdraw Funds\n\n"
            f"Your current balance: {format_balance(user['balance'])}\n"
            f"Minimum withdrawal amount: {format_balance(min_withdrawal)}\n\n"
            f"You need to earn more before you can withdraw.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎯 Complete Tasks", callback_data="tasks")],
                [InlineKeyboardButton("👥 Refer Friends", callback_data="refer")],
                [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
            ])
        )
        return
    
    await callback.edit_message_text(
        f"💸 Withdraw Funds\n\n"
        f"Your available balance: {format_balance(user['balance'])}\n"
        f"Minimum withdrawal: {format_balance(min_withdrawal)}\n\n"
        f"Payment method:\n"
        f"{payment_details}\n\n"
        f"Enter the amount you want to withdraw (e.g., 1.0000):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
        ])
    )
    
    # Set a flag that we're waiting for withdrawal amount
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {"$set": {"awaiting_withdrawal_amount": True}}
    )

@app.on_message(filters.private & ~filters.command(["start", "adminpanel"]))
async def handle_withdrawal_amount(client: Client, message: Message):
    user = get_user(message.from_user.id)
    
    if user.get('awaiting_withdrawal_amount'):
        try:
            amount = float(message.text)
            settings = get_settings()
            min_withdrawal = settings.get("min_withdrawal", DEFAULT_MIN_WITHDRAWAL)
            
            if amount < min_withdrawal:
                await message.reply_text(
                    f"Amount must be at least {format_balance(min_withdrawal)}. "
                    f"Please enter a valid amount:"
                )
                return
            
            if amount > user['balance']:
                await message.reply_text(
                    f"You don't have enough balance. Your current balance is "
                    f"{format_balance(user['balance'])}. Please enter a valid amount:"
                )
                return
            
            # Update user balance and create withdrawal request
            users_collection.update_one(
                {"user_id": message.from_user.id},
                {
                    "$inc": {"balance": -amount, "pending_withdrawal": amount},
                    "$set": {"awaiting_withdrawal_amount": False}
                }
            )
            
            # Add transaction
            add_transaction(
                message.from_user.id,
                amount,
                "withdrawal",
                "Pending admin approval"
            )
            
            # Notify admin
            admin_ids = settings.get("admin_ids", [])
            for admin_id in admin_ids:
                try:
                    await client.send_message(
                        admin_id,
                        f"⚠️ New Withdrawal Request\n\n"
                        f"User: {message.from_user.mention}\n"
                        f"Amount: {format_balance(amount)}\n"
                        f"User ID: {message.from_user.id}\n\n"
                        f"Use /adminpanel to review requests."
                    )
                except Exception as e:
                    logger.error(f"Error notifying admin {admin_id}: {e}")
            
            await message.reply_text(
                f"✅ Withdrawal request submitted!\n\n"
                f"Amount: {format_balance(amount)}\n\n"
                f"Our team will process your request soon. "
                f"You'll be notified once it's completed.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ])
            )
        except ValueError:
            await message.reply_text(
                "Please enter a valid amount (e.g., 1.0000):"
            )
    else:
        # If not waiting for withdrawal amount, just show main menu
        await start_command(client, message)

@app.on_callback_query(filters.regex("^main_menu$"))
async def main_menu_callback(client: Client, callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("📊 Profile", callback_data="profile")],
        [InlineKeyboardButton("🎯 Tasks", callback_data="tasks"),
         InlineKeyboardButton("👥 Refer Friends", callback_data="refer")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")]
    ])
    
    await callback.edit_message_text(
        f"🏠 Main Menu\n\n"
        f"💰 Your current balance: {format_balance(user['balance'])}\n"
        f"👥 Your referrals: {user['referral_count']}\n\n"
        f"Use the buttons below to navigate:",
        reply_markup=keyboard
    )

# Admin commands
@app.on_message(filters.command("adminpanel") & filters.private)
async def admin_panel(client: Client, message: Message):
    settings = get_settings()
    
    if message.from_user.id not in settings.get("admin_ids", []):
        await message.reply_text("You are not authorized to access this panel.")
        return
    
    await message.reply_text(
        "👑 Admin Panel\n\n"
        "Select an option below:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
             InlineKeyboardButton("👤 User Control", callback_data="admin_users")],
            [InlineKeyboardButton("💰 Withdrawal Requests", callback_data="admin_withdrawals")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings"),
             InlineKeyboardButton("➕ Add Task", callback_data="admin_add_task")]
        ])
    )

@app.on_callback_query(filters.regex("^admin_stats$"))
async def admin_stats_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    total_users = users_collection.count_documents({})
    active_users = users_collection.count_documents({
        "joined_at": {"$gte": datetime.datetime.now() - datetime.timedelta(days=30)}
    })
    total_referrals = users_collection.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$referral_count"}}}
    ]).next().get("total", 0)
    total_tasks = transactions_collection.count_documents({"type": "task_reward"})
    total_withdrawn = transactions_collection.aggregate([
        {"$match": {"type": "withdrawal", "status": "completed"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ])
    total_withdrawn = total_withdrawn.next().get("total", 0) if total_withdrawn.alive else 0
    
    await callback.edit_message_text(
        f"📊 Bot Statistics\n\n"
        f"👤 Total users: {total_users}\n"
        f"👥 Active users (last 30 days): {active_users}\n"
        f"🤝 Total referrals: {total_referrals}\n"
        f"✅ Completed tasks: {total_tasks}\n"
        f"💸 Total withdrawn: {format_balance(total_withdrawn)}\n\n"
        f"Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )

@app.on_callback_query(filters.regex("^admin_users$"))
async def admin_users_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    await callback.edit_message_text(
        "👤 User Control\n\n"
        "Enter the user ID you want to manage:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )
    
    # Set flag that we're waiting for user ID
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {"$set": {"admin_awaiting_user_id": True}}
    )

@app.on_message(filters.private & filters.regex(r"^\d+$"))
async def handle_admin_user_id(client: Client, message: Message):
    user = get_user(message.from_user.id)
    settings = get_settings()
    
    if message.from_user.id not in settings.get("admin_ids", []) or not user.get('admin_awaiting_user_id'):
        return
    
    try:
        target_user_id = int(message.text)
        target_user = get_user(target_user_id)
        
        if not target_user:
            await message.reply_text("User not found. Please try again:")
            return
        
        # Reset the flag
        users_collection.update_one(
            {"user_id": message.from_user.id},
            {"$set": {"admin_awaiting_user_id": False}}
        )
        
        join_date = target_user['joined_at'].strftime("%Y-%m-%d %H:%M:%S")
        
        await message.reply_text(
            f"👤 User Management\n\n"
            f"🆔 ID: {target_user_id}\n"
            f"📅 Joined: {join_date}\n"
            f"👥 Referrals: {target_user['referral_count']}\n"
            f"💰 Balance: {format_balance(target_user['balance'])}\n"
            f"⏳ Pending withdrawal: {format_balance(target_user['pending_withdrawal'])}\n\n"
            f"Select an action:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Balance", callback_data=f"admin_add_balance_{target_user_id}"),
                 InlineKeyboardButton("➖ Subtract Balance", callback_data=f"admin_sub_balance_{target_user_id}")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ])
        )
    except ValueError:
        await message.reply_text("Please enter a valid user ID:")

@app.on_callback_query(filters.regex("^admin_add_balance_(.*)"))
async def admin_add_balance_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    target_user_id = int(callback.matches[0].group(1))
    
    await callback.edit_message_text(
        f"➕ Add Balance to User {target_user_id}\n\n"
        f"Enter the amount to add:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data=f"admin_user_{target_user_id}")]
        ])
    )
    
    # Set flag that we're waiting for amount to add
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {
            "$set": {
                "admin_awaiting_amount": True,
                "admin_target_user": target_user_id,
                "admin_balance_action": "add"
            }
        }
    )

@app.on_callback_query(filters.regex("^admin_sub_balance_(.*)"))
async def admin_sub_balance_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    target_user_id = int(callback.matches[0].group(1))
    target_user = get_user(target_user_id)
    
    await callback.edit_message_text(
        f"➖ Subtract Balance from User {target_user_id}\n\n"
        f"Current balance: {format_balance(target_user['balance'])}\n\n"
        f"Enter the amount to subtract:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data=f"admin_user_{target_user_id}")]
        ])
    )
    
    # Set flag that we're waiting for amount to subtract
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {
            "$set": {
                "admin_awaiting_amount": True,
                "admin_target_user": target_user_id,
                "admin_balance_action": "subtract"
            }
        }
    )

@app.on_message(filters.private & filters.regex(r"^\d+\.?\d*$"))
async def handle_admin_balance_change(client: Client, message: Message):
    user = get_user(message.from_user.id)
    settings = get_settings()
    
    if (message.from_user.id not in settings.get("admin_ids", []) or 
        not user.get('admin_awaiting_amount')):
        return
    
    try:
        amount = float(message.text)
        target_user_id = user.get('admin_target_user')
        action = user.get('admin_balance_action')
        
        if not target_user_id or action not in ['add', 'subtract']:
            await message.reply_text("Invalid operation. Please try again.")
            return
        
        target_user = get_user(target_user_id)
        
        if action == 'subtract' and amount > target_user['balance']:
            await message.reply_text(
                f"Amount exceeds user's balance ({format_balance(target_user['balance'])}). "
                f"Please enter a valid amount:"
            )
            return
        
        # Update target user's balance
        update_amount = amount if action == 'add' else -amount
        users_collection.update_one(
            {"user_id": target_user_id},
            {"$inc": {"balance": update_amount}}
        )
        
        # Add transaction
        add_transaction(
            target_user_id,
            amount,
            "admin_adjustment",
            f"Balance {action}ed by admin {message.from_user.id}"
        )
        
        # Reset admin flags
        users_collection.update_one(
            {"user_id": message.from_user.id},
            {
                "$set": {
                    "admin_awaiting_amount": False,
                    "admin_target_user": None,
                    "admin_balance_action": None
                }
            }
        )
        
        await message.reply_text(
            f"✅ User {target_user_id}'s balance has been updated.\n\n"
            f"Action: {action} {format_balance(amount)}\n"
            f"New balance: {format_balance(target_user['balance'] + update_amount)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Admin",
@app.on_callback_query(filters.regex("^admin_withdrawals$"))
async def admin_withdrawals_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    pending_withdrawals = list(transactions_collection.find(
        {"type": "withdrawal", "status": "pending"}
    ).sort("created_at", 1))
    
    if not pending_withdrawals:
        await callback.edit_message_text(
            "No pending withdrawal requests.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ])
        )
        return
    
    # Show first withdrawal request
    withdrawal = pending_withdrawals[0]
    user = get_user(withdrawal['user_id'])
    date = withdrawal['created_at'].strftime("%Y-%m-%d %H:%M:%S")
    
    await callback.edit_message_text(
        f"💰 Withdrawal Request\n\n"
        f"👤 User: {user.get('first_name', 'Unknown')} (@{user.get('username', 'N/A')})\n"
        f"🆔 ID: {withdrawal['user_id']}\n"
        f"⏰ Date: {date}\n"
        f"💸 Amount: {format_balance(withdrawal['amount'])}\n\n"
        f"Select action:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"admin_approve_wd_{withdrawal['_id']}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject_wd_{withdrawal['_id']}")],
            [InlineKeyboardButton("⏭ Next", callback_data=f"admin_next_wd_{withdrawal['_id']}")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )

@app.on_callback_query(filters.regex("^admin_approve_wd_(.*)"))
async def admin_approve_withdrawal(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    withdrawal_id = callback.matches[0].group(1)
    withdrawal = transactions_collection.find_one({"_id": withdrawal_id})
    
    if not withdrawal:
        await callback.answer("Withdrawal not found!", show_alert=True)
        return
    
    # Update transaction status
    transactions_collection.update_one(
        {"_id": withdrawal_id},
        {"$set": {"status": "completed"}}
    )
    
    # Update user's pending withdrawal
    users_collection.update_one(
        {"user_id": withdrawal['user_id']},
        {"$inc": {"pending_withdrawal": -withdrawal['amount']}}
    )
    
    # Notify user
    try:
        await client.send_message(
            withdrawal['user_id'],
            f"🎉 Your withdrawal request has been approved!\n\n"
            f"💸 Amount: {format_balance(withdrawal['amount'])}\n"
            f"🕒 Processed at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Thank you for using our service!"
        )
    except Exception as e:
        logger.error(f"Error notifying user about withdrawal: {e}")
    
    await callback.answer("Withdrawal approved!", show_alert=True)
    await admin_withdrawals_callback(client, callback)

@app.on_callback_query(filters.regex("^admin_reject_wd_(.*)"))
async def admin_reject_withdrawal(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    withdrawal_id = callback.matches[0].group(1)
    withdrawal = transactions_collection.find_one({"_id": withdrawal_id})
    
    if not withdrawal:
        await callback.answer("Withdrawal not found!", show_alert=True)
        return
    
    await callback.edit_message_text(
        f"❌ Reject Withdrawal\n\n"
        f"Enter the reason for rejection:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data=f"admin_withdrawal_{withdrawal_id}")]
        ])
    )
    
    # Set flag that we're waiting for rejection reason
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {
            "$set": {
                "admin_awaiting_reject_reason": True,
                "admin_target_withdrawal": withdrawal_id
            }
        }
    )

@app.on_message(filters.private & ~filters.command(["start", "adminpanel"]))
async def handle_admin_reject_reason(client: Client, message: Message):
    user = get_user(message.from_user.id)
    settings = get_settings()
    
    if (message.from_user.id not in settings.get("admin_ids", []) or 
        not user.get('admin_awaiting_reject_reason')):
        return
    
    withdrawal_id = user.get('admin_target_withdrawal')
    if not withdrawal_id:
        return
    
    reason = message.text
    withdrawal = transactions_collection.find_one({"_id": withdrawal_id})
    
    if not withdrawal:
        await message.reply_text("Withdrawal not found!")
        return
    
    # Return funds to user's balance
    users_collection.update_one(
        {"user_id": withdrawal['user_id']},
        {
            "$inc": {
                "balance": withdrawal['amount'],
                "pending_withdrawal": -withdrawal['amount']
            }
        }
    )
    
    # Update transaction status
    transactions_collection.update_one(
        {"_id": withdrawal_id},
        {
            "$set": {
                "status": "rejected",
                "details": f"Rejected: {reason}"
            }
        }
    )
    
    # Reset admin flags
    users_collection.update_one(
        {"user_id": message.from_user.id},
        {
            "$set": {
                "admin_awaiting_reject_reason": False,
                "admin_target_withdrawal": None
            }
        }
    )
    
    # Notify user
    try:
        await client.send_message(
            withdrawal['user_id'],
            f"⚠️ Your withdrawal request has been rejected\n\n"
            f"💸 Amount: {format_balance(withdrawal['amount'])}\n"
            f"📝 Reason: {reason}\n\n"
            f"The amount has been returned to your balance."
        )
    except Exception as e:
        logger.error(f"Error notifying user about rejection: {e}")
    
    await message.reply_text(
        "Withdrawal rejected and funds returned to user.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
        ])
    )

@app.on_callback_query(filters.regex("^admin_settings$"))
async def admin_settings_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    await callback.edit_message_text(
        f"⚙️ Bot Settings\n\n"
        f"💰 Referral reward: {format_balance(settings['referral_reward'])}\n"
        f"💸 Min withdrawal: {format_balance(settings['min_withdrawal'])}\n"
        f"📢 Channel to join: {settings.get('channel_to_join', 'Not set')}\n\n"
        f"Select setting to change:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Referral Reward", callback_data="admin_set_referral"),
             InlineKeyboardButton("✏️ Min Withdrawal", callback_data="admin_set_min_wd")],
            [InlineKeyboardButton("✏️ Payment Details", callback_data="admin_set_payment"),
             InlineKeyboardButton("✏️ Channel to Join", callback_data="admin_set_channel")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )

@app.on_callback_query(filters.regex("^admin_set_referral$"))
async def admin_set_referral_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    await callback.edit_message_text(
        f"✏️ Set Referral Reward\n\n"
        f"Current value: {format_balance(settings['referral_reward'])}\n\n"
        f"Enter new referral reward amount (e.g., 0.2000):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]
        ])
    )
    
    # Set flag that we're waiting for new referral reward
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {"$set": {"admin_awaiting_referral_reward": True}}
    )

@app.on_message(filters.private & ~filters.command(["start", "adminpanel"]))
async def handle_admin_referral_reward(client: Client, message: Message):
    user = get_user(message.from_user.id)
    settings = get_settings()
    
    if (message.from_user.id not in settings.get("admin_ids", []) or 
        not user.get('admin_awaiting_referral_reward')):
        return
    
    try:
        new_reward = float(message.text)
        if new_reward < 0:
            await message.reply_text("Reward must be positive. Please try again:")
            return
        
        # Update settings
        update_settings({"referral_reward": new_reward})
        
        # Reset flag
        users_collection.update_one(
            {"user_id": message.from_user.id},
            {"$set": {"admin_awaiting_referral_reward": False}}
        )
        
        await message.reply_text(
            f"✅ Referral reward updated to {format_balance(new_reward)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Settings", callback_data="admin_settings")]
            ])
        )
    except ValueError:
        await message.reply_text("Please enter a valid amount (e.g., 0.2000):")

@app.on_callback_query(filters.regex("^admin_set_min_wd$"))
async def admin_set_min_wd_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    await callback.edit_message_text(
        f"✏️ Set Minimum Withdrawal\n\n"
        f"Current value: {format_balance(settings['min_withdrawal'])}\n\n"
        f"Enter new minimum withdrawal amount (e.g., 1.0000):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]
        ])
    )
    
    # Set flag that we're waiting for new min withdrawal
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {"$set": {"admin_awaiting_min_wd": True}}
    )

@app.on_message(filters.private & ~filters.command(["start", "adminpanel"]))
async def handle_admin_min_withdrawal(client: Client, message: Message):
    user = get_user(message.from_user.id)
    settings = get_settings()
    
    if (message.from_user.id not in settings.get("admin_ids", []) or 
        not user.get('admin_awaiting_min_wd')):
        return
    
    try:
        new_min = float(message.text)
        if new_min <= 0:
            await message.reply_text("Amount must be positive. Please try again:")
            return
        
        # Update settings
        update_settings({"min_withdrawal": new_min})
        
        # Reset flag
        users_collection.update_one(
            {"user_id": message.from_user.id},
            {"$set": {"admin_awaiting_min_wd": False}}
        )
        
        await message.reply_text(
            f"✅ Minimum withdrawal updated to {format_balance(new_min)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Settings", callback_data="admin_settings")]
            ])
        )
    except ValueError:
        await message.reply_text("Please enter a valid amount (e.g., 1.0000):")

@app.on_callback_query(filters.regex("^admin_set_payment$"))
async def admin_set_payment_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    await callback.edit_message_text(
        f"✏️ Set Payment Details\n\n"
        f"Current details:\n{settings['payment_details']}\n\n"
        f"Enter new payment details:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]
        ])
    )
    
    # Set flag that we're waiting for new payment details
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {"$set": {"admin_awaiting_payment_details": True}}
    )

@app.on_message(filters.private & ~filters.command(["start", "adminpanel"]))
async def handle_admin_payment_details(client: Client, message: Message):
    user = get_user(message.from_user.id)
    settings = get_settings()
    
    if (message.from_user.id not in settings.get("admin_ids", []) or 
        not user.get('admin_awaiting_payment_details')):
        return
    
    # Update settings
    update_settings({"payment_details": message.text})
    
    # Reset flag
    users_collection.update_one(
        {"user_id": message.from_user.id},
        {"$set": {"admin_awaiting_payment_details": False}}
    )
    
    await message.reply_text(
        "✅ Payment details updated!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Settings", callback_data="admin_settings")]
        ])
    )

@app.on_callback_query(filters.regex("^admin_set_channel$"))
async def admin_set_channel_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    await callback.edit_message_text(
        f"✏️ Set Channel to Join\n\n"
        f"Current channel ID: {settings.get('channel_to_join', 'Not set')}\n\n"
        f"Enter new channel ID or username:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]
        ])
    )
    
    # Set flag that we're waiting for new channel
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {"$set": {"admin_awaiting_channel": True}}
    )

@app.on_message(filters.private & ~filters.command(["start", "adminpanel"]))
async def handle_admin_channel(client: Client, message: Message):
    user = get_user(message.from_user.id)
    settings = get_settings()
    
    if (message.from_user.id not in settings.get("admin_ids", []) or 
        not user.get('admin_awaiting_channel')):
        return
    
    try:
        # Try to get the channel to verify it exists
        channel = await client.get_chat(message.text)
        
        # Update settings
        update_settings({"channel_to_join": channel.id})
        
        # Reset flag
        users_collection.update_one(
            {"user_id": message.from_user.id},
            {"$set": {"admin_awaiting_channel": False}}
        )
        
        await message.reply_text(
            f"✅ Channel to join updated to:\n"
            f"📢 {channel.title}\n"
            f"🆔 {channel.id}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Settings", callback_data="admin_settings")]
            ])
        )
    except Exception as e:
        await message.reply_text(
            f"Error: {str(e)}\n\n"
            f"Please enter a valid channel ID or username:"
        )

@app.on_callback_query(filters.regex("^admin_add_task$"))
async def admin_add_task_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    await callback.edit_message_text(
        "➕ Add New Task\n\n"
        "Select task type:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel", callback_data="admin_add_task_join"),
             InlineKeyboardButton("📰 View Post", callback_data="admin_add_task_view")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ])
    )

@app.on_callback_query(filters.regex("^admin_add_task_join$"))
async def admin_add_task_join_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    await callback.edit_message_text(
        "📢 Add Join Channel Task\n\n"
        "Enter the reward amount for this task (e.g., 0.1000):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="admin_add_task")]
        ])
    )
    
    # Set flag that we're creating a join channel task
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {
            "$set": {
                "admin_creating_task": True,
                "admin_task_type": "join_channel",
                "admin_task_stage": "reward"
            }
        }
    )

@app.on_callback_query(filters.regex("^admin_add_task_view$"))
async def admin_add_task_view_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    await callback.edit_message_text(
        "📰 Add View Post Task\n\n"
        "Enter the reward amount for this task (e.g., 0.1000):",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="admin_add_task")]
        ])
    )
    
    # Set flag that we're creating a view post task
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {
            "$set": {
                "admin_creating_task": True,
                "admin_task_type": "view_post",
                "admin_task_stage": "reward"
            }
        }
    )

@app.on_message(filters.private & ~filters.command(["start", "adminpanel"]))
async def handle_admin_task_creation(client: Client, message: Message):
    user = get_user(message.from_user.id)
    settings = get_settings()
    
    if (message.from_user.id not in settings.get("admin_ids", []) or 
        not user.get('admin_creating_task')):
        return
    
    task_type = user.get('admin_task_type')
    task_stage = user.get('admin_task_stage')
    
    if task_stage == "reward":
        try:
            reward = float(message.text)
            if reward <= 0:
                await message.reply_text("Reward must be positive. Please try again:")
                return
            
            # Store reward and move to next stage
            users_collection.update_one(
                {"user_id": message.from_user.id},
                {
                    "$set": {
                        "admin_task_reward": reward,
                        "admin_task_stage": "channel" if task_type == "join_channel" else "post_url"
                    }
                }
            )
            
            if task_type == "join_channel":
                await message.reply_text(
                    f"💰 Reward set to {format_balance(reward)}\n\n"
                    f"Enter the channel ID or username to join:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Cancel", callback_data="admin_add_task")]
                    ])
                )
            else:
                await message.reply_text(
                    f"💰 Reward set to {format_balance(reward)}\n\n"
                    f"Enter the post URL to view:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Cancel", callback_data="admin_add_task")]
                    ])
                )
        except ValueError:
            await message.reply_text("Please enter a valid amount (e.g., 0.1000):")
    
    elif task_stage == "channel":
        try:
            channel = await client.get_chat(message.text)
            reward = user.get('admin_task_reward')
            
            # Create the task
            task_id = create_task(
                "join_channel",
                channel_id=channel.id,
                reward=reward
            )
            
            # Reset admin flags
            users_collection.update_one(
                {"user_id": message.from_user.id},
                {
                    "$set": {
                        "admin_creating_task": False,
                        "admin_task_type": None,
                        "admin_task_stage": None,
                        "admin_task_reward": None
                    }
                }
            )
            
            await message.reply_text(
                f"✅ Join Channel Task Created!\n\n"
                f"📢 Channel: {channel.title}\n"
                f"💰 Reward: {format_balance(reward)}\n"
                f"🆔 Task ID: {task_id}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
                ])
            )
        except Exception as e:
            await message.reply_text(
                f"Error: {str(e)}\n\n"
                f"Please enter a valid channel ID or username:"
            )
    
    elif task_stage == "post_url":
        post_url = message.text
        reward = user.get('admin_task_reward')
        
        # Validate URL format
        if not post_url.startswith("https://t.me/"):
            await message.reply_text(
                "Please enter a valid Telegram post URL (e.g., https://t.me/channel/123):"
            )
            return
        
        await message.reply_text(
            f"📰 Post URL set to: {post_url}\n\n"
            f"Select the required viewing duration:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("15 seconds", callback_data=f"admin_set_duration_15_{post_url}"),
                 InlineKeyboardButton("30 seconds", callback_data=f"admin_set_duration_30_{post_url}")],
                [InlineKeyboardButton("60 seconds", callback_data=f"admin_set_duration_60_{post_url}"),
                 InlineKeyboardButton("120 seconds", callback_data=f"admin_set_duration_120_{post_url}")],
                [InlineKeyboardButton("🔙 Cancel", callback_data="admin_add_task")]
            ])
        )

@app.on_callback_query(filters.regex("^admin_set_duration_(.*)_(.*)"))
async def admin_set_duration_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    duration = int(callback.matches[0].group(1))
    post_url = callback.matches[0].group(2)
    user = get_user(callback.from_user.id)
    reward = user.get('admin_task_reward')
    
    # Create the task
    task_id = create_task(
        "view_post",
        post_url=post_url,
        duration=duration,
        reward=reward
    )
    
    # Reset admin flags
    users_collection.update_one(
        {"user_id": callback.from_user.id},
        {
            "$set": {
                "admin_creating_task": False,
                "admin_task_type": None,
                "admin_task_stage": None,
                "admin_task_reward": None
            }
        }
    )
    
    await callback.edit_message_text(
        f"✅ View Post Task Created!\n\n"
        f"📰 Post: {post_url}\n"
        f"⏱ Duration: {duration} seconds\n"
        f"💰 Reward: {format_balance(reward)}\n"
        f"🆔 Task ID: {task_id}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
        ])
    )

@app.on_callback_query(filters.regex("^admin_back$"))
async def admin_back_callback(client: Client, callback: CallbackQuery):
    settings = get_settings()
    
    if callback.from_user.id not in settings.get("admin_ids", []):
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    await admin_panel(client, callback.message)

# Error handler
@app.on_error()
async def error_handler(client: Client, error: Exception):
    logger.error(f"Error: {error}", exc_info=True)

# Start the bot
if __name__ == "__main__":
    print("Starting bot...")
    app.run()
