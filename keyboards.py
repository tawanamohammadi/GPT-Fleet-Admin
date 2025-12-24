from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def main_menu():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📂 اکانت‌ها", callback_data="list_accounts"))
    builder.row(InlineKeyboardButton(text="📥 وارد کردن (Paste Text)", callback_data="import_start"))
    builder.row(InlineKeyboardButton(text="🔎 جستجو", callback_data="search_member"))
    builder.row(InlineKeyboardButton(text="⏳ وضعیت انقضا", callback_data="expiry_status"))
    builder.row(InlineKeyboardButton(text="💎 مدیریت پکیج‌ها", callback_data="manage_packages"))
    builder.row(InlineKeyboardButton(text="💳 تایید فیش‌ها", callback_data="review_payments"))
    builder.row(
        InlineKeyboardButton(text="⚙️ تنظیمات", callback_data="settings"),
        InlineKeyboardButton(text="👤 ثبت کاربر جدید", callback_data="register_client")
    )
    builder.row(InlineKeyboardButton(text="📤 خروجی CSV", callback_data="export_csv"))
    return builder.as_markup()

# --- User Keyboards ---
def user_main_menu():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="👤 اکانت من", callback_data="my_account"))
    builder.row(InlineKeyboardButton(text="🛍 خرید / تمدید اشتراک", callback_data="buy_package"))
    builder.row(InlineKeyboardButton(text="📦 مشاهده بسته‌ها", callback_data="view_packages"))
    builder.row(InlineKeyboardButton(text="📞 پشتیبانی", callback_data="user_support"))
    return builder.as_markup()

def packages_kb(packages, is_admin=False):
    builder = InlineKeyboardBuilder()
    for pkg in packages:
        callback = f"edit_pkg_{pkg.id}" if is_admin else f"select_pkg_{pkg.id}"
        builder.row(InlineKeyboardButton(text=f"{pkg.name} - {pkg.price}", callback_data=callback))
    if is_admin:
        builder.row(InlineKeyboardButton(text="➕ افزودن پکیج جدید", callback_data="add_pkg_new"))
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت", callback_data="main_menu" if is_admin else "user_main"))
    return builder.as_markup()

def payment_review_kb(payment_id):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ تایید و ارسال اکانت", callback_data=f"pay_approve_{payment_id}"),
        InlineKeyboardButton(text="❌ رد فیش", callback_data=f"pay_reject_{payment_id}")
    )
    return builder.as_markup()

# --- Common builders ---
def accounts_list_kb(accounts):
    builder = InlineKeyboardBuilder()
    for acc in accounts:
        btn_text = f"👑 {acc.owner_email[:15]}... — {acc.account_label or 'بدون نام'}"
        builder.row(InlineKeyboardButton(text=btn_text, callback_data=f"view_acc_{acc.id}"))
    builder.row(InlineKeyboardButton(text="➕ افزودن اکانت جدید", callback_data="add_account_new"))
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت", callback_data="main_menu"))
    return builder.as_markup()

def account_detail_kb(acc_id):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👥 لیست اعضا", callback_data=f"members_list_{acc_id}"),
        InlineKeyboardButton(text="⏳ انقضا", callback_data=f"acc_expiry_{acc_id}")
    )
    builder.row(
        InlineKeyboardButton(text="➕ افزودن عضو دستی", callback_data=f"add_member_manual_{acc_id}"),
        InlineKeyboardButton(text="⚙️ تنظیمات", callback_data=f"acc_settings_{acc_id}")
    )
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به لیست", callback_data="list_accounts"))
    return builder.as_markup()

def import_pick_account_kb(accounts):
    builder = InlineKeyboardBuilder()
    for acc in accounts:
        builder.row(InlineKeyboardButton(text=f"{acc.owner_email}", callback_data=f"import_to_{acc.id}"))
    builder.row(InlineKeyboardButton(text="🆕 اکانت جدید", callback_data="add_account_new"))
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت", callback_data="main_menu"))
    return builder.as_markup()
