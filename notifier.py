import requests

# TUTAJ WKLEJ SWÓJ SKOPIOWANY LINK Z DISCORDA:
DISCORD_WEBHOOK_URL = ""


def send_discord_notification(product_url: str, current_price: float, target_price: float):
    # Zostawiamy tylko sprawdzenie, czy zmienna w ogóle ma jakąś wartość
    if not DISCORD_WEBHOOK_URL or "api/webhooks" not in DISCORD_WEBHOOK_URL:
        print("[Notifier] Brak poprawnego URL webhooka! Nie mogę wysłać wiadomości.")
        return

    # Reszta kodu bez zmian...

    # Tworzymy treść wiadomości (możesz używać formatowania Markdown z Discorda, np. pogrubienia)
    message = {
        "content": "🚨 **PROMOCJA WYKRYTA!** 🚨\n\n"
                   f"Cena spadła poniżej Twojego progu: **{target_price} PLN**\n"
                   f"💸 Aktualna cena: **{current_price} PLN**\n"
                   f"🔗 Link do produktu: {product_url}",
        "username": "Price Tracker Bot",  # Nazwa bota
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/2950/2950679.png"  # Ikonka (opcjonalnie)
    }

    try:
        # Wysyłamy paczkę z danymi na Discorda
        response = requests.post(DISCORD_WEBHOOK_URL, json=message)
        response.raise_for_status()  # Sprawdzamy czy nie ma błędu
        print("[Notifier] Powiadomienie wysłane pomyślnie!")
    except Exception as e:
        print(f"[Notifier] Błąd podczas wysyłania na Discorda: {e}")