from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, Float
from pydantic import BaseModel
from typing import List, Optional
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler

# Importy naszych modułów
from database import SessionLocal, engine, Base
from scraper import get_price
from notifier import send_discord_notification


# ---------------------------------------------------------
# 1. MODELE BAZY DANYCH (SQLAlchemy)
# ---------------------------------------------------------
class ProductDB(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, index=True)
    target_price = Column(Float)
    current_price = Column(Float, nullable=True)


# Tworzymy tabele w pliku tracker.db przy starcie
Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------
# 2. SCHEMATY DANYCH API (Pydantic v2)
# ---------------------------------------------------------
class ProductCreate(BaseModel):
    url: str
    target_price: float


class ProductResponse(BaseModel):
    id: int
    url: str
    target_price: float
    current_price: Optional[float] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------
# 3. LOGIKA SCHEDULERA (Zadanie w tle)
# ---------------------------------------------------------
def update_all_prices():
    """Funkcja budząca się co określony czas, by sprawdzić ceny."""
    print("\n" + "=" * 50)
    print("[Scheduler] ROZPOCZYNAM CYKLICZNE SPRAWDZANIE CEN...")
    print("=" * 50)

    db = SessionLocal()
    try:
        products = db.query(ProductDB).all()

        if not products:
            print("[Scheduler] Brak produktów w bazie do sprawdzenia.")
            return

        for product in products:
            print(f"[Scheduler] Sprawdzam: {product.url}")
            new_price = get_price(product.url)

            if new_price is not None:
                # LOGIKA POWIADOMIEŃ:
                # Jeśli nowa cena jest niższa lub równa docelowej...
                if new_price <= product.target_price:
                    # ...i jest niższa niż to co mieliśmy zapisane (żeby nie spamować co minutę tą samą ceną)
                    if product.current_price is None or new_price < product.current_price:
                        print(f"[Scheduler] ALERT! Cena spadła dla ID {product.id}. Wysyłam Discorda...")
                        send_discord_notification(product.url, new_price, product.target_price)

                # Aktualizacja bazy danych
                product.current_price = new_price
                db.commit()
                print(f"[Scheduler] Sukces! Nowa cena dla ID {product.id}: {new_price} PLN")
            else:
                print(
                    f"[Scheduler] Nie udało się pobrać ceny dla ID {product.id} (Sklep zablokował bota lub zmienił layout)")

        print("=" * 50)
        print("[Scheduler] ZAKOŃCZONO CYKL SPRAWDZANIA.\n")
    except Exception as e:
        print(f"[Scheduler] BŁĄD KRYTYCZNY: {e}")
    finally:
        db.close()


# ---------------------------------------------------------
# 4. CYKL ŻYCIA APLIKACJI (Lifespan)
# ---------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Kod tutaj wykonuje się raz przy starcie apki
    scheduler = BackgroundScheduler()

    # Zadanie ustawione na 1 minutę do celów testowych.
    # Dla bezpieczeństwa (żeby nie dostać bana) zmień potem na hours=6 lub hours=12
    scheduler.add_job(update_all_prices, trigger="interval", hours=1)

    scheduler.start()
    print(">>> Harmonogram zadań aktywny (co 1 h) <<<")

    yield  # Tutaj aplikacja "żyje"

    # Kod tutaj wykonuje się przy zamykaniu apki (Ctrl+C)
    scheduler.shutdown()
    print(">>> Harmonogram zadań wyłączony <<<")


# ---------------------------------------------------------
# 5. INICJALIZACJA I ENDPOINTY API
# ---------------------------------------------------------
app = FastAPI(
    title="Price Tracker Bot",
    description="Aplikacja śledząca ceny z powiadomieniami na Discord",
    lifespan=lifespan
)


# Pomocnicza funkcja do bazy danych
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", tags=["General"])
def read_root():
    return {"status": "online", "message": "Bot pracuje w tle. Przejdź do /docs aby zarządzać produktami."}


@app.post("/products", response_model=ProductResponse, tags=["Products"])
def add_product(product: ProductCreate, db: Session = Depends(get_db)):
    """Dodaje nowy produkt i od razu próbuje pobrać jego cenę."""
    print(f"[API] Dodaję nowy produkt: {product.url}")

    # Sprawdzamy cenę od razu przy dodawaniu
    initial_price = get_price(product.url)

    new_product = ProductDB(
        url=product.url,
        target_price=product.target_price,
        current_price=initial_price
    )

    db.add(new_product)
    db.commit()
    db.refresh(new_product)

    # Jeśli od razu przy dodaniu cena jest niska, wyślij powiadomienie
    if initial_price and initial_price <= product.target_price:
        send_discord_notification(product.url, initial_price, product.target_price)

    return new_product


@app.get("/products", response_model=List[ProductResponse], tags=["Products"])
def list_products(db: Session = Depends(get_db)):
    """Zwraca listę wszystkich śledzonych produktów."""
    return db.query(ProductDB).all()


@app.delete("/products/{product_id}", tags=["Products"])
def delete_product(product_id: int, db: Session = Depends(get_db)):
    """Usuwa produkt z bazy danych."""
    db_product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Produkt nie istnieje")
    db.delete(db_product)
    db.commit()
    return {"message": f"Produkt o ID {product_id} został usunięty."}