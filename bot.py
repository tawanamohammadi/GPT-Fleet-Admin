import asyncio
import logging
import csv
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_IDS
from db import init_db, async_session, Account, Member, Package, Payment
from sqlalchemy import select
from parser import parse_members_text

# Advanced Logging Setup
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"bot_{datetime.now().strftime('%Y%m%d')}.log")

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler()

# States
class AddAccountState(StatesGroup):
    email = State()
    label = State()
    login_email = State()
    login_password = State()
    activated_at = State()
    cycle_end = State()
    seats = State()

class RegisterClient(StatesGroup):
    tg_id = State()
    email = State()
    name = State()

class PackageState(StatesGroup):
    name = State()
    price = State()

class PaymentFlow(StatesGroup):
    waiting_for_package = State()
    waiting_for_receipt = State()

class ImportState(StatesGroup):
    picking_account = State()
    pasting_text = State()

class AddMemberManual(StatesGroup):
    account_id = State()
    name = State()
    email = State()

# Utils
def get_days_left(dt):
    if not dt: return 0
    return (dt - datetime.utcnow()).days

def get_days_since(dt):
    if not dt: return 0
    return (datetime.utcnow() - dt).days

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# Keyboards
def main_menu_kb():
    kb = [
        [InlineKeyboardButton(text="📂 اکانت‌ها", callback_data="list_accounts")],
        [InlineKeyboardButton(text="📥 وارد کردن اعضا (Paste)", callback_data="import_start")],
        [InlineKeyboardButton(text="💎 مدیریت پکیج‌ها", callback_data="manage_packages")],
        [InlineKeyboardButton(text="💳 تایید فیش‌ها", callback_data="review_payments")],
        [InlineKeyboardButton(text="👤 ثبت کاربر", callback_data="register_client"),
         InlineKeyboardButton(text="⏳ انقضا", callback_data="expiry_status")],
        [InlineKeyboardButton(text="📤 خروجی CSV", callback_data="export_csv")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def user_main_kb():
    kb = [
        [InlineKeyboardButton(text="👤 اکانت من", callback_data="my_account")],
        [InlineKeyboardButton(text="🛍 خرید / تمدید", callback_data="buy_package")],
        [InlineKeyboardButton(text="📦 بسته‌ها", callback_data="view_packages")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_to_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="main_menu")]])

