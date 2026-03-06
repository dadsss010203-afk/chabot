#!/usr/bin/env python3
"""
=============================================================================
    SCRAPER COMPLETO - CORREOS BOLIVIA
    Version: 2.0
=============================================================================
    Descripcion:
        Scraper completo para extraer informacion del sitio web de la
        Agencia Boliviana de Correos (correos.gob.bo), incluyendo:
        - Contenido textual de todas las paginas
        - Sucursales con coordenadas geograficas
        - Enlaces directos a Google Maps
        - Secciones del sitio (servicios, aplicativos)

    Uso:
        python scraper_correos_bolivia.py

    Requisitos:
        pip install requests beautifulsoup4

    Salida:
        - data/correos_bolivia.txt (contenido textual)
        - data/sucursales_contacto.json (sucursales con coordenadas)
        - data/secciones_home.json (secciones del footer)
        - data/estadisticas.json (estadisticas del scraping)
=============================================================================
"""

import re
import json
import os
import time
import unicodedata
import warnings
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, unquote
from typing import Optional, Set, List, Dict, Any
from datetime import datetime

import requests
import urllib3
from bs4 import BeautifulSoup

# Configuracion de warnings
warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# =============================================================================
#  CONFIGURACION CENTRALIZADA
# =============================================================================

class Config:
    """Configuracion del scraper."""

    BASE_URL = "https://correos.gob.bo"
    OUTPUT_DIR = "data"

    # Archivos de salida
    TEXT_FILE = os.path.join(OUTPUT_DIR, "correos_bolivia.txt")
    SUCURSALES_FILE = os.path.join(OUTPUT_DIR, "sucursales_contacto.json")
    SECCIONES_FILE = os.path.join(OUTPUT_DIR, "secciones_home.json")
    STATS_FILE = os.path.join(OUTPUT_DIR, "estadisticas.json")

    # Limites
    MAX_PAGINAS = 150
    REQUEST_TIMEOUT = 20
    DELAY_REQUESTS = 0.3

    # Headers HTTP
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }

    # Paginas iniciales
    PAGINAS_INICIALES = [
        "/", "/services", "/sp", "/servicio-encomienda-postal",
        "/me", "/eca", "/ems", "/realiza-envios-diarios-a",
        "/institucional", "/contact-us", "/noticias",
        "/about", "/filatelia", "/chasquiexpressbo",
    ]

    # Tags HTML a eliminar
    TAGS_ELIMINAR = {
        "script", "style", "form", "iframe", "noscript", "svg",
        "button", "input", "select", "textarea", "meta", "link",
        "nav", "header", "footer", "aside",
    }

    # Selectores para contenido principal
    SELECTORES_CONTENIDO = [
        "main", "article", "#content", ".content", "#main", ".main",
        ".entry-content", ".post-content", ".post", ".page-content",
        ".site-content", "#primary", ".primary",
        ".elementor-section", ".wp-block-group", ".wp-block-post-content",
    ]

    # Horario por defecto
    HORARIO_DEFAULT = "Lunes a viernes: 8:30 a 16:30"

    # Email por defecto
    EMAIL_DEFAULT = "agbc@correos.gob.bo"


# =============================================================================
#  ESTADISTICAS
# =============================================================================

class Estadisticas:
    """Almacena estadisticas del scraping."""

    def __init__(self):
        self.inicio = datetime.now().isoformat()
        self.fin = None
        self.paginas_exitosas = 0
        self.paginas_fallidas = 0
        self.caracteres_extraidos = 0
        self.sucursales_encontradas = 0
        self.errores = []

    def to_dict(self) -> Dict:
        return {
            "inicio": self.inicio,
            "fin": self.fin,
            "paginas_exitosas": self.paginas_exitosas,
            "paginas_fallidas": self.paginas_fallidas,
            "caracteres_extraidos": self.caracteres_extraidos,
            "sucursales_encontradas": self.sucursales_encontradas,
            "errores": self.errores[:20],  # Limitar errores guardados
        }


# =============================================================================
#  FUNCIONES DE UTILIDAD
# =============================================================================

