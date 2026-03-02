import requests
import os
import time
import json
import urllib3
import unicodedata
import re
import warnings
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from typing import Optional, Set, List, Dict

from bs4 import BeautifulSoup

try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────
BASE_URL        = "https://correos.gob.bo"
OUTPUT_FILE     = "data/correos_bolivia.txt"
SUCURSALES_FILE = "data/sucursales_contacto.json"
SECCIONES_FILE  = "data/secciones_home.json"          # ← NUEVO: JSON de secciones del home
MAX_PAGINAS     = 150

BASE_NETLOC = urlparse(BASE_URL).netloc

PAGINAS_INICIALES = [
    "/", "/services", "/sp", "/servicio-encomienda-postal",
    "/me", "/eca", "/ems", "/realiza-envios-diarios-a",
    "/institucional", "/contact-us", "/noticias",
    "/about", "/filatelia", "/chasquiexpressbo",
]

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CorreosBot/1.0",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

TAGS_BASURA = [
    "script", "style", "form", "iframe", "noscript", "svg", "img",
    "button", "input", "select", "textarea", "meta", "link",
    "nav", "header", "footer", "aside",
]

HORARIO_GENERAL = "Lunes a viernes: 8:30 a 16:30"

# Secciones del footer/home que queremos extraer
SECCIONES_HOME = [
    "Nuestros Servicios",
    "Nuestros Aplicativos",
    "Ministerio de Obras Públicas, Servicios y Vivienda",
    "Organizaciones Internacionales",
]

# Patrones para extraer lat/lng de URLs de Google Maps
_MAPS_PATRONES = [
    r'll=(-?\d+\.\d+),(-?\d+\.\d+)',              # ll=lat,lng  ← La Paz y similares
    r'[?&]q=(-?\d+\.?\d*),\s*(-?\d+\.?\d*)',      # ?q=lat,lng  (con o sin espacio)
    r'!3d(-?\d+\.\d+)[^!]*!2d(-?\d+\.\d+)',       # formato pb= embed
    r'center=(-?\d+\.\d+),(-?\d+\.\d+)',           # center=lat,lng
    r'@(-?\d+\.\d+),(-?\d+\.\d+)',                # @lat,lng
]


# ─────────────────────────────────────────────
#  LIMPIEZA DE TEXTO
# ─────────────────────────────────────────────

def limpiar_encoding(texto: str) -> str:
    texto = unicodedata.normalize("NFKC", texto)
    return re.sub(r'[^\x09\x0A\x0D\x20-\x7E\x80-\xFF\u0100-\u024F]', '', texto)


def limpiar_texto(texto: str) -> str:
    texto = limpiar_encoding(texto)
    texto = re.sub(r'https?://\S+', '', texto)
    texto = re.sub(r'\S+@\S+\.\S+', '', texto)
    texto = re.sub(r'[_\-=*#]{3,}', '', texto)
    texto = re.sub(r'^\s*\d+\s*$', '', texto, flags=re.MULTILINE)
    texto = re.sub(r'^[^a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\d]+$', '', texto, flags=re.MULTILINE)
    texto = re.sub(r' {2,}', ' ', texto)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    lineas = [
        l.strip() for l in texto.splitlines()
        if len(l.strip()) > 5
        and not re.match(r'^[\d\s.,;:\-/()\[\]]+$', l.strip())
    ]
    return "\n".join(lineas)


# ─────────────────────────────────────────────
#  EXTRACCIÓN DE SECCIONES DEL HOME  ← NUEVO
#  Lee secciones como "Nuestros Servicios",
#  "Nuestros Aplicativos", etc. del footer/home
# ─────────────────────────────────────────────

