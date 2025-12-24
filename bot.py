import asyncio
import logging
import csv
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_IDS
from db import init_db, async_session, Account, Member, Invoice, Package, Payment
from sqlalchemy import select, update, delete, or_
import keyboards as kb
from parser import parse_members_text

# Logging
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# --- Access Control ---
class IsAdmin(BaseFilter):
    async def __call__(self, message: types.Message) -> bool:
        return message.from_user.id in ADMIN_IDS

# --- States ---
class AddAccountState(StatesGroup):
    label = State()
    email = State()
    login_email = State()
    login_password = State()
    activated_at = State()
    cycle_end = State()
    seats = State()

class RegisterClient(StatesGroup):
    tg_id = State()
    email = State()
    name = State()

class ImportState(StatesGroup):
    picking_account = State()
    pasting_text = State()

class SearchState(StatesGroup):
    waiting_for_query = State()

class PaymentFlow(StatesGroup):
    waiting_for_package = State()
    waiting_for_receipt = State()

class PackageState(StatesGroup):
    name = State()
    price = State()
    desc = State()

# --- Utils ---
def get_days_since(dt):
    if not dt: return 0
    return (datetime.utcnow() - dt).days

def get_days_left(dt):
    if not dt: return 0
    return (dt - datetime.utcnow()).days

# --- Handlers: Start ---

@dp.message(Command("start"))
@dp.callback_query(F.data == "user_main")
async def cmd_start(event: types.Message | types.CallbackQuery):
    user_id = event.from_user.id
    if user_id in ADMIN_IDS:
        text = "🚀 **پنل مدیریت پیشرفته GPT Admin**\n\nخوش آمدید قربان. وضعیت سیستم در حالت عادی است."
        reply_markup = kb.main_menu()
    else:
        text = "👋 **به ربات خرید اشتراک ChatGPT خوش آمدید**\n\nاز منوی زیر برای خرید یا مدیریت اشتراک خود استفاده کنید:"
        reply_markup = kb.user_main_menu()
    
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await event.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in ADMIN_IDS:
        text = "🚀 **پنل مدیریت پیشرفته GPT Admin**\n\nخوش آمدید قربان. وضعیت سیستم در حالت عادی است."
        reply_markup = kb.main_menu()
    else:
        text = "👋 **به ربات خرید اشتراک ChatGPT خوش آمدید**\n\nاز منوی زیر برای خرید یا مدیریت اشتراک خود استفاده کنید:"
        reply_markup = kb.user_main_menu()
    await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    await callback.answer()

# --- Handlers: User Flow ---

@dp.callback_query(F.data == "view_packages")
async def user_view_packages(callback: types.CallbackQuery):
    async with async_session() as session:
        pkgs = (await session.execute(select(Package))).scalars().all()
    if not pkgs:
        await callback.message.edit_text("📭 فعلا پکیجی تعریف نشده است.", reply_markup=kb.user_main_menu())
    else:
        await callback.message.edit_text("🎁 **لیست بسته‌های موجود:**", reply_markup=kb.packages_kb(pkgs))

@dp.callback_query(F.data == "my_account")
async def user_my_account(callback: types.CallbackQuery):
    async with async_session() as session:
        stmt = select(Member, Account).join(Account, isouter=True).where(Member.telegram_id == callback.from_user.id)
        res = (await session.execute(stmt)).first()
    
    if not res:
        await callback.message.edit_text("❌ شما هنوز اشتراک فعالی ندارید.", reply_markup=kb.user_main_menu())
    else:
        m, acc = res
        left = get_days_left(acc.cycle_end) if acc else 0
        text = (
            f"👤 **وضعیت اشتراک شما:**\n\n"
            f"📧 ایمیل: `{m.email}`\n"
            f"🏢 ورک‌اسپیس: {acc.account_label if acc else 'تخصیص نیافته'}\n"
            f"⏳ زمان باقی‌مانده: {left} روز\n"
            f"📍 وضعیت: {m.status}"
        )
        await callback.message.edit_text(text, reply_markup=kb.user_main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "buy_package")
async def user_buy_start(callback: types.CallbackQuery, state: FSMContext):
    async with async_session() as session:
        pkgs = (await session.execute(select(Package))).scalars().all()
    await callback.message.edit_text("💳 لطفا پکیج مورد نظر را برای تمدید یا خرید انتخاب کنید:", reply_markup=kb.packages_kb(pkgs))
    await state.set_state(PaymentFlow.waiting_for_package)

@dp.callback_query(F.data.startswith("select_pkg_"), PaymentFlow.waiting_for_package)
async def user_pkg_selected(callback: types.CallbackQuery, state: FSMContext):
    pkg_id = int(callback.data.split("_")[2])
    await state.update_data(pkg_id=pkg_id)
    await callback.message.edit_text("📸 لطفا تصویر فیش واریزی خود را ارسال کنید.\n\n*شماره کارت:* `6037-xxxx-xxxx-xxxx` بنام تاوانا")
    await state.set_state(PaymentFlow.waiting_for_receipt)

