from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, Float
from pydantic import BaseModel
from typing import List, Optional
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta

from starlette.responses import FileResponse

# Importy Twoich zewnętrznych modułów
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


# Tworzymy tabele w bazie przy starcie
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
async def update_all_prices():
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
            new_price = await get_price(product.url)

            if new_price is not None:
                # LOGIKA POWIADOMIEŃ
                if new_price <= product.target_price:
                    if product.current_price is None or new_price < product.current_price:
                        print(f"[Scheduler] ALERT! Cena spadła dla ID {product.id}. Wysyłam Discorda...")
                        send_discord_notification(product.url, new_price, product.target_price)

                # Aktualizacja bazy danych
                product.current_price = new_price
                db.commit()
                print(f"[Scheduler] Sukces! Nowa cena dla ID {product.id}: {new_price} PLN")
            else:
                print(f"[Scheduler] Nie udało się pobrać ceny dla ID {product.id}")

        print("=" * 50)
        print("[Scheduler] ZAKOŃCZONO CYKL SPRAWDZANIA.\n")
    except Exception as e:
        print(f"[Scheduler] BŁĄD KRYTYCZNY: {e}")
    finally:
        db.close()


# ---------------------------------------------------------
# 4. CYKL ŻYCIA APLIKACJI I SCHEDULER
# ---------------------------------------------------------
# Globalna instancja schedulera
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Nadajemy zadaniu konkretne ID: "sync_job"
    scheduler.add_job(update_all_prices, trigger="interval", hours=1, id="sync_job")
    scheduler.start()
    print(">>> Harmonogram zadań aktywny (co 1 h) <<<")

    yield  # Tutaj aplikacja "żyje" i odbiera żądania API

    scheduler.shutdown()
    print(">>> Harmonogram zadań wyłączony <<<")


# ---------------------------------------------------------
# 5. INICJALIZACJA APLIKACJI I CORS
# ---------------------------------------------------------
app = FastAPI(
    title="Price Tracker Bot",
    description="Aplikacja śledząca ceny z powiadomieniami na Discord",
    lifespan=lifespan
)

# CORS - Zezwala frontendowi (nawet z pliku lokalnego) na odpytywanie API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pomocnicza funkcja dla wstrzykiwania bazy danych
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------
# 6. ENDPOINTY API (Produkty)
# ---------------------------------------------------------
@app.get("/", tags=["General"])
def read_root():
    return FileResponse("./index.html")

@app.post("/products", response_model=ProductResponse, tags=["Products"])
async def add_product(product: ProductCreate, db: Session = Depends(get_db)):
    print(f"[API] Dodaję nowy produkt: {product.url}")

    initial_price = await get_price(product.url)

    new_product = ProductDB(
        url=product.url,
        target_price=product.target_price,
        current_price=initial_price
    )

    db.add(new_product)
    db.commit()
    db.refresh(new_product)

    if initial_price and initial_price <= product.target_price:
        send_discord_notification(product.url, initial_price, product.target_price)

    return new_product


@app.get("/products", response_model=List[ProductResponse], tags=["Products"])
def list_products(db: Session = Depends(get_db)):
    return db.query(ProductDB).all()


@app.delete("/products/{product_id}", tags=["Products"])
def delete_product(product_id: int, db: Session = Depends(get_db)):
    db_product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Produkt nie istnieje")
    db.delete(db_product)
    db.commit()
    return {"message": f"Produkt o ID {product_id} został usunięty."}


# ---------------------------------------------------------
# 7. ENDPOINTY SYSTEMOWE (Odliczanie i ręczne skanowanie)
# ---------------------------------------------------------
@app.get("/system/status", tags=["System"])
def get_system_status():
    """Zwraca dokładną datę i czas kolejnego uruchomienia schedulera."""
    job = scheduler.get_job("sync_job")
    if job and job.next_run_time:
        return {"next_run_time": job.next_run_time.isoformat()}
    return {"next_run_time": None}


@app.post("/system/scrape-now", tags=["System"])
def trigger_scrape_now(background_tasks: BackgroundTasks):
    """
    Ręcznie wymusza proces sprawdzania cen w tle.
    Resetuje harmonogram schedulera, żeby nie dublować skanowań.
    """
    # 1. Dodajemy skanowanie w tle
    background_tasks.add_task(update_all_prices)

    # 2. Przesuwamy czas następnego skanowania na za 1h
    job = scheduler.get_job("sync_job")
    if job and job.next_run_time:
        next_run = datetime.now(job.next_run_time.tzinfo) + timedelta(hours=1)
        # TUTAJ JEST ZMIANA: używamy modify_job zamiast reschedule_job
        scheduler.modify_job("sync_job", next_run_time=next_run)

    return {"message": "Rozpoczęto ręczne sprawdzanie cen w tle."}