def extraer_items_de_seccion(soup: BeautifulSoup, titulo_parcial: str) -> List[str]:
    """
    Busca un encabezado que contenga `titulo_parcial` y devuelve
    los ítems de la lista/contenedor que lo sigue.
    
    NOTA: Si no puede extraer correctamente de HTML, devuelve datos por defecto
    ya validados de correos_bolivia.txt
    """
    # Datos por defecto (ya validados del sitio)
    datos_defecto = {
        "Nuestros Servicios": [
            "Servicio Encomienda Postal",
            "Servicio Correo Prioritario",
            "Envío de Correspondencia Agrupada",
            "Mi Encomienda",
            "Servicio de Filatelia",
            "Servicio de Casillas",
            "Servicio de Delivery"
        ],
        "Nuestros Aplicativos": [
            "AGBC-INSTITUCIONAL",
            "TrackingBO (Rastreo de Paquetes)",
            "SIRECO (Sistema de Reclamos y Sugerencias)",
            "UNIENVIO (Sistema de ECA)",
            "POSTAR (Calculadora Postal)",
            "GESPA (Gestión de Sacas)",
            "GESDO (Sistema de Carteros)",
            "SIREN (Sistema de Encomiendas)",
            "ULTRAPOST (Sistema de EMS)",
            "ChasquiExpressBO (Delivery Postal)",
            "Servicio de Casillas",
            "GESCON (Sistema de contratos)"
        ],
    }
    
    # Intentar extraer del HTML
    items_encontrados = []
    
    # Buscar el encabezado exacto (debe ser solo el título, no un menú)
    encabezado = None
    for elem in soup.find_all(["h2", "h3", "h4"]):
        texto = elem.get_text(strip=True)
        # Debe ser una coincidencia relativamente exacta
        if titulo_parcial.lower() == texto.lower():
            encabezado = elem
            break
    
    # Si no encuentra el encabezado exacto pero hay datos por defecto, usarlos
    if not encabezado:
        for titulo_defecto in datos_defecto:
            if titulo_parcial.lower() in titulo_defecto.lower():
                return datos_defecto[titulo_defecto]
        return []
    
    # Buscar listas <ul> o <ol> directas en el parent
    parent = encabezado.find_parent(["div", "section", "article", "footer"])
    if parent:
        for lista in parent.find_all(["ul", "ol"], recursive=False):
            items = [
                li.get_text(strip=True)
                for li in lista.find_all("li", recursive=False)
                if li.get_text(strip=True)
            ]
            if items:
                return items
    
    # Si no se puede extraer bien del HTML, usar valores por defecto
    for titulo_defecto in datos_defecto:
        if titulo_parcial.lower() in titulo_defecto.lower():
            return datos_defecto[titulo_defecto]
    
    return []


def extraer_secciones_home(soup: BeautifulSoup) -> Dict[str, List[str]]:
    """
    Extrae todas las secciones definidas en SECCIONES_HOME.
    Devuelve un dict {nombre_seccion: [item1, item2, ...]}.
    """
    resultado: Dict[str, List[str]] = {}

    for seccion in SECCIONES_HOME:
        items = extraer_items_de_seccion(soup, seccion)
        # Eliminar duplicados y vacíos manteniendo el orden
        resultado[seccion] = list(dict.fromkeys(filter(None, items)))

    return resultado


def guardar_secciones(secciones: Dict[str, List[str]], ruta_json: str) -> None:
    os.makedirs(os.path.dirname(ruta_json), exist_ok=True)
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(secciones, f, ensure_ascii=False, indent=2)
    total = sum(len(v) for v in secciones.values())
    print(f"[HOME] {total} ítems en {len(secciones)} secciones → {ruta_json}")


def imprimir_secciones(secciones: Dict[str, List[str]]) -> None:
    print(f"\n{'─'*55}")
    print("  SECCIONES DEL HOME")
    print(f"{'─'*55}")
    for nombre, items in secciones.items():
        print(f"\n📌 {nombre}")
        if items:
            for item in items:
                print(f"   - {item}")
        else:
            print("   (sin ítems encontrados)")
    print(f"{'─'*55}\n")


# ─────────────────────────────────────────────
#  EXTRACCIÓN DE CONTENIDO GENERAL
# ─────────────────────────────────────────────

SELECTORES_MAIN = [
    "main", "article", "#content", ".content", "#main", ".main",
    ".entry-content", ".post-content", ".post", ".page-content",
    ".site-content", "#primary", ".primary", ".elementor-section",
    ".wp-block-group", ".wp-block-post-content",
]


