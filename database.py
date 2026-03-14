from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Wskazujemy, że chcemy plik SQLite o nazwie "tracker.db"
SQLALCHEMY_DATABASE_URL = "sqlite:///./tracker.db"

# Tworzymy "silnik" bazy danych
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Sesja to nasze "okno" do bazy danych, przez które będziemy wysyłać zapytania
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Klasa bazowa, z której będą dziedziczyć nasze modele tabel
Base = declarative_base()