def payment_review_kb(pay_id):
    kb = [
        [InlineKeyboardButton(text="✅ تایید", callback_data=f"approve_{pay_id}"),
         InlineKeyboardButton(text="❌ رد", callback_data=f"reject_{pay_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

# Handlers
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    logger.info(f"User {user_id} started the bot")
    
    if is_admin(user_id):
        await message.answer("🚀 **پنل مدیریت GPT Admin**\n\nخوش آمدید قربان.", reply_markup=main_menu_kb(), parse_mode="Markdown")
    else:
        await message.answer("👋 **خوش آمدید**\n\nاز منو استفاده کنید:", reply_markup=user_main_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "main_menu")
async def back_main(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    logger.debug(f"User {user_id} returned to main menu")
    
    if is_admin(user_id):
        await callback.message.edit_text("🚀 **پنل مدیریت GPT Admin**", reply_markup=main_menu_kb())
    else:
        await callback.message.edit_text("👋 **منوی اصلی**", reply_markup=user_main_kb())
    await callback.answer()

@dp.callback_query(F.data == "list_accounts")
async def list_accounts(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        logger.warning(f"Unauthorized access attempt by {callback.from_user.id}")
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
    logger.info(f"Admin {callback.from_user.id} viewing accounts list")
    async with async_session() as session:
        accounts = (await session.execute(select(Account))).scalars().all()
    
    if not accounts:
        await callback.message.edit_text("📭 هیچ اکانتی ثبت نشده است.", reply_markup=back_to_main_kb())
    else:
        kb = []
        for acc in accounts:
            kb.append([InlineKeyboardButton(text=f"👑 {acc.account_label or acc.owner_email[:20]}", callback_data=f"view_acc_{acc.id}")])
        kb.append([InlineKeyboardButton(text="➕ افزودن اکانت", callback_data="add_account_new")])
        kb.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="main_menu")])
        await callback.message.edit_text("📂 **لیست اکانت‌ها:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("view_acc_"))
async def view_account(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
    acc_id = int(callback.data.split("_")[2])
    logger.info(f"Admin viewing account {acc_id}")
    
    async with async_session() as session:
        acc = await session.get(Account, acc_id)
        members_count = len((await session.execute(select(Member).where(Member.account_id == acc_id))).scalars().all())
    
    if not acc:
        await callback.answer("❌ اکانت یافت نشد", show_alert=True)
        return
    
    left = get_days_left(acc.cycle_end)
    text = (
        f"👑 **{acc.account_label}**\n\n"
        f"📧 ایمیل مالک: `{acc.owner_email}`\n"
        f"🔑 لاگین: `{acc.login_email or 'ندارد'}`\n"
        f"🔐 پسورد: `{acc.login_password or 'ندارد'}`\n\n"
        f"⏳ انقضا: {acc.cycle_end.strftime('%Y-%m-%d') if acc.cycle_end else 'نامشخص'} ({left} روز)\n"
        f"💺 ظرفیت: {acc.seats_total}\n"
        f"👥 اعضای ثبت شده: {members_count}"
    )
    
    kb = [
        [InlineKeyboardButton(text="👥 لیست اعضا", callback_data=f"members_{acc_id}"),
         InlineKeyboardButton(text="➕ افزودن عضو", callback_data=f"add_member_{acc_id}")],
        [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="list_accounts")]
    ]
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("members_"))
async def list_members(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
    acc_id = int(callback.data.split("_")[1])
    logger.info(f"Admin viewing members of account {acc_id}")
    
    async with async_session() as session:
        members = (await session.execute(select(Member).where(Member.account_id == acc_id))).scalars().all()
    
    if not members:
        await callback.message.edit_text("📭 هیچ عضوی ثبت نشده.", reply_markup=back_to_main_kb())
    else:
        text = f"👥 **اعضای اکانت:**\n\n"
        for m in members:
            days = get_days_since(m.date_added)
            text += f"• {m.name} - {m.email}\n  📅 {days} روز پیش\n\n"
        
        await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "add_account_new")
async def add_account_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
    logger.info(f"Admin {callback.from_user.id} starting to add new account")
    await callback.message.edit_text("📧 ایمیل مالک اکانت را وارد کنید:")
    await state.set_state(AddAccountState.email)
    await callback.answer()

@dp.message(AddAccountState.email)
async def add_acc_label(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(email=message.text)
    await message.answer("🏷 برچسب اکانت (مثلا GPT-01):")
    await state.set_state(AddAccountState.label)

@dp.message(AddAccountState.label)
async def add_acc_login_email(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(label=message.text)
    await message.answer("🔑 ایمیل لاگین ChatGPT:")
    await state.set_state(AddAccountState.login_email)

@dp.message(AddAccountState.login_email)
async def add_acc_login_pass(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(login_email=message.text)
    await message.answer("🔐 پسورد لاگین:")
    await state.set_state(AddAccountState.login_password)

@dp.message(AddAccountState.login_password)
async def add_acc_activated(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(login_password=message.text)
    await message.answer("📅 تاریخ فعال‌سازی (YYYY-MM-DD):")
    await state.set_state(AddAccountState.activated_at)

@dp.message(AddAccountState.activated_at)
async def add_acc_cycle(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        dt = datetime.strptime(message.text, "%Y-%m-%d")
        await state.update_data(activated_at=dt)
        await message.answer("⏳ تاریخ انقضا (YYYY-MM-DD):")
        await state.set_state(AddAccountState.cycle_end)
    except:
        await message.answer("❌ فرمت اشتباه. مثال: 2025-01-15")

@dp.message(AddAccountState.cycle_end)
async def add_acc_seats(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        dt = datetime.strptime(message.text, "%Y-%m-%d")
        await state.update_data(cycle_end=dt)
        await message.answer("💺 تعداد کل صندلی‌ها:")
        await state.set_state(AddAccountState.seats)
    except:
        await message.answer("❌ فرمت اشتباه. مثال: 2025-02-15")

@dp.message(AddAccountState.seats)
async def add_acc_finish(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    logger.info(f"Admin {message.from_user.id} creating account: {data['label']}")
    
    async with async_session() as session:
        acc = Account(
            owner_email=data['email'],
            account_label=data['label'],
            login_email=data['login_email'],
            login_password=data['login_password'],
            activated_at=data['activated_at'],
            cycle_end=data['cycle_end'],
            seats_total=int(message.text)
        )
        session.add(acc)
        await session.commit()
    
    await message.answer("✅ اکانت با موفقیت ثبت شد.", reply_markup=main_menu_kb())
    await state.clear()

# Import Members (Bulk)
@dp.callback_query(F.data == "import_start")
async def import_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
    logger.info(f"Admin {callback.from_user.id} starting bulk import")
    async with async_session() as session:
        accounts = (await session.execute(select(Account))).scalars().all()
    
    if not accounts:
        await callback.message.edit_text("❌ ابتدا یک اکانت ایجاد کنید.", reply_markup=back_to_main_kb())
        await callback.answer()
        return
    
    kb = []
    for acc in accounts:
        kb.append([InlineKeyboardButton(text=f"{acc.account_label}", callback_data=f"import_to_{acc.id}")])
    kb.append([InlineKeyboardButton(text="⬅️ انصراف", callback_data="main_menu")])
    
    await callback.message.edit_text("📥 **اکانت مقصد را انتخاب کنید:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("import_to_"))
async def import_select_account(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
    acc_id = int(callback.data.split("_")[2])
    await state.update_data(target_account=acc_id)
    await state.set_state(ImportState.pasting_text)
    
    await callback.message.edit_text(
        "📋 **حالا متن اعضا را کپی و پیست کنید:**\n\n"
        "مثال:\n"
        "John Doe - john@example.com - Member - Added 2 days ago"
    )
    await callback.answer()

@dp.message(ImportState.pasting_text)
async def import_process_text(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    acc_id = data['target_account']
    
    logger.info(f"Admin {message.from_user.id} importing members to account {acc_id}")
    
    try:
        members_data = parse_members_text(message.text)
        
        async with async_session() as session:
            for m_data in members_data:
                member = Member(
                    account_id=acc_id,
                    name=m_data.get('name', 'Unknown'),
                    email=m_data.get('email'),
                    role=m_data.get('role', 'Member'),
                    date_added=m_data.get('date_added', datetime.utcnow()),
                    status="Active"
                )
                session.add(member)
            await session.commit()
        
        await message.answer(f"✅ {len(members_data)} عضو با موفقیت وارد شدند.", reply_markup=main_menu_kb())
        logger.info(f"Successfully imported {len(members_data)} members")
    except Exception as e:
        logger.error(f"Import failed: {e}")
        await message.answer(f"❌ خطا در پردازش: {str(e)}", reply_markup=main_menu_kb())
    
    await state.clear()

# Export CSV
@dp.callback_query(F.data == "export_csv")
async def export_csv(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
    logger.info(f"Admin {callback.from_user.id} exporting CSV")
    
    async with async_session() as session:
        accounts = (await session.execute(select(Account))).scalars().all()
        members = (await session.execute(select(Member))).scalars().all()
    
    csv_file = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['Account', 'Member Name', 'Email', 'Role', 'Status', 'Date Added'])
        
        for m in members:
            acc = next((a for a in accounts if a.id == m.account_id), None)
            acc_label = acc.account_label if acc else 'N/A'
            writer.writerow([acc_label, m.name, m.email, m.role, m.status, m.date_added.strftime('%Y-%m-%d')])
    
    await callback.message.answer_document(FSInputFile(csv_file), caption="📊 خروجی CSV")
    os.remove(csv_file)
    await callback.answer()

@dp.callback_query(F.data == "expiry_status")
async def expiry_status(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
    async with async_session() as session:
        accounts = (await session.execute(select(Account).order_by(Account.cycle_end))).scalars().all()
    
    text = "⏳ **وضعیت انقضا:**\n\n"
    for acc in accounts:
        left = get_days_left(acc.cycle_end)
        icon = "🟢" if left > 7 else "🟡" if left > 0 else "🔴"
        text += f"{icon} {acc.account_label}: {left} روز\n"
    
    await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "manage_packages")
async def manage_packages(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
    async with async_session() as session:
        pkgs = (await session.execute(select(Package))).scalars().all()
    
    kb = []
    for pkg in pkgs:
        kb.append([InlineKeyboardButton(text=f"{pkg.name} - {pkg.price}", callback_data=f"pkg_{pkg.id}")])
    kb.append([InlineKeyboardButton(text="➕ افزودن پکیج", callback_data="add_pkg")])
    kb.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="main_menu")])
    
    await callback.message.edit_text("💎 **مدیریت پکیج‌ها:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data == "review_payments")
async def review_payments(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
    async with async_session() as session:
        payments = (await session.execute(select(Payment).where(Payment.status == "Pending"))).scalars().all()
    
    if not payments:
        await callback.message.edit_text("✅ فیشی در انتظار نیست.", reply_markup=back_to_main_kb())
    else:
        await callback.message.edit_text(f"⏳ {len(payments)} فیش در انتظار بررسی...")
        for pay in payments:
            await bot.send_photo(
                callback.from_user.id,
                pay.receipt_photo_id,
                caption=f"📝 فیش #{pay.id}\n👤 کاربر: {pay.user_id}",
                reply_markup=payment_review_kb(pay.id)
            )
    await callback.answer()

# User handlers
@dp.callback_query(F.data == "my_account")
async def my_account(callback: types.CallbackQuery):
    async with async_session() as session:
        stmt = select(Member).where(Member.telegram_id == callback.from_user.id)
        member = (await session.execute(stmt)).scalar()
        
        if member and member.account_id:
            acc = await session.get(Account, member.account_id)
        else:
            acc = None
    
    if not member or not acc:
        await callback.message.edit_text("❌ شما اشتراک فعالی ندارید.", reply_markup=user_main_kb())
    else:
        left = get_days_left(acc.cycle_end)
        text = f"👤 **اکانت شما:**\n\n📧 {member.email}\n⏳ {left} روز باقی‌مانده"
        await callback.message.edit_text(text, reply_markup=user_main_kb(), parse_mode="Markdown")
    await callback.answer()

async def send_daily_report():
    logger.info("Sending daily report")
    async with async_session() as session:
        accs = (await session.execute(select(Account))).scalars().all()
        pending = (await session.execute(select(Payment).where(Payment.status == "Pending"))).scalars().all()
    
    report = f"📊 **گزارش روزانه**\n📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"
    report += f"📁 کل اکانت‌ها: {len(accs)}\n"
    report += f"💳 فیش‌های منتظر: {len(pending)}\n"
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, report, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send report to {admin_id}: {e}")

async def check_reminders():
    logger.info("Checking expiry reminders")
    async with async_session() as session:
        accs = (await session.execute(select(Account))).scalars().all()
    
    for acc in accs:
        left = get_days_left(acc.cycle_end)
        if left in [7, 3, 1]:
            msg = f"⚠️ **هشدار انقضا!**\nاکانت `{acc.account_label}` فقط {left} روز باقی مانده."
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, msg, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Failed to send reminder to {admin_id}: {e}")

def setup_scheduler():
    scheduler.add_job(send_daily_report, 'cron', hour=9, minute=0)
    scheduler.add_job(check_reminders, 'interval', hours=12)
    scheduler.start()
    logger.info("Scheduler started")

async def main():
    await init_db()
    setup_scheduler()
    logger.info("✅ Bot started successfully!")
    print("✅ Bot started successfully! Logs: " + log_file)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