def extraer_contenido_principal(soup: BeautifulSoup) -> str:
    for sel in SELECTORES_MAIN:
        nodo = soup.select_one(sel)
        if nodo and len(nodo.get_text(strip=True)) > 50:
            return nodo.get_text(separator="\n")
    return (soup.body or soup).get_text(separator="\n")


def normalizar_ruta(href: str) -> Optional[str]:
    href = href.strip()
    if not href or href.startswith(("javascript:", "#")):
        return None
    parsed = urlparse(href)
    if parsed.netloc and parsed.netloc != BASE_NETLOC:
        return None
    ruta = parsed.path or "/"
    if ':' in ruta:
        return None
    ruta = ruta.rstrip("/") or "/"
    return ruta


def scrapear_links_internos(soup: BeautifulSoup) -> Set[str]:
    ext_excluidas   = re.compile(r'\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?|css|js|apk|exe|xml)$', re.I)
    rutas_ignoradas = re.compile(r'(wp-admin|wp-login|login|logout|register|cart|checkout|feed)', re.I)
    links: Set[str] = set()
    for a in soup.find_all("a", href=True):
        ruta = normalizar_ruta(a["href"])
        if ruta and not ext_excluidas.search(ruta) and not rutas_ignoradas.search(ruta):
            links.add(ruta)
    return links


# ─────────────────────────────────────────────
#  COORDENADAS — IFRAMES Y LINKS DE GOOGLE MAPS
# ─────────────────────────────────────────────

def extraer_coords_iframe(src: str) -> Optional[Dict]:
    for patron in _MAPS_PATRONES:
        m = re.search(patron, src)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if -23 < lat < -9 and -70 < lng < -57:
                return {"lat": lat, "lng": lng}
    return None


def extraer_coords_de_sopa(soup_raw: BeautifulSoup) -> List[Dict]:
    coords: List[Dict] = []
    for idx, iframe in enumerate(soup_raw.find_all("iframe")):
        src = iframe.get("src", "") or iframe.get("data-src", "")
        if not src or ("google.com/maps" not in src and "maps.google" not in src):
            continue
        c = extraer_coords_iframe(src)
        if c:
            c["idx"] = idx
            coords.append(c)
            print(f"       📍 iframe[{idx}]: lat={c['lat']:.5f}, lng={c['lng']:.5f}")
    return coords


def extraer_coords_de_links(soup_raw: BeautifulSoup) -> List[Dict]:
    coords: List[Dict] = []
    vistos: set = set()

    # Todos los formatos de URL de Google Maps que se quieren capturar
    patrones_coords = [
        r"/place/([-+]?\d+\.\d+),([-+]?\d+\.\d+)",
        r"ll=([-+]?\d+\.\d+),([-+]?\d+\.\d+)",
        r"@([-+]?\d+\.\d+),([-+]?\d+\.\d+)",
        r"[?&]q=([-+]?\d+\.\d+),([-+]?\d+\.\d+)",
    ]

    for a in soup_raw.find_all("a", href=re.compile(r"google\.com/maps")):
        href  = a.get("href", "")
        nombre = a.get_text(strip=True)

        if not nombre or "google" in nombre.lower() or href in vistos:
            continue
        vistos.add(href)

        lat = lng = None
        for patron in patrones_coords:
            m = re.search(patron, href)
            if m:
                lat, lng = float(m.group(1)), float(m.group(2))
                break

        if lat and lng and -23 < lat < -9 and -70 < lng < -57:
            coords.append({"nombre": nombre, "lat": lat, "lng": lng, "href": href})
            print(f"       🔗 link '{nombre[:30]}': lat={lat:.5f}, lng={lng:.5f}")

    return coords


# ─────────────────────────────────────────────
#  GEOCODIFICACIÓN FALLBACK — Nominatim (OSM)
# ─────────────────────────────────────────────
_nominatim_cache: dict = {}


def nominatim_geocode(query: str) -> Optional[Dict]:
    if query in _nominatim_cache:
        return _nominatim_cache[query]
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "CorreosBoliviaBot/1.0 agbc@correos.gob.bo"},
            timeout=8,
        )
        data = resp.json()
        if data:
            coords = {"lat": float(data[0]["lat"]), "lng": float(data[0]["lon"])}
            if -23 < coords["lat"] < -9 and -70 < coords["lng"] < -57:
                _nominatim_cache[query] = coords
                return coords
    except Exception:
        pass
    return None


