import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_IDS
from db import init_db, async_session, Account, Member, Package, Payment
from sqlalchemy import select

logging.basicConfig(level=logging.INFO)

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

# Utils
def get_days_left(dt):
    if not dt: return 0
    return (dt - datetime.utcnow()).days

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# Keyboards
def main_menu_kb():
    kb = [
        [InlineKeyboardButton(text="📂 اکانت‌ها", callback_data="list_accounts")],
        [InlineKeyboardButton(text="💎 مدیریت پکیج‌ها", callback_data="manage_packages")],
        [InlineKeyboardButton(text="💳 تایید فیش‌ها", callback_data="review_payments")],
        [InlineKeyboardButton(text="👤 ثبت کاربر جدید", callback_data="register_client")],
        [InlineKeyboardButton(text="⏳ وضعیت انقضا", callback_data="expiry_status")]
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

# Handlers
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if is_admin(user_id):
        await message.answer("🚀 **پنل مدیریت GPT Admin**\n\nخوش آمدید.", reply_markup=main_menu_kb(), parse_mode="Markdown")
    else:
        await message.answer("👋 **خوش آمدید**\n\nاز منو استفاده کنید:", reply_markup=user_main_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "main_menu")
async def back_main(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if is_admin(user_id):
        await callback.message.edit_text("🚀 **پنل مدیریت GPT Admin**", reply_markup=main_menu_kb())
    else:
        await callback.message.edit_text("👋 **منوی اصلی**", reply_markup=user_main_kb())
    await callback.answer()

@dp.callback_query(F.data == "list_accounts")
async def list_accounts(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
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
    async with async_session() as session:
        acc = await session.get(Account, acc_id)
    
    if not acc:
        await callback.answer("❌ اکانت یافت نشد", show_alert=True)
        return
    
    left = get_days_left(acc.cycle_end)
    text = (
        f"👑 **{acc.account_label}**\n\n"
        f"📧 ایمیل: `{acc.login_email or 'ندارد'}`\n"
        f"🔑 پسورد: `{acc.login_password or 'ندارد'}`\n"
        f"⏳ انقضا: {acc.cycle_end.strftime('%Y-%m-%d') if acc.cycle_end else 'نامشخص'} ({left} روز)\n"
        f"💺 ظرفیت: {acc.seats_total}"
    )
    await callback.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "add_account_new")
async def add_account_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی ندارید", show_alert=True)
        return
    
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
            kb = [
                [InlineKeyboardButton(text="✅ تایید", callback_data=f"approve_{pay.id}"),
                 InlineKeyboardButton(text="❌ رد", callback_data=f"reject_{pay.id}")]
            ]
            await bot.send_photo(
                callback.from_user.id,
                pay.receipt_photo_id,
                caption=f"📝 فیش #{pay.id}\n👤 کاربر: {pay.user_id}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
            )
    await callback.answer()

# User handlers
@dp.callback_query(F.data == "my_account")
async def my_account(callback: types.CallbackQuery):
    async with async_session() as session:
        stmt = select(Member).where(Member.telegram_id == callback.from_user.id)
        member = (await session.execute(stmt)).scalar()
    
    if not member or not member.account_id:
        await callback.message.edit_text("❌ شما اشتراک فعالی ندارید.", reply_markup=user_main_kb())
    else:
        acc = await session.get(Account, member.account_id)
        left = get_days_left(acc.cycle_end) if acc else 0
        text = f"👤 **اکانت شما:**\n\n📧 {member.email}\n⏳ {left} روز باقی‌مانده"
        await callback.message.edit_text(text, reply_markup=user_main_kb(), parse_mode="Markdown")
    await callback.answer()

async def send_daily_report():
    async with async_session() as session:
        accs = (await session.execute(select(Account))).scalars().all()
    
    report = f"📊 **گزارش روزانه**\n📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"
    report += f"📁 کل اکانت‌ها: {len(accs)}\n"
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, report, parse_mode="Markdown")
        except:
            pass

def setup_scheduler():
    scheduler.add_job(send_daily_report, 'cron', hour=9, minute=0)
    scheduler.start()

async def main():
    await init_db()
    setup_scheduler()
    print("✅ Bot started successfully!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
