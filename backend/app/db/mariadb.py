import logging
import json
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, JSON, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func
from app.utils.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()

class DocumentExtraction(Base):
    __tablename__ = "document_extractions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_type = Column(String(255), nullable=True)
    document_tittle = Column(String(255), nullable=True)  # Kept spelling from user request
    chapter_number = Column(Integer, nullable=True)
    standard = Column(Integer, nullable=True)
    subject_name = Column(String(255), nullable=True)
    board = Column(String(255), nullable=True)
    syear = Column(String(255), nullable=True)
    pdf_url = Column(Text, nullable=True)
    
    # Text contents (using Text/LONGTEXT since they can be large)
    md_content = Column(Text, nullable=True)
    json_content = Column(JSON, nullable=True)
    
    page_count = Column(Integer, nullable=True)
    image_extracted = Column(Integer, nullable=True)
    
    # JSON for metadata
    extraction_metadata = Column(JSON, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

# Create engine and session
# Default to empty string if not provided so sqlalchemy doesn't break
MARIADB_URL = f"mysql+pymysql://{settings.mariadb_user}:{settings.mariadb_password}@{settings.mariadb_host}:{settings.mariadb_port}/{settings.mariadb_db}"

engine = None
SessionLocal = None

try:
    engine = create_engine(MARIADB_URL, pool_recycle=3600)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    # Automatically create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    logger.info("Successfully connected to MariaDB and verified tables.")
except Exception as e:
    logger.warning(f"Could not connect to MariaDB: {e}")

def get_db():
    if not SessionLocal:
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