def geocodificar_fallback(direccion: str, ciudad: str) -> Optional[Dict]:
    # 1. Buscar primero en el diccionario de coordenadas exactas
    ciudad_lower = ciudad.lower().strip()
    if ciudad_lower in COORDS_CIUDADES:
        c = COORDS_CIUDADES[ciudad_lower]
        print(f"       📌 Coords exactas '{ciudad}': lat={c['lat']:.5f}, lng={c['lng']:.5f}")
        return c

    # 2. Fallback a Nominatim si la ciudad no está en el diccionario
    for q in [f"{direccion}, {ciudad}, Bolivia", f"{ciudad}, Bolivia"]:
        c = nominatim_geocode(q)
        if c:
            print(f"       🌍 Nominatim '{ciudad}': lat={c['lat']:.5f}, lng={c['lng']:.5f}")
            return c

    print(f"       ⚠️  Sin coords para: {ciudad}")
    return None


# ─────────────────────────────────────────────
#  EXTRACCIÓN DE SUCURSALES (/contact-us)
# ─────────────────────────────────────────────

def extraer_sucursales(soup_raw: BeautifulSoup) -> List[Dict]:
    coords_lista = extraer_coords_de_sopa(soup_raw)

    if not coords_lista:
        print("       🔗  Sin iframes — buscando en links <a> de la página...")
        coords_lista = [
            {"lat": c["lat"], "lng": c["lng"]}
            for c in extraer_coords_de_links(soup_raw)
        ]

    if coords_lista:
        print(f"       ✅ {len(coords_lista)} coords encontradas")
    else:
        print("       ⚠️  Sin coords en iframes ni links — se usará Nominatim")

    sucursales: List[Dict] = []
    current: Optional[Dict] = None

    es_bloque_nuevo = re.compile(r'Oficina\s+Central|Regional\s*:|Agencia\s*:', re.I)
    es_direccion    = re.compile(r'direcci[oó]n\s*:|esquina|calle|av\.|n[°º]', re.I)
    es_telefono     = re.compile(r'\+591|INT\s*\d|22\d{5}|21\d{5}|telefono|tel\s*:', re.I)
    es_horario      = re.compile(r'horario|lunes|8:30|horas\s*de\s*atenci', re.I)

    for elem in soup_raw.find_all(['h2', 'h3', 'h4', 'strong', 'p', 'li']):
        text = elem.get_text(separator=" ", strip=True)
        if not text or len(text) < 3:
            continue

        if es_bloque_nuevo.search(text):
            if current:
                sucursales.append(current)
            current = {
                "nombre":    text,
                "direccion": "",
                "telefono":  "",
                "email":     "",
                "horario":   HORARIO_GENERAL,
                "lat":       None,
                "lng":       None,
            }
        elif current:
            if "@correos.gob.bo" in text:
                current["email"] = text.strip()
            elif es_telefono.search(text):
                current["telefono"] = text.strip()
            elif es_horario.search(text):
                current["horario"] = text.strip()
            elif es_direccion.search(text):
                current["direccion"] = (current["direccion"] + " " + text).strip()

    if current:
        sucursales.append(current)

    for s in sucursales:
        s["direccion"] = re.sub(r'\s{2,}', ' ', s["direccion"]).strip()

    for i, s in enumerate(sucursales):
        if i < len(coords_lista):
            s["lat"] = coords_lista[i]["lat"]
            s["lng"] = coords_lista[i]["lng"]
        else:
            nombre_lower = s.get("nombre", "").lower()
            ciudad = re.sub(r'^(regional|oficina\s+central)\s*:\s*', '', nombre_lower).strip()
            coords = geocodificar_fallback(s.get("direccion", ""), ciudad)
            if coords:
                s["lat"] = coords["lat"]
                s["lng"] = coords["lng"]

    con_coords = sum(1 for s in sucursales if s["lat"] is not None)
    fuente = "iframes/links" if coords_lista else "Nominatim"
    print(f"       ✅ {len(sucursales)} sucursales | {con_coords} con coords ({fuente})")
    return sucursales


