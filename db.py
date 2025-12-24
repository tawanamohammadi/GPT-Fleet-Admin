from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Float, select, update, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from config import DB_URL

Base = declarative_base()

class Account(Base):
    __tablename__ = 'accounts'
    id = Column(Integer, primary_key=True)
    service_name = Column(String, default="ChatGPT Business")
    account_label = Column(String)
    owner_email = Column(String, unique=True, index=True)
    login_email = Column(String, nullable=True) # Actual GPT login
    login_password = Column(String, nullable=True) # Actual GPT pass
    billing_email = Column(String, nullable=True)
    activated_at = Column(DateTime, default=datetime.utcnow)
    cycle_start = Column(DateTime, nullable=True)
    cycle_end = Column(DateTime, nullable=True)
    seats_total = Column(Integer, default=0)
    status = Column(String, default="active") # active/expired
    notes = Column(Text, nullable=True)
    
    members = relationship("Member", back_populates="account", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="account", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="account")

class Member(Base):
    __tablename__ = 'members'
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=True)
    name = Column(String)
    email = Column(String, index=True, nullable=True)
    role = Column(String, default="Member") # Owner/Member/User
    status = Column(String, default="Active") # Active/Expired/Pending
    date_added = Column(DateTime, default=datetime.utcnow)
    expiry_date = Column(DateTime, nullable=True)
    telegram_id = Column(Integer, unique=True, index=True)
    phone = Column(String, nullable=True)
    active = Column(Boolean, default=True)

    account = relationship("Account", back_populates="members")

class Package(Base):
    __tablename__ = 'packages'
    id = Column(Integer, primary_key=True)
    name = Column(String) # e.g. 1 Month GPT
    price = Column(String) # e.g. 500,000 Toman
    description = Column(Text)

class Payment(Base):
    __tablename__ = 'payments'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer) # Telegram ID
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=True)
    package_id = Column(Integer, ForeignKey('packages.id'))
    amount = Column(String)
    receipt_photo_id = Column(String)
    status = Column(String, default="Pending") # Pending/Approved/Rejected
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", back_populates="payments")

class Invoice(Base):
    __tablename__ = 'invoices'
    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey('accounts.id'))
    invoice_number = Column(String)
    invoice_date = Column(DateTime)
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    subtotal = Column(Float)
    discount = Column(Float, default=0)
    total_due = Column(Float)
    paid_amount = Column(Float)
    payment_status = Column(String)

    account = relationship("Account", back_populates="invoices")

engine = create_async_engine(DB_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
