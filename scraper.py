import asyncio
import urllib.parse
import aiohttp
from bs4 import BeautifulSoup
import re
import json
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# Wpisz tutaj swój klucz ze strony ScraperAPI
SCRAPER_API_KEY = ""


def extract_number(price_str: str) -> float:
    if not price_str:
        return None
    price_str = price_str.lower().replace('zł', '').replace('pln', '').replace(' ', '').replace('\xa0', '')
    price_str = price_str.replace(',', '.')
    match = re.search(r'\d+\.\d+|\d+', price_str)
    if match:
        val = float(match.group())
        if val > 0:
            return val
    return None


def is_blocked(html_content: str) -> bool:
    """Sprawdza, czy pobrany HTML to strona blokady WAF/Captcha."""
    if not html_content:
        return True

    soup = BeautifulSoup(html_content, 'html.parser')
    title = soup.title.string.lower() if soup.title else ""

    # Słowa kluczowe używane przez Cloudflare, DataDome, Akamai itp.
    block_keywords = [
        "just a moment", "attention required", "cloudflare",
        "access denied", "zablokowany", "robot", "captcha", "datadome", "403 forbidden"
    ]

    for kw in block_keywords:
        if kw in title:
            return True

    # Jeśli strona jest nienaturalnie mała (np. pusty tag <body>)
    if len(html_content) < 2000:
        return True

    return False


async def fetch_html_via_playwright(url: str) -> str:
    """Próbuje pobrać stronę lokalnie za pomocą Playwrighta z ukrywaniem bota."""
    print(f"[Playwright] Próbuję pobrać lokalnie: {url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            # Dajemy Playwrightowi 15 sekund na pobranie
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            html_content = await page.content()
            await browser.close()
            return html_content
    except PlaywrightTimeoutError:
        print(f"[Playwright] Timeout - serwer zablokował połączenie dla {url}")
        return None
    except Exception as e:
        print(f"[Playwright] Błąd pobierania dla {url}: {e}")
        return None


async def fetch_html_via_api(url: str, render_js: bool = False) -> str:
    clean_url = url.split('?')[0]
    encoded_url = urllib.parse.quote(clean_url)
    api_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={encoded_url}&device_type=desktop"

    # DODANO EZEBRA.PL DO PROXY PREMIUM
    if any(domain in url for domain in ["notino.pl", "rossmann.pl", "ezebra.pl"]):
        api_url += "&premium=true&country_code=pl"

    if render_js:
        api_url += "&render=true"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=60) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    print(f"[ScraperAPI] Błąd pobierania {clean_url}. Status: {response.status}")
                    return None
    except Exception as e:
        print(f"[ScraperAPI] Wyjątek podczas łączenia dla {clean_url}: {e}")
        return None


# --- PARSERY SKLEPÓW ---

async def parse_empik(html_content: str, url: str) -> float:
    soup = BeautifulSoup(html_content, 'html.parser')

    meta_price = soup.find('meta', attrs={'property': 'product:price:amount'})
    if meta_price and meta_price.get('content'):
        cena = extract_number(meta_price['content'])
        if cena: return cena

    price_divs = soup.find_all(class_=re.compile("price", re.I))
    for div in price_divs:
        if div.text and "zł" in div.text.lower():
            cena = extract_number(div.text)
            if cena: return cena

    next_data = soup.find('script', id='__NEXT_DATA__')
    if next_data:
        try:
            json_str = json.dumps(json.loads(next_data.string))
            matches = re.findall(r'"(?:basePrice|price|sellPrice)"\s*:\s*([0-9]+\.[0-9]{2})', json_str)
            for match in matches:
                cena = float(match)
                if cena > 0: return cena
        except Exception:
            pass

    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'Product':
                offers = data.get('offers', {})
                if isinstance(offers, dict) and 'price' in offers:
                    cena = float(offers['price'])
                    if cena > 0: return cena
                elif isinstance(offers, list) and len(offers) > 0 and 'price' in offers[0]:
                    cena = float(offers[0]['price'])
                    if cena > 0: return cena
        except:
            continue

    price_texts = soup.find_all(string=re.compile(r'\d+,\d{2}\s*zł'))
    if price_texts:
        cena = extract_number(price_texts[0])
        if cena: return cena
    return None


async def parse_notino(html_content: str, url: str) -> float:
    soup = BeautifulSoup(html_content, 'html.parser')
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'Product':
                offers = data.get('offers', {})
                if isinstance(offers, dict) and 'price' in offers:
                    cena = float(offers['price'])
                    if cena > 0: return cena
                elif isinstance(offers, list) and len(offers) > 0:
                    for offer in offers:
                        if 'price' in offer:
                            cena = float(offer['price'])
                            if cena > 0: return cena
        except Exception:
            continue
    meta_price = soup.find('meta', property='product:price:amount') or soup.find('meta', itemprop='price')
    if meta_price and meta_price.get('content'):
        cena = extract_number(meta_price['content'])
        if cena: return cena
    return None


