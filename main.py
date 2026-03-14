from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, Float
from pydantic import BaseModel
from typing import List, Optional
from scraper import get_price

# Importujemy rzeczy z naszego nowego pliku database.py
from database import SessionLocal, engine, Base


# ----------------------------------------
# MODELE BAZY DANYCH (SQLAlchemy)
# Mówią jak wyglądają tabele w pliku SQLite
# ----------------------------------------
class ProductDB(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, index=True)
    target_price = Column(Float)
    current_price = Column(Float, nullable=True)


# Tworzymy tabele w bazie danych (jeśli jeszcze nie istnieją)
Base.metadata.create_all(bind=engine)


# ----------------------------------------
# MODELE DANYCH API (Pydantic)
# Mówią jak wyglądają JSONy wysyłane i odbierane przez użytkownika
# ----------------------------------------
class ProductCreate(BaseModel):
    url: str
    target_price: float


class ProductResponse(BaseModel):
    id: int
    url: str
    target_price: float
    current_price: Optional[float] = None

    class Config:
        orm_mode = True  # Pozwala FastAPI czytać dane prosto z bazy


# ----------------------------------------
# APLIKACJA I ENDPOINTY
# ----------------------------------------
app = FastAPI(title="Price Tracker API z Bazą")


# Zależność (Dependency): otwiera połączenie z bazą na czas żądania i zamyka po nim
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def read_root():
    return {"message": "Baza danych podłączona! Sprawdź /docs"}


# Zauważ parametr `db: Session = Depends(get_db)`. FastAPI samo poda nam tu sesję bazy!
@app.post("/products", response_model=ProductResponse)
@app.post("/products", response_model=ProductResponse)
def add_product(product: ProductCreate, db: Session = Depends(get_db)):
    # Używamy naszego scrapera do pobrania ceny!
    fetched_price = get_price(product.url)

    new_product = ProductDB(
        url=product.url,
        target_price=product.target_price,
        current_price=fetched_price  # Zapisujemy pobraną cenę
    )

    db.add(new_product)
    db.commit()
    db.refresh(new_product)

    return new_product


@app.get("/products", response_model=List[ProductResponse])
def get_all_products(db: Session = Depends(get_db)):
    # Pobieramy wszystkie produkty z tabeli
    products = db.query(ProductDB).all()
    return products