@dp.message(PaymentFlow.waiting_for_receipt, F.photo)
async def user_receipt_sent(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id
    
    async with async_session() as session:
        pay = Payment(user_id=message.from_user.id, package_id=data['pkg_id'], receipt_photo_id=photo_id)
        session.add(pay)
        await session.commit()
        pay_id = pay.id

    await message.answer("✅ فیش شما دریافت شد و برای ادمین ارسال گردید. منتظر تایید باشید.")
    
    # Notify Admin
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(admin_id, photo_id, caption=f"🔔 **فیش جدید دریافت شد!**\nکاربر: {message.from_user.full_name}\nآیدی: {message.from_user.id}", 
                               reply_markup=kb.payment_review_kb(pay_id))
        except: pass
    await state.clear()

@dp.callback_query(F.data == "review_payments", IsAdmin())
async def admin_list_pending_payments(callback: types.CallbackQuery):
    async with async_session() as session:
        stmt = select(Payment).where(Payment.status == "Pending")
        payments = (await session.execute(stmt)).scalars().all()
    
    if not payments:
        await callback.message.edit_text("✅ هیچ فیش در انتظار تاییدی وجود ندارد.", reply_markup=kb.main_menu())
    else:
        await callback.message.edit_text(f"⏳ تعداد {len(payments)} فیش در انتظار بررسی است. در حال ارسال فیش‌ها...")
        for pay in payments:
            await bot.send_photo(
                callback.from_user.id, 
                pay.receipt_photo_id, 
                caption=f"📝 فیش ID: {pay.id}\n👤 کاربر: {pay.user_id}\n📅 تاریخ: {pay.created_at.strftime('%Y-%m-%d')}",
                reply_markup=kb.payment_review_kb(pay.id)
            )
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_approve_"), IsAdmin())
async def admin_approve_pay(callback: types.CallbackQuery):
    pay_id = int(callback.data.split("_")[2])
    async with async_session() as session:
        pay = await session.get(Payment, pay_id)
        # Notify user first
        await bot.send_message(pay.user_id, "🥳 **تبریک! فیش شما تایید شد.**\nادمین در حال تخصیص اکانت به شماست...")
        
        # Show accounts to admin for assignment
        accounts = (await session.execute(select(Account))).scalars().all()
        await session.commit()

    await callback.message.edit_caption(caption="✅ فیش تایید شد.\nحالا اکانت مقصد را انتخاب کنید:")
    
    builder = InlineKeyboardBuilder()
    for acc in accounts:
        builder.row(InlineKeyboardButton(text=f"📤 ارسال {acc.account_label}", callback_data=f"assign_{acc.id}_to_{pay_id}"))
    builder.row(InlineKeyboardButton(text="❌ انصراف", callback_data="main_menu"))
    
    await callback.message.answer("انتخاب اکانت برای ارسال مشخصات:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("assign_"), IsAdmin())
async def admin_assign_account(callback: types.CallbackQuery):
    _, acc_id, _, pay_id = callback.data.split("_")
    async with async_session() as session:
        acc = await session.get(Account, int(acc_id))
        pay = await session.get(Payment, int(pay_id))
        pay.status = "Approved"
        pay.account_id = acc.id
        
        # Send credentials to user
        msg = (
            f"✅ **مشخصات اکانت شما:**\n\n"
            f"📧 ایمیل: `{acc.login_email}`\n"
            f"🔑 پسورد: `{acc.login_password}`\n\n"
            f"🏢 ورک‌اسپیس: {acc.account_label}\n"
            f"⏳ انقضا: {acc.cycle_end.strftime('%Y-%m-%d')}"
        )
        await bot.send_message(pay.user_id, msg, parse_mode="Markdown")
        
        # Look for existing member or create
        stmt = select(Member).where(Member.telegram_id == pay.user_id)
        m = (await session.execute(stmt)).scalar()
        if m:
            m.account_id = acc.id
            m.status = "Active"
        else:
            m = Member(telegram_id=pay.user_id, account_id=acc.id, email=pay.user_id, status="Active")
            session.add(m)
        await session.commit()
        
    await callback.message.edit_text(f"🚀 مشخصات {acc.account_label} ارسال و کاربر تایید شد.")
    await callback.answer()

@dp.callback_query(F.data.startswith("pay_reject_"), IsAdmin())
async def admin_reject_pay(callback: types.CallbackQuery):
    pay_id = int(callback.data.split("_")[2])
    async with async_session() as session:
        pay = await session.get(Payment, pay_id)
        pay.status = "Rejected"
        await session.commit()
    
    await bot.send_message(pay.user_id, "❌ متاسفانه فیش ارسالی شما رد شد. لطفا در صورت نیاز با پشتیبانی تماس بگیرید.")
    await callback.message.edit_caption(caption="❌ فیش رد شد.")
    await callback.answer()

@dp.callback_query(F.data == "add_account_new", IsAdmin())
async def add_account_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📧 ایمیل مالک اکانت (Owner Email) را وارد کنید:")
    await state.set_state(AddAccountState.email)
    await callback.answer()

@dp.message(AddAccountState.email, IsAdmin())
async def add_acc_label(message: types.Message, state: FSMContext):
    await state.update_data(email=message.text)
    await message.answer("🏷 یک برچسب (Label) برای این اکانت انتخاب کنید (مثلا GPT-Biz-01):")
    await state.set_state(AddAccountState.label)

@dp.message(AddAccountState.label, IsAdmin())
async def add_acc_login_email(message: types.Message, state: FSMContext):
    await state.update_data(label=message.text)
    await message.answer("🔑 ایمیل لاگین (ChatGPT Login) را وارد کنید:")
    await state.set_state(AddAccountState.login_email)

@dp.message(AddAccountState.login_email, IsAdmin())
async def add_acc_login_pass(message: types.Message, state: FSMContext):
    await state.update_data(login_email=message.text)
    await message.answer("🔐 پسورد لاگین را وارد کنید:")
    await state.set_state(AddAccountState.login_password)

@dp.message(AddAccountState.login_password, IsAdmin())
async def add_acc_activated(message: types.Message, state: FSMContext):
    await state.update_data(login_password=message.text)
    await message.answer("📅 تاریخ فعال‌سازی (YYYY-MM-DD):")
    await state.set_state(AddAccountState.activated_at)

@dp.message(AddAccountState.activated_at, IsAdmin())
async def add_acc_cycle(message: types.Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text, "%Y-%m-%d")
        await state.update_data(activated_at=dt)
        await message.answer("⏳ تاریخ پایان انقضا (YYYY-MM-DD):")
        await state.set_state(AddAccountState.cycle_end)
    except:
        await message.answer("❌ فرمت اشتباه. (YYYY-MM-DD):")

@dp.message(AddAccountState.cycle_end, IsAdmin())
async def add_acc_seats(message: types.Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text, "%Y-%m-%d")
        await state.update_data(cycle_end=dt)
        await message.answer("💺 ظرفیت کل (Seats):")
        await state.set_state(AddAccountState.seats)
    except:
        await message.answer("❌ فرمت اشتباه. (YYYY-MM-DD):")

@dp.message(AddAccountState.seats, IsAdmin())
async def add_acc_finish(message: types.Message, state: FSMContext):
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
    await message.answer("✅ اکانت با تمام مشخصات ثبت شد.", reply_markup=kb.main_menu())
    await state.clear()

@dp.callback_query(F.data == "register_client", IsAdmin())
async def admin_reg_client_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🆔 آیدی عددی تلگرام کاربر را وارد کنید:")
    await state.set_state(RegisterClient.tg_id)
    await callback.answer()

@dp.message(RegisterClient.tg_id, IsAdmin())
async def admin_reg_client_email(message: types.Message, state: FSMContext):
    await state.update_data(tg_id=int(message.text))
    await message.answer("📧 ایمیل کاربر را وارد کنید:")
    await state.set_state(RegisterClient.email)

@dp.message(RegisterClient.email, IsAdmin())
async def admin_reg_client_name(message: types.Message, state: FSMContext):
    await state.update_data(email=message.text)
    await message.answer("👤 نام کاربر؟")
    await state.set_state(RegisterClient.name)

@dp.message(RegisterClient.name, IsAdmin())
async def admin_reg_client_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as session:
        m = Member(telegram_id=data['tg_id'], email=data['email'], name=message.text, status="Active")
        session.add(m)
        await session.commit()
    await message.answer("✅ کاربر با موفقیت ثبت شد و حالا می‌تواند از پنل استفاده کند.", reply_markup=kb.main_menu())
    await state.clear()

# --- Handlers: Admin Tasks & Reports ---

@dp.callback_query(F.data == "expiry_status", IsAdmin())
async def expiry_status(callback: types.CallbackQuery):
    async with async_session() as session:
        accounts = (await session.execute(select(Account).order_by(Account.cycle_end))).scalars().all()
    text = "⏳ **وضعیت انقضای کل اکانت‌ها:**\n"
    for acc in accounts:
        left = get_days_left(acc.cycle_end)
        icon = "🟢" if left > 7 else "🟡" if left > 0 else "🔴"
        text += f"{icon} {acc.account_label}: {left} روز\n"
    await callback.message.edit_text(text, reply_markup=kb.main_menu(), parse_mode="Markdown")

async def send_daily_report():
    async with async_session() as session:
        accs = (await session.execute(select(Account))).scalars().all()
        pending_pays = (await session.execute(select(Payment).where(Payment.status == "Pending"))).scalars().all()
    
    report = f"📊 **گزارش روزانه مدیریت GPT Admin**\n📅 {datetime.now().strftime('%Y-%m-%d')}\n\n"
    report += f"📁 کل ورک‌اسپیس‌ها: {len(accs)}\n"
    report += f"🕒 فیش‌های در انتظار: {len(pending_pays)}\n\n"
    
    report += "⏳ **وضعیت انقضاها:**\n"
    for acc in accs:
        left = get_days_left(acc.cycle_end)
        status = "✅" if left > 5 else "⚠️" if left > 0 else "🚫"
        report += f"{status} {acc.account_label}: {left} روز\n"
    
    for admin_id in ADMIN_IDS:
        try: await bot.send_message(admin_id, report, parse_mode="Markdown")
        except: pass

async def check_reminders():
    async with async_session() as session:
        accs = (await session.execute(select(Account))).scalars().all()
    for acc in accs:
        left = get_days_left(acc.cycle_end)
        if left in [7, 3, 1]:
            msg = f"⚠️ **هشدار انقضا!**\nاکانت `{acc.account_label}` فقط {left} روز تا پایان انقضا زمان دارد."
            for admin_id in ADMIN_IDS:
                try: await bot.send_message(admin_id, msg, parse_mode="Markdown")
                except: pass

# --- Handlers: Package Management ---
@dp.callback_query(F.data == "manage_packages", IsAdmin())
async def admin_manage_pkgs(callback: types.CallbackQuery):
    async with async_session() as session:
        pkgs = (await session.execute(select(Package))).scalars().all()
    await callback.message.edit_text("💎 **مدیریت پکیج‌ها:**", reply_markup=kb.packages_kb(pkgs, is_admin=True))

@dp.callback_query(F.data == "add_pkg_new", IsAdmin())
async def admin_add_pkg_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🏷 نام پکیج را وارد کنید (مثلا اکانت اختصاصی یک ماهه):")
    await state.set_state(PackageState.name)

@dp.message(PackageState.name, IsAdmin())
async def admin_add_pkg_price(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("💰 قیمت را وارد کنید (مثلا 500,000 تومان):")
    await state.set_state(PackageState.price)

@dp.message(PackageState.price, IsAdmin())
async def admin_add_pkg_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as session:
        pkg = Package(name=data['name'], price=message.text)
        session.add(pkg)
        await session.commit()
    await message.answer("✅ پکیج جدید با موفقیت اضافه شد.", reply_markup=kb.main_menu())
    await state.clear()

# --- Standard Admin Handlers (List, Import, etc.) - Simplified ---
@dp.callback_query(F.data == "list_accounts", IsAdmin())
async def list_accounts_handler(callback: types.CallbackQuery):
    async with async_session() as session:
        accounts = (await session.execute(select(Account))).scalars().all()
    await callback.message.edit_text("📂 **لیست اکانت‌ها:**", reply_markup=kb.accounts_list_kb(accounts))

@dp.callback_query(F.data.startswith("view_acc_"), IsAdmin())
async def view_acc_handler(callback: types.CallbackQuery):
    acc_id = int(callback.data.split("_")[2])
    async with async_session() as session:
        acc = await session.get(Account, acc_id)
        # Count members assigned via bot
        m_count = (await session.execute(select(Member).where(Member.account_id == acc.id))).scalars().all()
        
    left = get_days_left(acc.cycle_end)
    text = (
        f"👑 **جزئیات اکانت {acc.account_label}**\n\n"
        f"📧 ایمیل مالک: `{acc.owner_email}`\n"
        f"🔑 ایمیل لاگین: `{acc.login_email}`\n"
        f"🔐 پسورد لاگین: `{acc.login_password}`\n\n"
        f"⏳ انقضا: {acc.cycle_end.strftime('%Y-%m-%d')} ({left} روز مانده)\n"
        f"💺 ظرفیت کل: {acc.seats_total}\n"
        f"👥 اعضای ثبت شده در دیتابیس: {len(m_count)}\n"
    )
    await callback.message.edit_text(text, reply_markup=kb.account_detail_kb(acc_id), parse_mode="Markdown")
    await callback.answer()

# --- Scheduler setup ---
def setup_scheduler():
    scheduler.add_job(send_daily_report, 'cron', hour=9, minute=0) # Each morning at 9
    scheduler.add_job(check_reminders, 'interval', hours=12)
    scheduler.start()

async def main():
    await init_db()
    setup_scheduler()
    print("Bot & Scheduler started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