def limpiar_texto(texto: str) -> str:
    """
    Limpia y normaliza texto eliminando caracteres no deseados.

    Args:
        texto: Texto a limpiar

    Returns:
        Texto limpio y normalizado
    """
    if not texto:
        return ""

    texto = unicodedata.normalize("NFKC", texto)
    texto = re.sub(r'https?://\S+', '', texto)
    texto = re.sub(r'\S+@\S+\.\S+', '', texto)
    texto = re.sub(r'[_\-=*#]{3,}', '', texto)
    texto = re.sub(r'^\s*\d+\s*$', '', texto, flags=re.MULTILINE)
    texto = re.sub(r' {2,}', ' ', texto)
    texto = re.sub(r'\n{3,}', '\n\n', texto)

    lineas = [
        l.strip() for l in texto.splitlines()
        if len(l.strip()) > 5
        and not re.match(r'^[\d\s.,;:\-/()\[\]]+$', l.strip())
    ]

    return "\n".join(lineas)


def normalizar_ruta(href: str, base_netloc: str) -> Optional[str]:
    """
    Normaliza una URL a ruta relativa interna.

    Args:
        href: URL o ruta a normalizar
        base_netloc: Dominio base para filtrar URLs externas

    Returns:
        Ruta normalizada o None si debe ignorarse
    """
    if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
        return None

    try:
        parsed = urlparse(href)

        if parsed.netloc and parsed.netloc != base_netloc:
            return None

        ruta = parsed.path or "/"

        # Ignorar extensiones de archivo
        if re.search(r'\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?|css|js|apk|exe|xml|mp[34])$', ruta, re.I):
            return None

        # Ignorar rutas administrativas
        if re.search(r'(wp-admin|wp-login|login|logout|register|cart|checkout|feed)', ruta, re.I):
            return None

        return ruta.rstrip("/") or "/"

    except Exception:
        return None


def validar_coordenadas_bolivia(lat: float, lng: float) -> bool:
    """
    Valida que las coordenadas esten dentro de Bolivia.

    Args:
        lat: Latitud
        lng: Longitud

    Returns:
        True si las coordenadas estan en Bolivia
    """
    return -23 < lat < -9 and -70 < lng < -57


def generar_enlaces_mapas(lat: float, lng: float, zoom: int = 17) -> Dict[str, str]:
    """
    Genera diferentes formatos de enlaces a Google Maps.

    Args:
        lat: Latitud
        lng: Longitud
        zoom: Nivel de zoom

    Returns:
        Diccionario con URLs para diferentes propositos
    """
    return {
        "mapa": f"https://www.google.com/maps/@{lat},{lng},{zoom}z",
        "direcciones": f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}",
        "embed": f"https://maps.google.com/maps?q={lat},{lng}&t=m&z={zoom}&output=embed",
        "busqueda": f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    }


# =============================================================================
#  EXTRACTOR DE COORDENADAS
# =============================================================================

class ExtractorCoordenadas:
    """Extrae coordenadas de iframes de Google Maps."""

    PATRON_COORDS = re.compile(r'[?&]q=(-?\d+\.\d+)%2C%20(-?\d+\.\d+)')

    @classmethod
    def de_url(cls, url: str) -> Optional[Dict[str, float]]:
        """
        Extrae coordenadas de una URL de Google Maps.

        Args:
            url: URL del iframe

        Returns:
            Diccionario con lat y lng, o None
        """
        url_decoded = url.replace('&#038;', '&')

        match = cls.PATRON_COORDS.search(url_decoded)
        if match:
            try:
                lat = float(match.group(1))
                lng = float(match.group(2))

                if validar_coordenadas_bolivia(lat, lng):
                    return {"lat": lat, "lng": lng}
            except ValueError:
                pass

        return None

    @classmethod
    def de_soup(cls, soup: BeautifulSoup) -> List[Dict[str, float]]:
        """
        Extrae coordenadas de todos los iframes de una pagina.

        Args:
            soup: Objeto BeautifulSoup

        Returns:
            Lista de coordenadas
        """
        coordenadas = []

        for iframe in soup.find_all("iframe"):
            src = iframe.get("src", "") or iframe.get("data-src", "")

            if "maps.google" not in src and "google.com/maps" not in src:
                continue

            coord = cls.de_url(src)
            if coord:
                coordenadas.append(coord)

        return coordenadas


# =============================================================================
#  EXTRACTOR DE SUCURSALES
# =============================================================================

