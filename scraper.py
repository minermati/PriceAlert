import json

from bs4 import BeautifulSoup
import re
from playwright.sync_api import sync_playwright


def extract_number(price_str: str) -> float:
    # Ta funkcja zostaje DOKŁADNIE taka sama jak była
    if not price_str:
        return None
    price_str = price_str.lower().replace('zł', '').replace('pln', '').replace(' ', '').replace('\xa0', '')
    price_str = price_str.replace(',', '.')
    match = re.search(r'\d+\.\d+|\d+', price_str)
    if match:
        return float(match.group())
    return None


def get_price(url: str) -> float:
    print(f"Uruchamiam przeglądarkę dla: {url}")

    html_content = ""

    try:
        # Uruchamiamy Playwright
        with sync_playwright() as p:
            # Otwieramy przeglądarkę w trybie "headless" (bez pokazywania okna)
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Wchodzimy na stronę i czekamy aż cała się załaduje (w tym skrypty JS)
            page.goto(url, wait_until="networkidle", timeout=15000)

            # Pobieramy pełny, wyrenderowany przez przeglądarkę kod HTML
            html_content = page.content()

            # Zamykamy przeglądarkę
            browser.close()

    except Exception as e:
        print(f"Błąd Playwright: {e}")
        return None

    # Teraz przekazujemy ten wyrenderowany HTML do naszego starego dobrego BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
    # ---------------------------------------------------------
    # SUPER-PODEJŚCIE DLA X-KOM (Dane z ukrytego JSON-a)
    # ---------------------------------------------------------
    if "x-kom.pl" in url:
        # Szukamy w całym surowym kodzie HTML wzorca: "priceInfo":{"price":2899
        # (.*?) pozwala ominąć ewentualne spacje, a ([0-9.]+) wyłapuje samą liczbę
        match = re.search(r'"priceInfo"\s*:\s*\{\s*"price"\s*:\s*([0-9.]+)', html_content)

        if match:
            # match.group(1) to nasza wyłapana liczba w nawiasie
            cena = float(match.group(1))
            print(f"BINGO! Znaleziono cenę X-kom w ukrytym obiekcie danych: {cena}")
            return cena

        print("Nie mogłem znaleźć obiektu priceInfo w kodzie x-komu.")
    # ---------------------------------------------------------
    # Próba ogólna (Open Graph) - np. dla mniejszych sklepów
    # ---------------------------------------------------------
    meta_price = soup.find('meta', property='product:price:amount')
    if meta_price and meta_price.get('content'):
        return extract_number(meta_price['content'])

    # ---------------------------------------------------------
    # Strzał w ciemno
    # ---------------------------------------------------------
    fallback_price = soup.find(class_=re.compile("price", re.I))
    if fallback_price:
        return extract_number(fallback_price.text)

    print("Strona się załadowała, ale nie mogłem znaleźć elementu z ceną.")
    return None