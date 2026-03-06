#!/usr/bin/env python3
"""
=============================================================================
    SCRAPER SUPER POTENTE - CORREOS BOLIVIA
    Version: 3.0 - MEJORADO
=============================================================================
    Descripcion:
        Scraper completo y potente para extraer informacion del sitio web de la
        Agencia Boliviana de Correos (correos.gob.bo), incluyendo:
        - Contenido textual de TODAS las paginas
        - Sucursales con coordenadas geograficas
        - Enlaces directos a Google Maps
        - Secciones del sitio (servicios, aplicativos)
        - DESCARGA AUTOMATICA DE PDFs
        - Extraccion de aplicaciones y servicios
        - Historia e informacion institucional
        - Noticias y eventos
        - Filatelia y productos

    Uso:
        python scraper_correos_bolivia_super.py

    Requisitos:
        pip install requests beautifulsoup4 PyPDF2

    Salida:
        - data/correos_bolivia_completo.txt (contenido textual)
        - data/sucursales_contacto.json (sucursales con coordenadas)
        - data/secciones_home.json (secciones del footer)
        - data/estadisticas.json (estadisticas del scraping)
        - data/aplicaciones_servicios.json (apps y servicios)
        - data/historia_institucional.json (historia)
        - data/noticias_eventos.json (noticias)
        - data/pdfs_descargados/ (carpeta con PDFs)
        - data/pdfs_contenido.json (contenido extraido de PDFs)
=============================================================================
"""

import re
import json
import os
import time
import unicodedata
import warnings
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, unquote, urljoin
from typing import Optional, Set, List, Dict, Any, Tuple
from datetime import datetime
from pathlib import Path
import hashlib

import requests
import urllib3
from bs4 import BeautifulSoup, Tag

# Configuracion de warnings
warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Intentar importar PyPDF2 para extraer texto de PDFs
try:
    import PyPDF2
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("[WARNING] PyPDF2 no instalado. Instala con: pip install PyPDF2")


# =============================================================================
#  CONFIGURACION CENTRALIZADA
# =============================================================================