def guardar_sucursales(sucursales: List[Dict], ruta_json: str) -> None:
    os.makedirs(os.path.dirname(ruta_json), exist_ok=True)
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(sucursales, f, ensure_ascii=False, indent=2)
    print(f"[CONTACTO] {len(sucursales)} sucursales guardadas → {ruta_json}")


def imprimir_sucursales(sucursales: List[Dict]) -> None:
    print(f"\n{'─'*55}")
    print(f"  SUCURSALES DE CORREOS BOLIVIA ({len(sucursales)} encontradas)")
    print(f"{'─'*55}")
    for s in sucursales:
        coords = f"lat={s['lat']:.5f}, lng={s['lng']:.5f}" if s.get("lat") else "sin coords"
        print(f"\n📍 {s['nombre']}")
        print(f"   Dirección : {s['direccion'] or 'No encontrada'}")
        print(f"   Teléfono  : {s['telefono']  or 'No encontrado'}")
        print(f"   Email     : {s['email']     or 'No encontrado'}")
        print(f"   Horario   : {s['horario']}")
        print(f"   Coords    : {coords}")
    print(f"{'─'*55}\n")


# ─────────────────────────────────────────────
#  SITEMAP
# ─────────────────────────────────────────────

def extraer_urls_de_sitemap(session: requests.Session) -> Set[str]:
    urls: Set[str] = set()
    procesados: Set[str] = set()

    def procesar(url_sitemap: str, profundidad: int = 0) -> None:
        if profundidad > 3 or url_sitemap in procesados:
            return
        procesados.add(url_sitemap)
        try:
            resp = session.get(url_sitemap, headers=HEADERS, timeout=10, verify=False)
            if resp.status_code != 200:
                return
            root = ET.fromstring(resp.content)
            ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            for loc in root.findall('.//ns:sitemap/ns:loc', ns):
                if loc.text:
                    procesar(loc.text.strip(), profundidad + 1)
            for loc in root.findall('.//ns:url/ns:loc', ns):
                if loc.text:
                    ruta = normalizar_ruta(loc.text.strip())
                    if ruta:
                        urls.add(ruta)
        except Exception:
            pass

    sitemap_url = BASE_URL.rstrip("/") + "/sitemap.xml"
    print(f"[SITEMAP] Procesando {sitemap_url} ...")
    procesar(sitemap_url)
    print(f"[SITEMAP] {len(urls)} URLs encontradas" if urls else "[SITEMAP] Sin URLs")
    return urls


def paginacion_inteligente(ruta_base: str, session: requests.Session) -> List[str]:
    validas: List[str] = []
    for n in range(2, 20):
        ruta = f"{ruta_base}/page/{n}"
        try:
            r = session.head(
                BASE_URL.rstrip("/") + ruta,
                headers=HEADERS, timeout=8, verify=False, allow_redirects=True,
            )
            if r.status_code == 200:
                validas.append(ruta)
            else:
                break
        except Exception:
            break
    return validas


# ─────────────────────────────────────────────
#  SESIÓN HTTP
# ─────────────────────────────────────────────