async def parse_hebe(html_content: str, url: str) -> float:
    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. ZŁOTY STANDARD: Szukamy głęboko ukrytych danych JSON-LD głównego produktu
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)

            # Czasami Hebe pakuje to w listę
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'Product':
                        data = item
                        break

            if isinstance(data, dict) and data.get('@type') == 'Product':
                offers = data.get('offers', {})
                if isinstance(offers, dict) and 'price' in offers:
                    cena = float(offers['price'])
                    if cena > 0: return cena
                elif isinstance(offers, list) and len(offers) > 0:
                    cena = float(offers[0].get('price', 0))
                    if cena > 0: return cena
        except Exception:
            continue

    # 2. Próba: Główna klasa ceny Hebe, ale zawężona TYLKO do bloku detali produktu
    # Omijamy dzięki temu ceny z karuzel polecanych produktów!
    sales_price = soup.select_one('.product-detail .price-sales') or soup.select_one('.price-sales')
    if sales_price:
        cena = extract_number(sales_price.text)
        if cena: return cena

    # 3. Fallback na mikroformaty
    meta_price = soup.find('meta', itemprop='price') or soup.find('span', itemprop='price')
    if meta_price and meta_price.get('content'):
        cena = extract_number(meta_price['content'])
        if cena > 0: return cena

    return None

async def parse_superpharm(html_content: str, url: str) -> float:
    soup = BeautifulSoup(html_content, 'html.parser')
    meta_price = soup.find('meta', attrs={'property': 'product:price:amount'})
    if meta_price and meta_price.get('content'):
        try:
            cena = float(meta_price['content'])
            if cena > 0: return cena
        except ValueError:
            pass
    return None


async def parse_xkom(html_content: str, url: str) -> float:
    match = re.search(r'"priceInfo"\s*:\s*\{\s*"price"\s*:\s*([0-9.]+)', html_content)
    if match:
        try:
            cena = float(match.group(1))
            if cena > 0: return cena
        except ValueError:
            pass
    return None


# --- GŁÓWNA FUNKCJA ---
async def parse_ezebra(html_content: str, url: str) -> float:
    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Złoty standard: JSON-LD (eZebra zazwyczaj ładnie to wystawia)
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'Product':
                offers = data.get('offers', {})
                if isinstance(offers, dict) and 'price' in offers:
                    cena = float(offers['price'])
                    if cena > 0: return cena
                elif isinstance(offers, list) and len(offers) > 0:
                    cena = float(offers[0].get('price', 0))
                    if cena > 0: return cena
        except Exception:
            continue

    # 2. Próba: Meta tagi używane przez eZebra
    meta_price = soup.find('meta', itemprop='price') or soup.find('meta', property='product:price:amount')
    if meta_price and meta_price.get('content'):
        cena = extract_number(meta_price['content'])
        if cena and cena > 0: return cena

    # 3. Próba: Specyficzne klasy HTML dla silnika IdoSell / eZebra
    # Szukamy głównych klas z ceną, omijając przekreślone ceny i historię Omnibusa
    price_elements = soup.select('.projector_price_value, .price, [data-price]')
    for el in price_elements:
        # Jeśli element ma zadeklarowany atrybut systemowy (najdokładniejsze)
        if el.has_attr('data-price'):
            cena = extract_number(el['data-price'])
            if cena and cena > 0: return cena

        # Fallback na szukanie w tekście
        text = el.get_text(separator=" ").lower()
        if "30 dni" in text or "najniższ" in text or "omnibus" in text or "regularna" in text or "stara" in text:
            continue

        if "zł" in text:
            cena = extract_number(text)
            if cena and cena > 0: return cena

    return None

async def get_price(url: str) -> float:
    print(f"\nRozpoczynam pobieranie dla: {url}")

    # 1. Próbujemy pobrać Playwrightem
    html_content = await fetch_html_via_playwright(url)

    # 2. Weryfikujemy, czy Playwright został zablokowany lub wyrzucił błąd
    if is_blocked(html_content):
        print(f"[Fallback] Playwright zawiódł/zablokowany. Uruchamiam ScraperAPI...")
        needs_js = True
        html_content = await fetch_html_via_api(url, render_js=needs_js)

    if not html_content:
        print(f"Nie udało się pobrać strony (ani Playwright, ani API) dla: {url}")
        return None

    # 3. Parsowanie wyciągniętego kodu HTML
    if "empik.com" in url:
        cena = await parse_empik(html_content, url)
        if cena: return cena
    elif "notino.pl" in url:
        cena = await parse_notino(html_content, url)
        if cena: return cena
    elif "hebe.pl" in url:
        cena = await parse_hebe(html_content, url)
        if cena: return cena
    elif "superpharm.pl" in url:
        cena = await parse_superpharm(html_content, url)
        if cena: return cena
    elif "x-kom.pl" in url:
        cena = await parse_xkom(html_content, url)
        if cena: return cena
    # DODANO EZEBRA:
    elif "ezebra.pl" in url:
        cena = await parse_ezebra(html_content, url)
        if cena: return cena

    # Fallback dla wszystkich innych/nowych sklepów
    soup = BeautifulSoup(html_content, 'html.parser')
    meta_price = soup.find('meta', property='product:price:amount')
    if meta_price and meta_price.get('content'):
        cena = extract_number(meta_price['content'])
        if cena: return cena

    fallback_price = soup.find(class_=re.compile("price", re.I))
    if fallback_price:
        cena = extract_number(fallback_price.text)
        if cena: return cena

    print(f"Strona pobrana, ale nie odnaleziono ceny dla: {url}")
    return None