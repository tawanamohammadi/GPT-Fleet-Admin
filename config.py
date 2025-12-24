import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

# Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Admin IDs (comma separated string in .env converted to list of ints)
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "").split(",") if i.strip()]

# Database URL
DB_URL = "sqlite+aiosqlite:///gpt_admin.db"

# Encryption Key (Fernet)
# If not provided in .env, generate one (but it should be stored in .env for production persistence)
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = Fernet.generate_key().decode()
    # In a real scenario, you'd write this back to .env if missing
    
fernet = Fernet(SECRET_KEY.encode())

def encrypt_data(data: str) -> str:
    if not data: return ""
    return fernet.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    if not encrypted_data: return ""
    return fernet.decrypt(encrypted_data.encode()).decode()

# UI Settings
TIMEZONE_OFFSET = 3.5 # For Iran (Optional if server local is enough)