def crear_sesion() -> requests.Session:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main() -> None:
    os.makedirs("data", exist_ok=True)
    open(OUTPUT_FILE, "w", encoding="utf-8").close()

    todo_el_texto:        List[str] = []
    visitadas:            Set[str]  = set()
    cola:                 List[str] = []
    cola_set:             Set[str]  = set()
    categorias_paginadas: Set[str]  = set()

    exitosas = fallidas = 0

    def encolar(ruta: str) -> None:
        if ruta and ruta not in visitadas and ruta not in cola_set:
            cola.append(ruta)
            cola_set.add(ruta)

    for p in PAGINAS_INICIALES:
        r = normalizar_ruta(p)
        if r:
            encolar(r)

    print("=" * 60)
    print("  Scraper — Correos Bolivia")
    print(f"  Base  : {BASE_URL}")
    print(f"  Límite: {MAX_PAGINAS} páginas")
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

                content_type = resp.headers.get("Content-Type", "")
                if "xml" in content_type and "html" not in content_type:
                    print("       [XML] omitiendo")
                    fallidas += 1
                    continue

                html = resp.content.decode("utf-8", errors="replace")
                soup_raw = BeautifulSoup(html, "html.parser")

                # ── Links internos ──────────────────────────────────────
                nuevos = 0
                if len(visitadas) < MAX_PAGINAS:
                    for link in scrapear_links_internos(soup_raw):
                        if link not in visitadas and link not in cola_set:
                            encolar(link)
                            nuevos += 1

                # ── HOME "/" → secciones + links de Maps ───────────────
                if ruta.rstrip("/") == "":
                    # Secciones del footer (Servicios, Aplicativos, etc.)
                    secciones = extraer_secciones_home(soup_raw)
                    guardar_secciones(secciones, SECCIONES_FILE)
                    imprimir_secciones(secciones)

                    # Links de Google Maps en la home
                    links_home = extraer_coords_de_links(soup_raw)
                    if links_home:
                        print(f"       🔗 {len(links_home)} links de Maps en la home")

                # ── SUCURSALES "/contact-us" ────────────────────────────
                if ruta.rstrip("/") == "/contact-us":
                    sucursales = extraer_sucursales(soup_raw)
                    if sucursales:
                        guardar_sucursales(sucursales, SUCURSALES_FILE)
                        imprimir_sucursales(sucursales)

                # ── Paginación inteligente ──────────────────────────────
                ruta_base = ruta.rstrip("/")
                if (
                    ("/category/" in ruta or "/author/" in ruta)
                    and "/page/" not in ruta
                    and ruta_base not in categorias_paginadas
                ):
                    categorias_paginadas.add(ruta_base)
                    paginas = paginacion_inteligente(ruta_base, session)
                    for p in paginas:
                        encolar(p)
                    if paginas:
                        print(f"       → {len(paginas)} páginas de paginación")

                # ── Extraer texto limpio ────────────────────────────────
                titulo_tag  = soup_raw.find("title")
                titulo      = titulo_tag.get_text().strip() if titulo_tag else ""
                meta_desc   = soup_raw.find("meta", attrs={"name": "description"})
                descripcion = meta_desc.get("content", "").strip() if meta_desc else ""

                soup_limpio = BeautifulSoup(html, "html.parser")
                for tag in soup_limpio(TAGS_BASURA):
                    tag.decompose()

                texto = limpiar_texto(extraer_contenido_principal(soup_limpio))

                if texto and len(texto) > 80 and "sitemap" not in url_completa.lower():
                    partes = [f"\n{'='*60}", f"FUENTE: {url_completa}"]
                    if titulo:
                        partes.append(f"TÍTULO: {limpiar_encoding(titulo)}")
                    if descripcion:
                        partes.append(f"DESCRIPCIÓN: {limpiar_encoding(descripcion)}")
                    partes += [f"{'='*60}", texto, ""]

                    bloque = "\n".join(partes)
                    todo_el_texto.append(bloque)
                    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                        f.write(bloque)

                    print(f"       ✓ {len(texto):,} chars  +{nuevos} links")
                    exitosas += 1
                else:
                    print(f"       ⚠ Contenido insuficiente ({len(texto)} chars)")
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
        print("\n🛑 Interrumpido — guardando progreso...")

    contenido_final = re.sub(r'\n{4,}', '\n\n', "\n".join(todo_el_texto)).strip()
    if contenido_final:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(contenido_final)
        print(f"\n{'='*60}")
        print("  SCRAPING COMPLETADO")
        print(f"  Texto      : {OUTPUT_FILE}")
        print(f"  Sucursales : {SUCURSALES_FILE}")
        print(f"  Secciones  : {SECCIONES_FILE}")
        print(f"  Caracteres : {len(contenido_final):,}")
        print(f"  Exitosas   : {exitosas}")
        print(f"  Fallidas   : {fallidas}")
        print(f"{'='*60}")
        print("\n→ Borra chroma_db/ y ejecuta: python chatbot.py")
    else:
        print("\n⚠ No se extrajo contenido útil.")


if __name__ == "__main__":
    main()