import os

def setup():
    print("--- 🚀 GPT Admin Bot Setup Wizard ---")
    token = input("1. Please enter your Telegram Bot Token (from @BotFather): ").strip()
    admin_id = input("2. Please enter your Numeric Telegram ID (e.g. 12345678): ").strip()
    
    env_content = f"BOT_TOKEN={token}\nADMIN_IDS={admin_id}\n"
    
    with open(".env", "w") as f:
        f.write(env_content)
    
    print("\n✅ Configuration saved to .env file!")
    print("Now you can run the bot using: python bot.py")

if __name__ == "__main__":
    setup()