class ExtractorSucursales:
    """Extrae informacion de sucursales de la pagina de contacto."""

    def __init__(self, html: str, url: str):
        self.soup = BeautifulSoup(html, "html.parser")
        self.url = url
        self.coordenadas = ExtractorCoordenadas.de_soup(self.soup)

    def extraer(self) -> List[Dict[str, Any]]:
        """
        Extrae todas las sucursales.

        Returns:
            Lista de sucursales con coordenadas y enlaces
        """
        sucursales = []

        for h3 in self.soup.find_all("h3", class_="elementor-heading-title"):
            titulo = limpiar_texto(h3.get_text())

            if not re.search(r'Oficina Central|Regional', titulo, re.IGNORECASE):
                continue

            seccion = h3.find_parent("section")
            if not seccion:
                continue

            indice = len(sucursales)

            sucursal = {
                "nombre": titulo,
                "direccion": self._extraer_campo(seccion, "Direcci"),
                "telefono": self._extraer_campo(seccion, "Tel"),
                "email": self._extraer_campo(seccion, "Email") or Config.EMAIL_DEFAULT,
                "horario": Config.HORARIO_DEFAULT,
                "lat": None,
                "lng": None,
                "enlaces": {},
                "fuente": self.url
            }

            # Asignar coordenadas
            if indice < len(self.coordenadas):
                coord = self.coordenadas[indice]
                sucursal["lat"] = coord["lat"]
                sucursal["lng"] = coord["lng"]
                sucursal["enlaces"] = generar_enlaces_mapas(coord["lat"], coord["lng"])

            sucursales.append(sucursal)

        return sucursales

    def _extraer_campo(self, seccion: BeautifulSoup, nombre: str) -> str:
        """Extrae un campo especifico de la seccion."""
        for wrapper in seccion.find_all("div", class_="elementor-image-box-wrapper"):
            titulo_elem = wrapper.find("h4", class_="elementor-image-box-title")
            if not titulo_elem:
                continue

            if nombre.lower() in limpiar_texto(titulo_elem.get_text()).lower():
                valor_elem = wrapper.find("p", class_="elementor-image-box-description")
                if valor_elem:
                    return limpiar_texto(valor_elem.get_text())

        return ""


# =============================================================================
#  EXTRACTOR DE SECCIONES DEL HOME
# =============================================================================

class ExtractorSecciones:
    """Extrae secciones del footer/home."""

    def __init__(self, html: str):
        self.soup = BeautifulSoup(html, "html.parser")

    def extraer(self) -> Dict[str, List[str]]:
        """
        Extrae las secciones del footer.

        Returns:
            Diccionario con secciones y sus items
        """
        secciones = {}

        footer = self.soup.find("footer") or self.soup

        for bloque in footer.find_all(["div", "section", "nav"]):
            titulo_tag = bloque.find(['h2', 'h3', 'h4', 'h5'])
            if not titulo_tag:
                continue

            titulo = limpiar_texto(titulo_tag.get_text())
            if not titulo or len(titulo) < 3:
                continue

            items = []
            for li in bloque.find_all("li"):
                texto = limpiar_texto(li.get_text())
                if texto and 2 < len(texto) < 100:
                    items.append(texto)

            if items:
                secciones[titulo] = list(dict.fromkeys(items))

        return secciones


# =============================================================================
#  CLIENTE HTTP
# =============================================================================

