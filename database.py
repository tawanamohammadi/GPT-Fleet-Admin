from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
from config import DB_URL

Base = declarative_base()

class Account(Base):
    __tablename__ = "accounts"
    
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=True)
    workspace_name = Column(String, nullable=True)
    expiry_date = Column(DateTime, nullable=True)
    members_count = Column(Integer, default=0)
    status = Column(String, default="Active") # Active, Expired, Suspended
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

engine = create_async_engine(DB_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