class Config:
    """Configuracion del scraper."""

    BASE_URL = "https://correos.gob.bo"
    OUTPUT_DIR = "data"
    PDF_DIR = os.path.join(OUTPUT_DIR, "pdfs_descargados")

    # Archivos de salida
    TEXT_FILE = os.path.join(OUTPUT_DIR, "correos_bolivia_completo.txt")
    SUCURSALES_FILE = os.path.join(OUTPUT_DIR, "sucursales_contacto.json")
    SECCIONES_FILE = os.path.join(OUTPUT_DIR, "secciones_home.json")
    STATS_FILE = os.path.join(OUTPUT_DIR, "estadisticas.json")
    APLICACIONES_FILE = os.path.join(OUTPUT_DIR, "aplicaciones_servicios.json")
    HISTORIA_FILE = os.path.join(OUTPUT_DIR, "historia_institucional.json")
    NOTICIAS_FILE = os.path.join(OUTPUT_DIR, "noticias_eventos.json")
    PDFS_FILE = os.path.join(OUTPUT_DIR, "pdfs_contenido.json")
    ENLACES_FILE = os.path.join(OUTPUT_DIR, "enlaces_interes.json")
    PRODUCTOS_FILE = os.path.join(OUTPUT_DIR, "productos_servicios.json")

    # Limites
    MAX_PAGINAS = 300  # Aumentado
    REQUEST_TIMEOUT = 30
    DELAY_REQUESTS = 0.2  # Reducido para mayor velocidad
    MAX_PDFS = 100  # Limite de PDFs a descargar

    # Headers HTTP
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }

    # Paginas iniciales - EXPANDIDAS
    PAGINAS_INICIALES = [
        # Principales
        "/", "/services", "/sp", "/servicio-encomienda-postal",
        "/me", "/eca", "/ems", "/realiza-envios-diarios-a",
        "/institucional", "/contact-us", "/noticias",
        "/about", "/filatelia", "/chasquiexpressbo",
        
        # Servicios adicionales
        "/servicios", "/servicio-postal", "/servicio-telegramas",
        "/servicio-giros", "/servicio-casillas", "/servicio-listas",
        "/servicio-apartados", "/envios-nacionales", "/envios-internacionales",
        
        # Aplicativos y herramientas
        "/aplicativos", "/herramientas", "/calculadora",
        "/rastreo", "/tracking", "/seguimiento", "/track",
        "/cotizador", "/tarifas", "/precios",
        
        # Institucional - HISTORIA
        "/historia", "/resena-historica", "/nuestra-historia",
        "/quienes-somos", "/mision-vision", "/valores",
        "/organigrama", "/autoridades", "/directorio",
        "/marco-legal", "/normativa", "/reglamentos",
        
        # Transparencia
        "/transparencia", "/rendicion-cuentas", "/estados-financieros",
        "/contrataciones", "/convocatorias", "/concursos",
        
        # Productos y servicios
        "/productos", "/estampillas", "/colecciones",
        "/filatelia", "/souvenirs", "/merchandising",
        
        # Noticias y eventos
        "/noticias", "/eventos", "/comunicados",
        "/boletines", "/prensa", "/galeria",
        
        # Atencion al cliente
        "/atencion-cliente", "/faq", "/preguntas-frecuentes",
        "/reclamos", "/sugerencias", "/buzon",
        "/terminos", "/condiciones", "/politicas",
        
        # Descargas y recursos
        "/descargas", "/documentos", "/recursos",
        "/manuales", "/guias", "/formatos",
        
        # Redes y sucursales
        "/red-agencias", "/agencias", "/oficinas",
        "/sucursales", "/cobertura", "/red-nacional",
        
        # Especiales
        "/casilleros", "/casilla-postal", "/apartado-postal",
        "/encomiendas", "/paquetes", "/cartas",
        "/giros-postales", "/telegramas", "/telegrafos",
        
        # EMS y servicios premium
        "/ems", "/ems-internacional", "/envio-expreso",
        "/courier", "/mensajeria", "/logistica",
        
        # Otros
        "/glosario", "/terminologia", "/diccionario",
        "/enlaces", "/links", "/sitios-interes",
        "/mapa-sitio", "/sitemap",
    ]

    # Tags HTML a eliminar
    TAGS_ELIMINAR = {
        "script", "style", "form", "iframe", "noscript", "svg",
        "button", "input", "select", "textarea", "meta", "link",
    }

    # Selectores para contenido principal - EXPANDIDOS
    SELECTORES_CONTENIDO = [
        # WordPress y CMS comunes
        "main", "article", "#content", ".content", "#main", ".main",
        ".entry-content", ".post-content", ".post", ".page-content",
        ".site-content", "#primary", ".primary",
        
        # Elementor
        ".elementor-section", ".elementor-widget-container",
        ".elementor-text-editor", ".elementor-heading-title",
        ".wp-block-group", ".wp-block-post-content",
        
        # Otros
        ".container", ".wrapper", ".page-wrapper",
        "#wrapper", ".main-content", "#main-content",
        ".single-content", ".archive-content",
        ".elementor-widget-theme-post-content",
        
        # Ultimo recurso
        "body",
    ]

    # Selectores para aplicaciones/servicios
    SELECTORES_APLICACIONES = [
        ".aplicativo", ".app", ".application",
        ".servicio", ".service", ".service-item",
        ".producto", ".product", ".product-item",
        ".card", ".card-item", ".feature",
        ".elementor-icon-box-wrapper", ".elementor-flip-box",
        ".elementor-image-box-wrapper",
    ]

    # Patrones para detectar tipo de contenido
    PATRONES_HISTORIA = [
        r'hist[oó]ria', r'rese[ñn]a', r'antecedente', r'fundaci[oó]n',
        r'trayectoria', r'tradici[oó]n', r'legado', r'a[ñn]os de servicio',
        r'nacimiento', r'origen', r'creaci[oó]n',
    ]

    PATRONES_APLICACION = [
        r'aplicativo', r'aplicaci[oó]n', r'app', r'sistema',
        r'plataforma', r'herramienta', r'software', r'portal',
        r'portal web', r'servicio en l[ií]nea', r'servicio digital',
    ]

    PATRONES_SERVICIO = [
        r'servicio', r'env[ií]o', r'correo', r'paquete',
        r'encomienda', r'carta', r'telegrama', r'giro',
        r'casilla', r'apartado', r'filatelia', r'estampilla',
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
        self.aplicaciones_encontradas = 0
        self.servicios_encontrados = 0
        self.noticias_encontradas = 0
        self.pdfs_descargados = 0
        self.pdfs_procesados = 0
        self.historia_encontrada = False
        self.errores = []

    def to_dict(self) -> Dict:
        return {
            "inicio": self.inicio,
            "fin": self.fin,
            "duracion_segundos": self._calcular_duracion(),
            "paginas_exitosas": self.paginas_exitosas,
            "paginas_fallidas": self.paginas_fallidas,
            "caracteres_extraidos": self.caracteres_extraidos,
            "sucursales_encontradas": self.sucursales_encontradas,
            "aplicaciones_encontradas": self.aplicaciones_encontradas,
            "servicios_encontrados": self.servicios_encontrados,
            "noticias_encontradas": self.noticias_encontradas,
            "pdfs_descargados": self.pdfs_descargados,
            "pdfs_procesados": self.pdfs_procesados,
            "historia_encontrada": self.historia_encontrada,
            "errores": self.errores[:30],
        }
    
    def _calcular_duracion(self) -> float:
        if self.inicio and self.fin:
            try:
                inicio = datetime.fromisoformat(self.inicio)
                fin = datetime.fromisoformat(self.fin)
                return (fin - inicio).total_seconds()
            except:
                pass
        return 0


# =============================================================================
#  FUNCIONES DE UTILIDAD
# =============================================================================

def limpiar_texto(texto: str) -> str:
    """
    Limpia y normaliza texto eliminando caracteres no deseados.
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
    texto = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', texto)

    lineas = [
        l.strip() for l in texto.splitlines()
        if len(l.strip()) > 3
        and not re.match(r'^[\d\s.,;:\-/()\[\]]+$', l.strip())
    ]

    return "\n".join(lineas)


def normalizar_ruta(href: str, base_netloc: str) -> Optional[str]:
    """
    Normaliza una URL a ruta relativa interna.
    """
    if not href or href.startswith(("javascript:", "#", "mailto:", "tel:", "data:", "blob:")):
        return None

    try:
        # Limpiar la URL
        href = href.strip()
        if href.startswith("//"):
            href = "https:" + href

        parsed = urlparse(href)

        # Verificar dominio
        if parsed.netloc and parsed.netloc != base_netloc:
            return None

        ruta = parsed.path or "/"

        # Ignorar extensiones de archivo no deseadas
        if re.search(r'\.(css|js|apk|exe|dmg|deb|rpm|zip|rar|7z|tar|gz|mp[34]|avi|mov|wmv|flv|wav|ogg|webp)$', ruta, re.I):
            return None

        # Ignorar rutas administrativas
        if re.search(r'(wp-admin|wp-login|wp-content/uploads|login|logout|register|cart|checkout|feed|xmlrpc)', ruta, re.I):
            return None

        # Decodificar URL
        ruta = unquote(ruta)

        return ruta.rstrip("/") or "/"

    except Exception:
        return None


def validar_coordenadas_bolivia(lat: float, lng: float) -> bool:
    """Valida que las coordenadas esten dentro de Bolivia."""
    return -23 < lat < -9 and -70 < lng < -57


def generar_enlaces_mapas(lat: float, lng: float, zoom: int = 17) -> Dict[str, str]:
    """Genera diferentes formatos de enlaces a Google Maps."""
    return {
        "mapa": f"https://www.google.com/maps/@{lat},{lng},{zoom}z",
        "direcciones": f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}",
        "embed": f"https://maps.google.com/maps?q={lat},{lng}&t=m&z={zoom}&output=embed",
        "busqueda": f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"
    }


def generar_hash_contenido(contenido: str) -> str:
    """Genera un hash MD5 del contenido para detectar duplicados."""
    return hashlib.md5(contenido.encode('utf-8', errors='ignore')).hexdigest()


def es_contenido_duplicado(texto: str, hashes_existentes: Set[str]) -> bool:
    """Verifica si el contenido ya fue extraido."""
    hash_contenido = generar_hash_contenido(texto)
    if hash_contenido in hashes_existentes:
        return True
    hashes_existentes.add(hash_contenido)
    return False


def detectar_tipo_contenido(texto: str, url: str) -> List[str]:
    """
    Detecta el tipo de contenido basado en el texto y URL.
    
    Returns:
        Lista de tipos detectados
    """
    tipos = []
    texto_lower = texto.lower()
    url_lower = url.lower()
    
    # Detectar historia
    for patron in Config.PATRONES_HISTORIA:
        if re.search(patron, texto_lower) or re.search(patron, url_lower):
            tipos.append("historia")
            break
    
    # Detectar aplicacion
    for patron in Config.PATRONES_APLICACION:
        if re.search(patron, texto_lower) or re.search(patron, url_lower):
            tipos.append("aplicacion")
            break
    
    # Detectar servicio
    for patron in Config.PATRONES_SERVICIO:
        if re.search(patron, texto_lower) or re.search(patron, url_lower):
            tipos.append("servicio")
            break
    
    # Detectar noticia
    if re.search(r'noticia|evento|comunicado|bolet[ií]n|prensa', texto_lower) or \
       re.search(r'/noticia|/evento|/comunicado|/prensa', url_lower):
        tipos.append("noticia")
    
    # Detectar producto
    if re.search(r'producto|estampilla|filatelia|souvenir|colecci[oó]n', texto_lower) or \
       re.search(r'/producto|/filatelia|/estampilla', url_lower):
        tipos.append("producto")
    
    # Detectar contacto
    if re.search(r'contacto|sucursal|oficina|agencia|direcci[oó]n|tel[eé]fono', texto_lower) or \
       re.search(r'/contact|/sucursal|/agencia', url_lower):
        tipos.append("contacto")
    
    # Detectar institucional
    if re.search(r'institucional|misi[oó]n|visi[oó]n|valor|autoridad|directorio', texto_lower) or \
       re.search(r'/institucional|/about|/quienes', url_lower):
        tipos.append("institucional")
    
    # Detectar normativo
    if re.search(r'normativa|reglamento|marco legal|ley|decreto|resoluci[oó]n', texto_lower) or \
       re.search(r'/normativa|/legal|/reglamento', url_lower):
        tipos.append("normativo")
    
    if not tipos:
        tipos.append("general")
    
    return tipos


# =============================================================================
#  EXTRACTOR DE COORDENADAS
# =============================================================================

class ExtractorCoordenadas:
    """Extrae coordenadas de iframes de Google Maps."""

    PATRON_COORDS = re.compile(r'[?&]q=(-?\d+\.\d+)%2C%20(-?\d+\.\d+)')
    PATRON_COORDS2 = re.compile(r'@(-?\d+\.\d+),(-?\d+\.\d+),\d+z')
    PATRON_COORDS3 = re.compile(r'll=(-?\d+\.\d+),(-?\d+\.\d+)')
    PATRON_COORDS4 = re.compile(r'center=(-?\d+\.\d+),(-?\d+\.\d+)')

    @classmethod
    def de_url(cls, url: str) -> Optional[Dict[str, float]]:
        """Extrae coordenadas de una URL de Google Maps."""
        url_decoded = url.replace('&#038;', '&').replace('&amp;', '&')

        patrones = [cls.PATRON_COORDS, cls.PATRON_COORDS2, cls.PATRON_COORDS3, cls.PATRON_COORDS4]

        for patron in patrones:
            match = patron.search(url_decoded)
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
        """Extrae coordenadas de todos los iframes de una pagina."""
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
        """Extrae todas las sucursales."""
        sucursales = []

        for h3 in self.soup.find_all("h3", class_="elementor-heading-title"):
            titulo = limpiar_texto(h3.get_text())

            if not re.search(r'Oficina Central|Regional|Agencia|Sucursal', titulo, re.IGNORECASE):
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
                "horario": self._extraer_campo(seccion, "Horario") or Config.HORARIO_DEFAULT,
                "lat": None,
                "lng": None,
                "enlaces": {},
                "fuente": self.url
            }

            if indice < len(self.coordenadas):
                coord = self.coordenadas[indice]
                sucursal["lat"] = coord["lat"]
                sucursal["lng"] = coord["lng"]
                sucursal["enlaces"] = generar_enlaces_mapas(coord["lat"], coord["lng"])

            sucursales.append(sucursal)

        # Intentar extraccion alternativa
        if not sucursales:
            sucursales = self._extraccion_alternativa()

        return sucursales

    def _extraccion_alternativa(self) -> List[Dict[str, Any]]:
        """Extraccion alternativa cuando la principal falla."""
        sucursales = []
        
        # Buscar cualquier estructura que parezca una sucursal
        contenedores = self.soup.find_all(["div", "section"], class_=re.compile(r'elementor-widget|oficina|sucursal|contact', re.I))
        
        for cont in contenedores:
            texto = cont.get_text(separator="\n", strip=True)
            
            if not re.search(r'direcci[oó]n|tel[eé]fono|email', texto, re.I):
                continue
            
            lineas = [l.strip() for l in texto.split('\n') if l.strip()]
            
            if len(lineas) < 2:
                continue
            
            sucursal = {
                "nombre": lineas[0] if lineas else "Sucursal",
                "direccion": "",
                "telefono": "",
                "email": Config.EMAIL_DEFAULT,
                "horario": Config.HORARIO_DEFAULT,
                "lat": None,
                "lng": None,
                "enlaces": {},
                "fuente": self.url,
                "texto_completo": texto
            }
            
            for linea in lineas[1:]:
                if re.search(r'direcci[oó]n|direc\.', linea, re.I):
                    sucursal["direccion"] = linea
                elif re.search(r'tel[eé]fono|tel\.|celular', linea, re.I):
                    sucursal["telefono"] = linea
                elif re.search(r'@', linea):
                    sucursal["email"] = linea
                elif re.search(r'horario|hora|atenci[oó]n', linea, re.I):
                    sucursal["horario"] = linea
            
            if sucursal["direccion"] or sucursal["telefono"]:
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
#  EXTRACTOR DE APLICACIONES Y SERVICIOS
# =============================================================================

class ExtractorAplicaciones:
    """Extrae informacion de aplicaciones y servicios."""

    def __init__(self, html: str, url: str):
        self.soup = BeautifulSoup(html, "html.parser")
        self.url = url

    def extraer(self) -> Dict[str, List[Dict[str, Any]]]:
        """Extrae aplicaciones y servicios."""
        resultado = {
            "aplicaciones": [],
            "servicios": [],
            "herramientas": [],
            "enlaces_externos": []
        }

        # Buscar tarjetas/widgets de Elementor
        for widget in self.soup.find_all(["div", "section"], class_=re.compile(r'elementor-widget|card|service|app', re.I)):
            app = self._extraer_de_widget(widget)
            if app:
                tipo = app.get("tipo", "servicio")
                if tipo in resultado:
                    resultado[tipo].append(app)

        # Buscar enlaces a aplicaciones
        for a in self.soup.find_all("a", href=True):
            href = a.get("href", "")
            texto = limpiar_texto(a.get_text())
            
            if not texto or len(texto) < 3:
                continue
            
            # Detectar aplicaciones/sistemas
            if re.search(r'aplicativo|sistema|plataforma|app|portal', texto, re.I) or \
               re.search(r'/app|/sistema|/portal|/aplicativo', href, re.I):
                
                enlace = {
                    "nombre": texto,
                    "url": href if href.startswith("http") else f"{Config.BASE_URL}{href}",
                    "descripcion": self._extraer_descripcion_cercana(a),
                    "tipo": "aplicacion",
                    "fuente": self.url
                }
                
                # Verificar si es enlace externo
                if urlparse(href).netloc and urlparse(href).netloc != urlparse(Config.BASE_URL).netloc:
                    resultado["enlaces_externos"].append(enlace)
                else:
                    resultado["aplicaciones"].append(enlace)

        # Buscar listas de servicios
        for ul in self.soup.find_all(["ul", "ol"]):
            items = []
            for li in ul.find_all("li"):
                texto = limpiar_texto(li.get_text())
                if texto and len(texto) > 3:
                    # Buscar enlace dentro del li
                    link = li.find("a")
                    if link:
                        items.append({
                            "texto": texto,
                            "url": link.get("href", "")
                        })
                    else:
                        items.append({"texto": texto})
            
            if len(items) > 2:  # Lista significativa
                # Clasificar por contexto
                padre = ul.find_parent(["div", "section", "article"])
                contexto = padre.get_text(separator=" ", strip=True).lower() if padre else ""
                
                if re.search(r'servicio|producto|envio', contexto, re.I):
                    resultado["servicios"].extend([{"item": i, "fuente": self.url} for i in items])

        return resultado

    def _extraer_de_widget(self, widget: Tag) -> Optional[Dict[str, Any]]:
        """Extrae informacion de un widget de Elementor."""
        # Buscar titulo
        titulo = None
        for tag in widget.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            texto = limpiar_texto(tag.get_text())
            if texto and len(texto) > 3:
                titulo = texto
                break

        if not titulo:
            return None

        # Buscar descripcion
        descripcion = None
        for tag in widget.find_all(["p", "div"], class_=re.compile(r'description|content|text', re.I)):
            texto = limpiar_texto(tag.get_text())
            if texto and len(texto) > 20 and texto != titulo:
                descripcion = texto
                break

        # Buscar enlace
        enlace = None
        for a in widget.find_all("a", href=True):
            href = a.get("href", "")
            if href and not href.startswith(("#", "javascript:", "tel:", "mailto:")):
                enlace = href
                break

        # Determinar tipo
        texto_completo = widget.get_text(separator=" ", strip=True).lower()
        tipo = "servicio"
        if re.search(r'aplicativo|app|sistema|plataforma', titulo.lower() + texto_completo):
            tipo = "aplicacion"
        elif re.search(r'herramienta|calculadora|rastreo|tracking|cotizador', titulo.lower() + texto_completo):
            tipo = "herramienta"

        return {
            "nombre": titulo,
            "descripcion": descripcion,
            "url": enlace,
            "tipo": tipo,
            "fuente": self.url
        }

    def _extraer_descripcion_cercana(self, elemento: Tag) -> str:
        """Extrae descripcion del elemento mas cercano."""
        # Buscar en el padre
        padre = elemento.find_parent(["div", "section", "article"])
        if padre:
            for p in padre.find_all("p"):
                texto = limpiar_texto(p.get_text())
                if texto and len(texto) > 20:
                    return texto[:200]
        return ""


# =============================================================================
#  EXTRACTOR DE HISTORIA
# =============================================================================

class ExtractorHistoria:
    """Extrae informacion historica."""

    def __init__(self, html: str, url: str):
        self.soup = BeautifulSoup(html, "html.parser")
        self.url = url

    def extraer(self) -> Optional[Dict[str, Any]]:
        """Extrae contenido historico."""
        # Obtener todo el texto
        for tag in self.soup.find_all(Config.TAGS_ELIMINAR):
            tag.decompose()

        texto = ""
        for selector in Config.SELECTORES_CONTENIDO:
            nodo = self.soup.select_one(selector)
            if nodo:
                texto = nodo.get_text(separator="\n", strip=True)
                if len(texto) > 200:
                    break

        if not texto and self.soup.body:
            texto = self.soup.body.get_text(separator="\n", strip=True)

        texto = limpiar_texto(texto)

        # Verificar si contiene historia
        if not re.search(r'hist[oó]ria|rese[ñn]a|antecedente|fundaci[oó]n|trayectoria|tradici[oó]n', texto, re.I):
            return None

        # Extraer titulo
        titulo = ""
        for tag in self.soup.find_all(["h1", "h2", "h3"]):
            t = limpiar_texto(tag.get_text())
            if t:
                titulo = t
                break

        # Extraer fechas/anos mencionados
        anos = re.findall(r'\b(18\d{2}|19\d{2}|20\d{2})\b', texto)
        anos_unicos = sorted(set(anos))

        return {
            "titulo": titulo,
            "contenido": texto,
            "anos_mencionados": anos_unicos,
            "url": self.url,
            "longitud": len(texto)
        }


# =============================================================================
#  EXTRACTOR DE NOTICIAS
# =============================================================================

class ExtractorNoticias:
    """Extrae noticias y eventos."""

    def __init__(self, html: str, url: str):
        self.soup = BeautifulSoup(html, "html.parser")
        self.url = url

    def extraer(self) -> List[Dict[str, Any]]:
        """Extrae noticias de la pagina."""
        noticias = []

        # Buscar articulos o entradas
        for article in self.soup.find_all(["article", "div"], class_=re.compile(r'post|article|news|noticia|entry', re.I)):
            noticia = self._extraer_noticia(article)
            if noticia:
                noticias.append(noticia)

        # Si no encontro, buscar estructura alternativa
        if not noticias:
            for widget in self.soup.find_all(["div", "section"], class_=re.compile(r'elementor-widget|card|item', re.I)):
                noticia = self._extraer_noticia(widget)
                if noticia:
                    noticias.append(noticia)

        return noticias

    def _extraer_noticia(self, contenedor: Tag) -> Optional[Dict[str, Any]]:
        """Extrae una noticia de un contenedor."""
        # Titulo
        titulo = ""
        for tag in contenedor.find_all(["h1", "h2", "h3", "h4", "h5"]):
            texto = limpiar_texto(tag.get_text())
            if texto and len(texto) > 5:
                titulo = texto
                break

        if not titulo:
            return None

        # Descripcion/extracto
        descripcion = ""
        for tag in contenedor.find_all(["p", "div"], class_=re.compile(r'excerpt|summary|description|content', re.I)):
            texto = limpiar_texto(tag.get_text())
            if texto and len(texto) > 30 and texto != titulo:
                descripcion = texto
                break

        # Si no hay descripcion, tomar el primer p
        if not descripcion:
            for p in contenedor.find_all("p"):
                texto = limpiar_texto(p.get_text())
                if texto and len(texto) > 30 and texto != titulo:
                    descripcion = texto
                    break

        # Fecha
        fecha = ""
        for tag in contenedor.find_all(["time", "span"], class_=re.compile(r'date|fecha|time', re.I)):
            texto = limpiar_texto(tag.get_text())
            if texto:
                fecha = texto
                break

        # Buscar patron de fecha en el texto
        if not fecha:
            match = re.search(r'(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4}|\d{1,2}\s+de\s+\w+\s+de\s+\d{4})', 
                            contenedor.get_text())
            if match:
                fecha = match.group(1)

        # Imagen
        imagen = ""
        for img in contenedor.find_all("img"):
            src = img.get("src", "")
            if src and not src.startswith("data:"):
                imagen = src
                break

        # Enlace
        enlace = ""
        for a in contenedor.find_all("a", href=True):
            href = a.get("href", "")
            if href and not href.startswith("#"):
                enlace = href
                break

        return {
            "titulo": titulo,
            "descripcion": descripcion[:500] if descripcion else "",
            "fecha": fecha,
            "imagen": imagen,
            "enlace": enlace if enlace.startswith("http") else f"{Config.BASE_URL}{enlace}",
            "fuente": self.url
        }


# =============================================================================
#  DESCARGADOR DE PDFs
# =============================================================================

class DescargadorPDFs:
    """Descarga y procesa archivos PDF."""

    def __init__(self, cliente: 'ClienteHTTP'):
        self.cliente = cliente
        self.pdfs_procesados: Set[str] = set()
        self.contenido_pdfs: List[Dict[str, Any]] = []

    def procesar_pdf(self, url: str, pagina_fuente: str) -> Optional[Dict[str, Any]]:
        """
        Descarga y extrae contenido de un PDF.

        Args:
            url: URL del PDF
            pagina_fuente: URL de la pagina donde se encontro el PDF

        Returns:
            Diccionario con informacion del PDF o None
        """
        if not PDF_SUPPORT:
            return None

        # Normalizar URL
        if not url.startswith("http"):
            url = urljoin(Config.BASE_URL, url)

        # Evitar duplicados
        if url in self.pdfs_procesados:
            return None

        # Verificar limite
        if len(self.pdfs_procesados) >= Config.MAX_PDFS:
            return None

        self.pdfs_procesados.add(url)

        # Descargar PDF
        print(f"       [PDF] Descargando: {url}")
        
        try:
            respuesta = self.cliente.session.get(
                url,
                timeout=Config.REQUEST_TIMEOUT,
                verify=False,
                stream=True
            )
            respuesta.raise_for_status()

            # Verificar que sea PDF
            content_type = respuesta.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
                return None

            # Generar nombre de archivo
            nombre_archivo = self._generar_nombre_archivo(url)
            ruta_archivo = os.path.join(Config.PDF_DIR, nombre_archivo)

            # Guardar PDF
            os.makedirs(Config.PDF_DIR, exist_ok=True)
            with open(ruta_archivo, "wb") as f:
                for chunk in respuesta.iter_content(chunk_size=8192):
                    f.write(chunk)

            print(f"       [PDF] Guardado: {nombre_archivo}")

            # Extraer texto del PDF
            texto_extraido = self._extraer_texto_pdf(ruta_archivo)

            pdf_info = {
                "url": url,
                "archivo_local": ruta_archivo,
                "nombre_archivo": nombre_archivo,
                "tamano_bytes": os.path.getsize(ruta_archivo),
                "texto_extraido": texto_extraido,
                "longitud_texto": len(texto_extraido) if texto_extraido else 0,
                "pagina_fuente": pagina_fuente,
                "descargado_en": datetime.now().isoformat()
            }

            self.contenido_pdfs.append(pdf_info)
            return pdf_info

        except Exception as e:
            print(f"       [PDF] Error descargando: {e}")
            return None

    def _generar_nombre_archivo(self, url: str) -> str:
        """Genera un nombre de archivo unico para el PDF."""
        parsed = urlparse(url)
        nombre = os.path.basename(parsed.path)
        
        if not nombre or not nombre.lower().endswith(".pdf"):
            nombre = f"documento_{len(self.pdfs_procesados)}.pdf"
        
        # Limpiar nombre
        nombre = re.sub(r'[^\w\-_\.]', '_', nombre)
        
        # Agregar hash si es muy largo
        if len(nombre) > 100:
            hash_url = hashlib.md5(url.encode()).hexdigest()[:8]
            nombre = f"{nombre[:50]}_{hash_url}.pdf"
        
        return nombre

    def _extraer_texto_pdf(self, ruta: str) -> Optional[str]:
        """Extrae el texto de un archivo PDF."""
        if not PDF_SUPPORT:
            return None

        try:
            texto = []
            with open(ruta, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                
                for i, pagina in enumerate(reader.pages):
                    try:
                        contenido = pagina.extract_text()
                        if contenido:
                            texto.append(f"--- Pagina {i+1} ---\n{contenido}")
                    except Exception:
                        pass

            return "\n\n".join(texto) if texto else None

        except Exception as e:
            print(f"       [PDF] Error extrayendo texto: {e}")
            return None

    def guardar_contenido(self):
        """Guarda el contenido extraido de todos los PDFs."""
        if self.contenido_pdfs:
            with open(Config.PDFS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.contenido_pdfs, f, ensure_ascii=False, indent=2)
            print(f"       [PDF] {len(self.contenido_pdfs)} PDFs procesados")


# =============================================================================
#  EXTRACTOR DE SECCIONES DEL HOME
# =============================================================================

class ExtractorSecciones:
    """Extrae secciones del footer/home."""

    def __init__(self, html: str):
        self.soup = BeautifulSoup(html, "html.parser")

    def extraer(self) -> Dict[str, List[str]]:
        """Extrae las secciones del footer."""
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

        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def obtener(self, url: str) -> Optional[str]:
        """Obtiene el contenido HTML de una URL."""
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
            print(f"       [ERROR] {type(e).__name__}: {str(e)[:50]}")
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
        self.descargador_pdf = DescargadorPDFs(self.cliente)
        self.base_netloc = urlparse(self.config.BASE_URL).netloc

        self.visitadas: Set[str] = set()
        self.cola: List[str] = []
        self.cola_set: Set[str] = set()
        self.hashes_contenido: Set[str] = set()

        # Almacenamiento de datos
        self.sucursales: List[Dict] = []
        self.aplicaciones: List[Dict] = []
        self.servicios: List[Dict] = []
        self.historia: List[Dict] = []
        self.noticias: List[Dict] = []
        self.enlaces_interes: List[Dict] = []

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
        os.makedirs(self.config.PDF_DIR, exist_ok=True)
        open(self.config.TEXT_FILE, "w", encoding="utf-8").close()

        print("=" * 70)
        print("    SCRAPER SUPER POTENTE - CORREOS BOLIVIA v3.0")
        print("=" * 70)
        print(f"    Base: {self.config.BASE_URL}")
        print(f"    Limite: {self.config.MAX_PAGINAS} paginas")
        print(f"    PDFs: Maximo {self.config.MAX_PDFS}")
        print("=" * 70)

    def _finalizar(self):
        """Finaliza el scraper."""
        self.cliente.cerrar()
        self.stats.fin = datetime.now().isoformat()

        # Guardar PDFs
        self.descargador_pdf.guardar_contenido()
        self.stats.pdfs_descargados = len(self.descargador_pdf.pdfs_procesados)
        self.stats.pdfs_procesados = len([p for p in self.descargador_pdf.contenido_pdfs if p.get("texto_extraido")])

        # Guardar estadisticas
        with open(self.config.STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.stats.to_dict(), f, ensure_ascii=False, indent=2)

        # Guardar aplicaciones y servicios
        datos_apps = {
            "aplicaciones": self.aplicaciones,
            "servicios": self.servicios,
            "total_aplicaciones": len(self.aplicaciones),
            "total_servicios": len(self.servicios)
        }
        with open(self.config.APLICACIONES_FILE, "w", encoding="utf-8") as f:
            json.dump(datos_apps, f, ensure_ascii=False, indent=2)

        # Guardar historia
        if self.historia:
            with open(self.config.HISTORIA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.historia, f, ensure_ascii=False, indent=2)
            self.stats.historia_encontrada = True

        # Guardar noticias
        if self.noticias:
            with open(self.config.NOTICIAS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.noticias, f, ensure_ascii=False, indent=2)

        # Guardar enlaces de interes
        if self.enlaces_interes:
            with open(self.config.ENLACES_FILE, "w", encoding="utf-8") as f:
                json.dump(self.enlaces_interes, f, ensure_ascii=False, indent=2)

        print("\n" + "=" * 70)
        print("    SCRAPING COMPLETADO")
        print("=" * 70)
        print(f"    Archivos generados en {self.config.OUTPUT_DIR}/:")
        print(f"      - correos_bolivia_completo.txt")
        print(f"      - sucursales_contacto.json")
        print(f"      - secciones_home.json")
        print(f"      - estadisticas.json")
        print(f"      - aplicaciones_servicios.json")
        print(f"      - historia_institucional.json")
        print(f"      - noticias_eventos.json")
        print(f"      - enlaces_interes.json")
        print(f"      - pdfs_contenido.json")
        print(f"      - pdfs_descargados/ ({self.stats.pdfs_descargados} archivos)")
        print(f"    Estadisticas:")
        print(f"      - Paginas exitosas: {self.stats.paginas_exitosas}")
        print(f"      - Paginas fallidas: {self.stats.paginas_fallidas}")
        print(f"      - Caracteres extraidos: {self.stats.caracteres_extraidos:,}")
        print(f"      - Sucursales: {self.stats.sucursales_encontradas}")
        print(f"      - Aplicaciones: {self.stats.aplicaciones_encontradas}")
        print(f"      - Servicios: {self.stats.servicios_encontrados}")
        print(f"      - Noticias: {self.stats.noticias_encontradas}")
        print(f"      - PDFs descargados: {self.stats.pdfs_descargados}")
        print(f"      - Historia encontrada: {'Si' if self.stats.historia_encontrada else 'No'}")
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
                pdfs_encontrados = 0
                
                for a in soup_raw.find_all("a", href=True):
                    href = a["href"]
                    
                    # Detectar PDFs
                    if href.lower().endswith(".pdf") or ".pdf" in href.lower():
                        self.descargador_pdf.procesar_pdf(href, url_completa)
                        pdfs_encontrados += 1
                        continue
                    
                    link = normalizar_ruta(href, self.base_netloc)
                    if link and link not in self.visitadas and link not in self.cola_set:
                        self._encolar(link)
                        nuevos += 1

                if nuevos:
                    print(f"       +{nuevos} links", end="")
                if pdfs_encontrados:
                    print(f" +{pdfs_encontrados} PDFs", end="")
                if nuevos or pdfs_encontrados:
                    print()

            # Procesar paginas especiales
            ruta_norm = ruta.rstrip("/") or "/"

            # HOME - extraer secciones
            if ruta_norm == "/":
                self._procesar_home(soup_raw)

            # CONTACTO - extraer sucursales
            elif ruta_norm == "/contact-us" or "contact" in ruta_norm:
                self._procesar_contacto(soup_raw, url_completa)

            # Detectar tipo de contenido
            tipos = detectar_tipo_contenido(html, url_completa)
            
            # Procesar segun tipo
            if "aplicacion" in tipos:
                self._procesar_aplicaciones(soup_raw, url_completa)
            
            if "historia" in tipos:
                self._procesar_historia(soup_raw, url_completa)
            
            if "noticia" in tipos:
                self._procesar_noticias(soup_raw, url_completa)
            
            if "servicio" in tipos:
                self._procesar_servicios(soup_raw, url_completa)

            # Extraer texto
            self._extraer_texto(soup_raw, html, url_completa, tipos)

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
            self.sucursales.extend(sucursales)
            
            with open(self.config.SUCURSALES_FILE, "w", encoding="utf-8") as f:
                json.dump(self.sucursales, f, ensure_ascii=False, indent=2)

            self.stats.sucursales_encontradas = len(self.sucursales)
            print(f"       {len(sucursales)} sucursales encontradas (total: {self.stats.sucursales_encontradas})")

    def _procesar_aplicaciones(self, soup: BeautifulSoup, url: str):
        """Procesa paginas de aplicaciones."""
        extractor = ExtractorAplicaciones(str(soup), url)
        datos = extractor.extraer()

        if datos["aplicaciones"]:
            self.aplicaciones.extend(datos["aplicaciones"])
            self.stats.aplicaciones_encontradas = len(self.aplicaciones)
            print(f"       {len(datos['aplicaciones'])} aplicaciones (total: {self.stats.aplicaciones_encontradas})")

        if datos["herramientas"]:
            self.servicios.extend(datos["herramientas"])
            self.stats.servicios_encontrados = len(self.servicios)

        if datos["enlaces_externos"]:
            self.enlaces_interes.extend(datos["enlaces_externos"])

    def _procesar_servicios(self, soup: BeautifulSoup, url: str):
        """Procesa paginas de servicios."""
        extractor = ExtractorAplicaciones(str(soup), url)
        datos = extractor.extraer()

        if datos["servicios"]:
            self.servicios.extend(datos["servicios"])
            self.stats.servicios_encontrados = len(self.servicios)
            print(f"       {len(datos['servicios'])} servicios (total: {self.stats.servicios_encontrados})")

    def _procesar_historia(self, soup: BeautifulSoup, url: str):
        """Procesa paginas con contenido historico."""
        extractor = ExtractorHistoria(str(soup), url)
        datos = extractor.extraer()

        if datos:
            self.historia.append(datos)
            print(f"       Historia encontrada: {datos['titulo'][:50]}... ({len(datos['contenido'])} chars)")

    def _procesar_noticias(self, soup: BeautifulSoup, url: str):
        """Procesa paginas de noticias."""
        extractor = ExtractorNoticias(str(soup), url)
        datos = extractor.extraer()

        if datos:
            nuevas = [n for n in datos if n["titulo"] and n["titulo"] not in [x["titulo"] for x in self.noticias]]
            self.noticias.extend(nuevas)
            self.stats.noticias_encontradas = len(self.noticias)
            if nuevas:
                print(f"       {len(nuevas)} noticias (total: {self.stats.noticias_encontradas})")

    def _extraer_texto(self, soup_raw: BeautifulSoup, html: str, url: str, tipos: List[str]):
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

        # Verificar duplicados
        if es_contenido_duplicado(texto, self.hashes_contenido):
            return

        if len(texto) > 100 and "sitemap" not in url.lower():
            # Extraer metadatos
            titulo_tag = soup_raw.find("title")
            titulo = limpiar_texto(titulo_tag.get_text()) if titulo_tag else ""

            meta_desc = soup_raw.find("meta", attrs={"name": "description"})
            descripcion = limpiar_texto(meta_desc.get("content", "")) if meta_desc else ""

            # Formatear
            tipos_str = ", ".join(tipos)
            partes = [f"\n{'='*60}", f"FUENTE: {url}"]
            if titulo:
                partes.append(f"TITULO: {titulo}")
            if descripcion:
                partes.append(f"DESCRIPCION: {descripcion}")
            partes.append(f"TIPOS: {tipos_str}")
            partes.extend([f"{'='*60}", texto, ""])

            bloque = "\n".join(partes)

            with open(self.config.TEXT_FILE, "a", encoding="utf-8") as f:
                f.write(bloque)

            self.stats.caracteres_extraidos += len(texto)
            self.stats.paginas_exitosas += 1
            print(f"       {len(texto):,} caracteres [{tipos_str}]")
        else:
            self.stats.paginas_fallidas += 1
            print(f"       Contenido insuficiente")


# =============================================================================
#  PUNTO DE ENTRADA
# =============================================================================

def main():
    """Funcion principal."""
    print("\n" + "=" * 70)
    print("    IMPORTANTE: Antes de ejecutar, instala las dependencias:")
    print("    pip install requests beautifulsoup4 PyPDF2")
    print("=" * 70 + "\n")
    
    scraper = ScraperCorreosBolivia()
    scraper.ejecutar()


if __name__ == "__main__":
    main()