class ClienteHTTP:
    """Cliente HTTP con reintentos."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(Config.HEADERS)

        # Configurar reintentos
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry = Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def obtener(self, url: str) -> Optional[str]:
        """
        Obtiene el contenido HTML de una URL.

        Args:
            url: URL a descargar

        Returns:
            HTML si es exitoso, None en caso contrario
        """
        try:
            respuesta = self.session.get(
                url,
                timeout=Config.REQUEST_TIMEOUT,
                verify=False,
                allow_redirects=True
            )
            respuesta.raise_for_status()

            content_type = respuesta.headers.get("Content-Type", "")
            if "xml" in content_type and "html" not in content_type:
                return None

            return respuesta.text

        except requests.exceptions.Timeout:
            print(f"       [ERROR] Timeout")
            return None
        except requests.exceptions.ConnectionError:
            print(f"       [ERROR] Conexion fallida")
            return None
        except requests.exceptions.HTTPError as e:
            print(f"       [ERROR] HTTP {e.response.status_code}")
            return None
        except Exception as e:
            print(f"       [ERROR] {type(e).__name__}")
            return None

    def cerrar(self):
        """Cierra la sesion."""
        self.session.close()


# =============================================================================
#  SCRAPER PRINCIPAL
# =============================================================================

class ScraperCorreosBolivia:
    """Scraper principal para Correos Bolivia."""

    def __init__(self):
        self.config = Config()
        self.stats = Estadisticas()
        self.cliente = ClienteHTTP()
        self.base_netloc = urlparse(self.config.BASE_URL).netloc

        self.visitadas: Set[str] = set()
        self.cola: List[str] = []
        self.cola_set: Set[str] = set()

    def ejecutar(self):
        """Ejecuta el scraper completo."""
        self._iniciar()

        try:
            # Procesar sitemap
            self._procesar_sitemap()

            # Agregar paginas iniciales
            for pagina in self.config.PAGINAS_INICIALES:
                ruta = normalizar_ruta(pagina, self.base_netloc)
                if ruta:
                    self._encolar(ruta)

            print(f"[INICIO] {len(self.cola)} URLs en cola\n")

            # Procesar cola
            while self.cola and len(self.visitadas) < self.config.MAX_PAGINAS:
                ruta = self.cola.pop(0)
                self.cola_set.discard(ruta)
                self._procesar_pagina(ruta)

        except KeyboardInterrupt:
            print("\n[INFO] Interrumpido por usuario")

        finally:
            self._finalizar()

    def _iniciar(self):
        """Inicializa el scraper."""
        os.makedirs(self.config.OUTPUT_DIR, exist_ok=True)
        open(self.config.TEXT_FILE, "w", encoding="utf-8").close()

        print("=" * 70)
        print("    SCRAPER - CORREOS BOLIVIA")
        print("=" * 70)
        print(f"    Base: {self.config.BASE_URL}")
        print(f"    Limite: {self.config.MAX_PAGINAS} paginas")
        print("=" * 70)

    def _finalizar(self):
        """Finaliza el scraper."""
        self.cliente.cerrar()
        self.stats.fin = datetime.now().isoformat()

        # Guardar estadisticas
        with open(self.config.STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.stats.to_dict(), f, ensure_ascii=False, indent=2)

        print("\n" + "=" * 70)
        print("    SCRAPING COMPLETADO")
        print("=" * 70)
        print(f"    Archivos generados:")
        print(f"      - {self.config.TEXT_FILE}")
        print(f"      - {self.config.SUCURSALES_FILE}")
        print(f"      - {self.config.SECCIONES_FILE}")
        print(f"      - {self.config.STATS_FILE}")
        print(f"    Estadisticas:")
        print(f"      - Paginas exitosas: {self.stats.paginas_exitosas}")
        print(f"      - Paginas fallidas: {self.stats.paginas_fallidas}")
        print(f"      - Caracteres extraidos: {self.stats.caracteres_extraidos:,}")
        print(f"      - Sucursales encontradas: {self.stats.sucursales_encontradas}")
        print("=" * 70)

    def _encolar(self, ruta: str):
        """Agrega una ruta a la cola."""
        if ruta and ruta not in self.visitadas and ruta not in self.cola_set:
            self.cola.append(ruta)
            self.cola_set.add(ruta)

    def _procesar_sitemap(self):
        """Procesa el sitemap del sitio."""
        sitemap_url = f"{self.config.BASE_URL}/sitemap.xml"
        print(f"[SITEMAP] Procesando: {sitemap_url}")

        urls = self._extraer_urls_sitemap(sitemap_url)
        for url in urls:
            self._encolar(url)

        print(f"[SITEMAP] {len(urls)} URLs encontradas")

    def _extraer_urls_sitemap(self, url: str, profundidad: int = 0) -> Set[str]:
        """Extrae URLs de un sitemap."""
        urls: Set[str] = set()

        if profundidad > 3:
            return urls

        html = self.cliente.obtener(url)
        if not html:
            return urls

        try:
            root = ET.fromstring(html)
            ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

            # Sitemaps anidados
            for loc in root.findall('.//ns:sitemap/ns:loc', ns):
                if loc.text:
                    sub_urls = self._extraer_urls_sitemap(loc.text.strip(), profundidad + 1)
                    urls.update(sub_urls)

            # URLs directas
            for loc in root.findall('.//ns:url/ns:loc', ns):
                if loc.text:
                    ruta = normalizar_ruta(loc.text.strip(), self.base_netloc)
                    if ruta:
                        urls.add(ruta)

        except ET.ParseError:
            pass

        return urls

    def _procesar_pagina(self, ruta: str):
        """Procesa una pagina individual."""
        if ruta in self.visitadas:
            return

        self.visitadas.add(ruta)
        url_completa = f"{self.config.BASE_URL.rstrip('/')}{ruta}"

        print(f"[{len(self.visitadas):>3}/{self.config.MAX_PAGINAS}] {url_completa} (cola: {len(self.cola)})")

        html = self.cliente.obtener(url_completa)
        if not html:
            self.stats.paginas_fallidas += 1
            return

        try:
            soup_raw = BeautifulSoup(html, "html.parser")

            # Extraer links
            if len(self.visitadas) < self.config.MAX_PAGINAS:
                nuevos = 0
                for a in soup_raw.find_all("a", href=True):
                    link = normalizar_ruta(a["href"], self.base_netloc)
                    if link and link not in self.visitadas and link not in self.cola_set:
                        self._encolar(link)
                        nuevos += 1

                if nuevos:
                    print(f"       +{nuevos} links")

            # Procesar paginas especiales
            ruta_norm = ruta.rstrip("/") or "/"

            # HOME - extraer secciones
            if ruta_norm == "/":
                self._procesar_home(soup_raw)

            # CONTACTO - extraer sucursales
            elif ruta_norm == "/contact-us":
                self._procesar_contacto(soup_raw, url_completa)

            # Extraer texto
            self._extraer_texto(soup_raw, html, url_completa)

        except Exception as e:
            self.stats.paginas_fallidas += 1
            self.stats.errores.append(f"{url_completa}: {str(e)}")
            print(f"       [ERROR] {e}")

        time.sleep(self.config.DELAY_REQUESTS)

    def _procesar_home(self, soup: BeautifulSoup):
        """Procesa la pagina principal."""
        extractor = ExtractorSecciones(str(soup))
        secciones = extractor.extraer()

        if secciones:
            with open(self.config.SECCIONES_FILE, "w", encoding="utf-8") as f:
                json.dump(secciones, f, ensure_ascii=False, indent=2)

            total = sum(len(v) for v in secciones.values())
            print(f"       {total} items en {len(secciones)} secciones")

    def _procesar_contacto(self, soup: BeautifulSoup, url: str):
        """Procesa la pagina de contacto."""
        extractor = ExtractorSucursales(str(soup), url)
        sucursales = extractor.extraer()

        if sucursales:
            with open(self.config.SUCURSALES_FILE, "w", encoding="utf-8") as f:
                json.dump(sucursales, f, ensure_ascii=False, indent=2)

            self.stats.sucursales_encontradas = len(sucursales)
            print(f"       {len(sucursales)} sucursales encontradas")

    def _extraer_texto(self, soup_raw: BeautifulSoup, html: str, url: str):
        """Extrae el texto de una pagina."""
        # Limpiar HTML
        soup_limpio = BeautifulSoup(html, "html.parser")
        for tag_name in self.config.TAGS_ELIMINAR:
            for tag in soup_limpio.find_all(tag_name):
                tag.decompose()

        # Extraer contenido
        texto = ""
        for selector in self.config.SELECTORES_CONTENIDO:
            nodo = soup_limpio.select_one(selector)
            if nodo:
                texto = nodo.get_text(separator="\n", strip=True)
                if len(texto) > 100:
                    break

        if not texto and soup_limpio.body:
            texto = soup_limpio.body.get_text(separator="\n", strip=True)

        texto = limpiar_texto(texto)

        if len(texto) > 100 and "sitemap" not in url.lower():
            # Extraer metadatos
            titulo_tag = soup_raw.find("title")
            titulo = limpiar_texto(titulo_tag.get_text()) if titulo_tag else ""

            meta_desc = soup_raw.find("meta", attrs={"name": "description"})
            descripcion = limpiar_texto(meta_desc.get("content", "")) if meta_desc else ""

            # Formatear
            partes = [f"\n{'='*60}", f"FUENTE: {url}"]
            if titulo:
                partes.append(f"TITULO: {titulo}")
            if descripcion:
                partes.append(f"DESCRIPCION: {descripcion}")
            partes.extend([f"{'='*60}", texto, ""])

            bloque = "\n".join(partes)

            with open(self.config.TEXT_FILE, "a", encoding="utf-8") as f:
                f.write(bloque)

            self.stats.caracteres_extraidos += len(texto)
            self.stats.paginas_exitosas += 1
            print(f"       {len(texto):,} caracteres")
        else:
            self.stats.paginas_fallidas += 1
            print(f"       Contenido insuficiente")


# =============================================================================
#  PUNTO DE ENTRADA
# =============================================================================

def main():
    """Funcion principal."""
    scraper = ScraperCorreosBolivia()
    scraper.ejecutar()


if __name__ == "__main__":
    main()
