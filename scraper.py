import asyncio
import cloudscraper
from bs4 import BeautifulSoup
import re
from playwright.async_api import async_playwright


def extract_number(price_str: str) -> float:
    if not price_str:
        return None
    price_str = price_str.lower().replace('zł', '').replace('pln', '').replace(' ', '').replace('\xa0', '')
    price_str = price_str.replace(',', '.')
    match = re.search(r'\d+\.\d+|\d+', price_str)
    if match:
        return float(match.group())
    return None


# Funkcja synchroniczna dla Cloudscrapera - zostanie uruchomiona w osobnym wątku
def fetch_superpharm_sync(url: str) -> float:
    print(f"[Scraper] Próbuję obejść Cloudflare dla: {url}")
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

    try:
        response = scraper.get(url, timeout=15)
        if response.status_code != 200:
            print(f"[Scraper] Błąd Cloudflare! Status: {response.status_code} dla {url}")
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        meta_price = soup.find('meta', attrs={'property': 'product:price:amount'})

        if meta_price and meta_price.get('content'):
            return float(meta_price['content'])

    except Exception as e:
        print(f"[Scraper] Błąd Super-Pharm dla {url}: {e}")

    return None


async def get_price(url: str) -> float:
    print(f"Rozpoczynam pobieranie dla: {url}")

    # 1. Logika SUPER-PHARM (uruchamiana bez Playwrighta)
    if "superpharm.pl" in url:
        # Ponieważ cloudscraper jest synchroniczny, odpalamy go w tle, by nie blokował pętli asyncio
        return await asyncio.to_thread(fetch_superpharm_sync, url)

    # 2. Logika dla X-KOM i reszty (używamy asynchronicznego Playwrighta)
    html_content = ""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=15000)
            html_content = await page.content()
            await browser.close()
    except Exception as e:
        print(f"Błąd Playwright dla {url}: {e}")
        return None

    # SUPER-PODEJŚCIE DLA X-KOM
    if "x-kom.pl" in url:
        match = re.search(r'"priceInfo"\s*:\s*\{\s*"price"\s*:\s*([0-9.]+)', html_content)
        if match:
            cena = float(match.group(1))
            print(f"BINGO! Znaleziono cenę X-kom ({url}): {cena}")
            return cena
        print(f"Nie mogłem znaleźć obiektu priceInfo w x-kom: {url}")

    # Ogólny parsing HTML dla innych sklepów z Playwrighta
    soup = BeautifulSoup(html_content, 'html.parser')

    meta_price = soup.find('meta', property='product:price:amount')
    if meta_price and meta_price.get('content'):
        return extract_number(meta_price['content'])

    fallback_price = soup.find(class_=re.compile("price", re.I))
    if fallback_price:
        return extract_number(fallback_price.text)

    print(f"Strona się załadowała, ale brak ceny dla: {url}")
    return None

