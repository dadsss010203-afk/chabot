import requests
import os
import time
import urllib3
import unicodedata
import re
import warnings
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from typing import Optional, Set, List

from bs4 import BeautifulSoup

try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= CONFIGURACIÓN =================
BASE_URL = "https://correos.gob.bo"
OUTPUT_FILE = "data/correos_bolivia.txt"
MAX_PAGINAS = 150  # Aumentado porque el sitio tiene contenido real

BASE_NETLOC = urlparse(BASE_URL).netloc

# Solo rutas que sabemos que existen o son probables
PAGINAS_INICIALES = [
    "/",
    "/services",
    "/sp",
    "/servicio-encomienda-postal",
    "/me",
    "/eca",
    "/ems",
    "/realiza-envios-diarios-a",
    "/institucional",
    "/contact-us",
    "/noticias",
    "/about",
    "/filatelia",
    "/chasquiexpressbo",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

# Tags eliminados del contenido DESPUÉS de extraer links
TAGS_BASURA_CONTENIDO = [
    "script", "style", "form", "iframe", "noscript", "svg", "img",
    "button", "input", "select", "textarea", "meta", "link",
    "nav", "header", "footer", "aside",
]


# ================= LIMPIEZA =================

def limpiar_encoding(texto: str) -> str:
    texto = unicodedata.normalize("NFKC", texto)
    texto = re.sub(r'[^\x09\x0A\x0D\x20-\x7E\x80-\xFF\u0100-\u024F]', '', texto)
    return texto


def limpiar_texto(texto: str) -> str:
    texto = limpiar_encoding(texto)
    texto = re.sub(r'https?://\S+', '', texto)
    texto = re.sub(r'\S+@\S+\.\S+', '', texto)
    texto = re.sub(r'[_\-=*#]{3,}', '', texto)
    texto = re.sub(r'^\s*\d+\s*$', '', texto, flags=re.MULTILINE)
    texto = re.sub(r'^[^a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\d]+$', '', texto, flags=re.MULTILINE)
    texto = re.sub(r' {2,}', ' ', texto)
    texto = re.sub(r'\n{3,}', '\n\n', texto)

    lineas_limpias = []
    for linea in texto.splitlines():
        linea = linea.strip()
        if (
            len(linea) > 5
            and not re.match(r'^[\d\s\.\,\:\;\-\/\(\)]+$', linea)
        ):
            lineas_limpias.append(linea)

    return "\n".join(lineas_limpias)


# ================= EXTRACCIÓN =================

def extraer_contenido_principal(soup: BeautifulSoup) -> str:
    for selector in [
        "main", "article", "#content", ".content",
        "#main", ".main", ".entry-content", ".post-content",
        ".post", ".page-content", ".site-content",
        "#primary", ".primary", ".elementor-section",
        ".wp-block-group", ".wp-block-post-content",
    ]:
        contenido = soup.select_one(selector)
        if contenido and len(contenido.get_text(strip=True)) > 50:
            return contenido.get_text(separator="\n")

    body = soup.body
    if body:
        return body.get_text(separator="\n")

    return soup.get_text(separator="\n")


def normalizar_ruta(href: str) -> Optional[str]:
    href = href.strip()
    if not href or href.startswith("javascript:") or href.startswith("#"):
        return None

    parsed = urlparse(href)
    if parsed.netloc and parsed.netloc != BASE_NETLOC:
        return None

    ruta = parsed.path or "/"
    if ':' in ruta:
        return None
    if ruta != "/":
        ruta = ruta.rstrip("/")
    return ruta if ruta else "/"


def extraer_urls_de_sitemap(session: requests.Session) -> Set[str]:
    """Extrae URLs del sitemap principal y todos sus sub-sitemaps."""
    urls: Set[str] = set()
    sitemaps_procesados: Set[str] = set()

    def procesar_sitemap(url_sitemap: str, profundidad: int = 0) -> None:
        if profundidad > 3 or url_sitemap in sitemaps_procesados:
            return
        sitemaps_procesados.add(url_sitemap)
        try:
            resp = session.get(url_sitemap, headers=HEADERS, timeout=10, verify=False)
            if resp.status_code != 200:
                return
            root = ET.fromstring(resp.content)
            ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

            # Sub-sitemaps (sitemapindex)
            for loc in root.findall('.//ns:sitemap/ns:loc', ns):
                if loc.text and loc.text.strip():
                    procesar_sitemap(loc.text.strip(), profundidad + 1)

            # URLs directas (urlset)
            for loc in root.findall('.//ns:url/ns:loc', ns):
                if loc.text:
                    ruta = normalizar_ruta(loc.text.strip())
                    if ruta:
                        urls.add(ruta)
        except Exception:
            pass

    sitemap_url = BASE_URL.rstrip("/") + "/sitemap.xml"
    print(f"[SITEMAP] Procesando {sitemap_url} ...")
    procesar_sitemap(sitemap_url)

    if urls:
        print(f"[SITEMAP] {len(urls)} URLs encontradas")
    else:
        print("[SITEMAP] Sin URLs (sitemap inexistente o vacío)")

    return urls


def paginacion_inteligente(
    ruta_base: str,
    session: requests.Session,
) -> List[str]:
    """
    Genera páginas de paginación SOLO mientras el servidor responda 200.
    Para en el primer 404, evitando colas de URLs inútiles.
    """
    paginas_validas: List[str] = []
    for num in range(2, 20):
        ruta_pag = f"{ruta_base}/page/{num}"
        url = BASE_URL.rstrip("/") + ruta_pag
        try:
            resp = session.head(url, headers=HEADERS, timeout=8, verify=False,
                                allow_redirects=True)
            if resp.status_code == 200:
                paginas_validas.append(ruta_pag)
            else:
                break  # Parar en el primer error
        except Exception:
            break
    return paginas_validas


def scrapear_links_internos(soup: BeautifulSoup) -> Set[str]:
    """Extrae todos los enlaces internos del HTML completo (antes de limpiar)."""
    links: Set[str] = set()
    for a in soup.find_all("a", href=True):
        ruta = normalizar_ruta(a["href"].strip())
        if not ruta:
            continue
        if re.search(r'\.(pdf|jpg|jpeg|png|gif|zip|docx?|xlsx?|css|js|apk|exe|xml)$', ruta, re.I):
            continue
        if re.search(r'(wp-admin|wp-login|login|logout|register|cart|checkout|feed)', ruta, re.I):
            continue
        links.add(ruta)
    return links


# ================= SESIÓN HTTP =================

def crear_sesion() -> requests.Session:
    session = requests.Session()
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retries = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session


# ================= MAIN =================

def main() -> None:
    os.makedirs("data", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("")

    todo_el_texto: List[str] = []
    visitadas: Set[str] = set()
    cola: List[str] = []
    cola_set: Set[str] = set()
    categorias_paginadas: Set[str] = set()  # evitar reprocesar paginación

    exitosas = 0
    fallidas = 0

    def encolar(ruta: str) -> None:
        if ruta and ruta not in visitadas and ruta not in cola_set:
            cola.append(ruta)
            cola_set.add(ruta)

    for p in PAGINAS_INICIALES:
        r = normalizar_ruta(p)
        if r:
            encolar(r)

    print("=" * 60)
    print("  Scraper Correos Bolivia")
    print(f"  URL base : {BASE_URL}")
    print(f"  Máx págs : {MAX_PAGINAS}")
    print("=" * 60)

    session = crear_sesion()

    try:
        print()
        for url in extraer_urls_de_sitemap(session):
            encolar(url)
        print(f"[INICIO] Cola inicial: {len(cola)} URLs\n")

        while cola and len(visitadas) < MAX_PAGINAS:
            ruta = cola.pop(0)
            cola_set.discard(ruta)

            if ruta in visitadas:
                continue
            visitadas.add(ruta)

            url_completa = BASE_URL.rstrip("/") + ruta
            print(f"[{len(visitadas):>3}/{MAX_PAGINAS}] {url_completa}  (cola: {len(cola)})")

            try:
                resp = session.get(url_completa, headers=HEADERS, timeout=15, verify=False)
                resp.raise_for_status()

                # Saltar XML que no sea HTML
                content_type = resp.headers.get("Content-Type", "")
                if "xml" in content_type and "html" not in content_type:
                    print("       [XML] omitiendo")
                    fallidas += 1
                    continue

                html = resp.content.decode("utf-8", errors="replace")
                soup = BeautifulSoup(html, "html.parser")

                # ── 1. Extraer links del HTML completo ──
                agregados = 0
                if len(visitadas) < MAX_PAGINAS:
                    for link in scrapear_links_internos(soup):
                        if link not in visitadas and link not in cola_set:
                            encolar(link)
                            agregados += 1

                # ── 2. Paginación INTELIGENTE (solo para categorías, solo una vez) ──
                es_categoria = '/category/' in ruta
                es_autor = '/author/' in ruta and '/page/' not in ruta
                ruta_base = ruta.rstrip("/")

                if (es_categoria or es_autor) and ruta_base not in categorias_paginadas:
                    categorias_paginadas.add(ruta_base)
                    print(f"       → Detectando paginación para {ruta_base}...")
                    paginas = paginacion_inteligente(ruta_base, session)
                    for p in paginas:
                        encolar(p)
                    if paginas:
                        print(f"       → {len(paginas)} páginas válidas encontradas")

                # ── 3. Meta datos ──
                titulo_tag = soup.find("title")
                titulo_texto = titulo_tag.get_text().strip() if titulo_tag else ""
                meta_desc = soup.find("meta", attrs={"name": "description"})
                meta_texto = meta_desc.get("content", "").strip() if meta_desc else ""

                # ── 4. Limpiar y extraer contenido ──
                for tag in soup(TAGS_BASURA_CONTENIDO):
                    tag.decompose()

                texto_raw = extraer_contenido_principal(soup)
                texto_limpio = limpiar_texto(texto_raw)

                if texto_limpio and len(texto_limpio) > 80:
                    if "sitemap" not in url_completa.lower():
                        partes = [f"\n{'=' * 60}", f"FUENTE: {url_completa}"]
                        if titulo_texto:
                            partes.append(f"TÍTULO: {limpiar_encoding(titulo_texto)}")
                        if meta_texto:
                            partes.append(f"DESCRIPCIÓN: {limpiar_encoding(meta_texto)}")
                        partes += [f"{'=' * 60}", texto_limpio, ""]

                        trozo = "\n".join(partes)
                        todo_el_texto.append(trozo)
                        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                            f.write(trozo)

                        print(f"       ✓ {len(texto_limpio):,} chars | +{agregados} links nuevos")
                        exitosas += 1
                    else:
                        print("       [SITEMAP] omitiendo")
                        fallidas += 1
                else:
                    print(f"       ⚠ Muy poco contenido ({len(texto_limpio)} chars)")
                    fallidas += 1

            except requests.exceptions.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                print(f"       ❌ HTTP {code}")
                fallidas += 1
            except requests.exceptions.ConnectionError:
                print("       ❌ Error de conexión")
                fallidas += 1
            except Exception as e:
                print(f"       ❌ {type(e).__name__}: {e}")
                fallidas += 1

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n🛑 Interrumpido. Guardando progreso...")

    # ===== RESULTADO FINAL =====
    contenido_final = "\n".join(todo_el_texto)
    contenido_final = re.sub(r'\n{4,}', '\n\n', contenido_final).strip()

    if contenido_final:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(contenido_final)
        print(f"\n{'=' * 60}")
        print("SCRAPING COMPLETADO")
        print(f"  Archivo            : {OUTPUT_FILE}")
        print(f"  Caracteres totales : {len(contenido_final):,}")
        print(f"  Páginas exitosas   : {exitosas}")
        print(f"  Páginas fallidas   : {fallidas}")
        print(f"{'=' * 60}")
        print("\nAhora borra chroma_db/ y corre: python chatbot.py")
    else:
        print("\n⚠ No se pudo extraer contenido útil.")


if __name__ == "__main__":
    main()