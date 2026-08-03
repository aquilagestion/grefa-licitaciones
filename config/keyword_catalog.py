"""Catálogo de términos GREFA con equivalentes en castellano, euskera, catalán y gallego.

Cada fila del catálogo es un concepto. Si está activo, la búsqueda puntúa
cualquier coincidencia en cualquiera de los cuatro idiomas. Al añadir un
término nuevo desde la app o desde Sheets, basta con rellenar las columnas
de traducción para que también entre en el matching.
"""

from __future__ import annotations

from typing import TypedDict


class TerminoCatalogo(TypedDict):
    castellano: str
    euskera: str
    catalan: str
    gallego: str
    categoria: str
    activo: bool


# Términos solicitados + los históricos de GREFA. Las traducciones son las
# formas habituales en documentación pública / administración; los nombres
# propios (ADIF, RENFE…) se mantienen.
DEFAULT_TERM_CATALOG: list[TerminoCatalogo] = [
    # --- Medio ambiente y clima ---
    {"castellano": "biodiversidad", "euskera": "biodibertsitatea", "catalan": "biodiversitat", "gallego": "biodiversidade", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "bosque", "euskera": "basoa", "catalan": "bosc", "gallego": "bosque", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "calentamiento global", "euskera": "berotze globala", "catalan": "escalfament global", "gallego": "quecemento global", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "cambio climático", "euskera": "klima-aldaketa", "catalan": "canvi climàtic", "gallego": "cambio climático", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "conservación", "euskera": "kontserbazioa", "catalan": "conservació", "gallego": "conservación", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "contaminación", "euskera": "kutsadura", "catalan": "contaminació", "gallego": "contaminación", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "deforestación", "euskera": "baso-soiltzea", "catalan": "desforestació", "gallego": "deforestación", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "desarrollo sostenible", "euskera": "garapen jasangarria", "catalan": "desenvolupament sostenible", "gallego": "desenvolvemento sostible", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "desertificación", "euskera": "basamortutze", "catalan": "desertificació", "gallego": "desertificación", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "ecología", "euskera": "ekologia", "catalan": "ecologia", "gallego": "ecoloxía", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "economía circular", "euskera": "ekonomia zirkularra", "catalan": "economia circular", "gallego": "economía circular", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "ecosistema", "euskera": "ekosistema", "catalan": "ecosistema", "gallego": "ecosistema", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "educación ambiental", "euskera": "ingurumen-hezkuntza", "catalan": "educació ambiental", "gallego": "educación ambiental", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "educativas", "euskera": "hezkuntzakoak", "catalan": "educatives", "gallego": "educativas", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "efecto invernadero", "euskera": "berotegi-efektua", "catalan": "efecte hivernacle", "gallego": "efecto invernadoiro", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "emisiones", "euskera": "isuriak", "catalan": "emissions", "gallego": "emisións", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "energías renovables", "euskera": "energia berriztagarriak", "catalan": "energies renovables", "gallego": "enerxías renovables", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "fauna", "euskera": "fauna", "catalan": "fauna", "gallego": "fauna", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "flora", "euskera": "flora", "catalan": "flora", "gallego": "flora", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "gestión ambiental", "euskera": "ingurumen-kudeaketa", "catalan": "gestió ambiental", "gallego": "xestión ambiental", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "hábitat", "euskera": "habitat", "catalan": "hàbitat", "gallego": "hábitat", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "huella ecológica", "euskera": "aztarna ekologikoa", "catalan": "petjada ecològica", "gallego": "pegada ecolóxica", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "legislación ambiental", "euskera": "ingurumen-legedia", "catalan": "legislació ambiental", "gallego": "lexislación ambiental", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "mar", "euskera": "itsasoa", "catalan": "mar", "gallego": "mar", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "medio ambiental", "euskera": "ingurumenekoa", "catalan": "mediambiental", "gallego": "medioambiental", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "medio ambiente", "euskera": "ingurumena", "catalan": "medi ambient", "gallego": "medio ambiente", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "medio natural", "euskera": "ingurune naturala", "catalan": "medi natural", "gallego": "medio natural", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "medioambiental", "euskera": "ingurumenekoa", "catalan": "mediambiental", "gallego": "medioambiental", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "medioambiente", "euskera": "ingurumena", "catalan": "medi ambient", "gallego": "medioambiente", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "montaña", "euskera": "mendia", "catalan": "muntanya", "gallego": "montaña", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "movimientos ecologistas", "euskera": "mugimendu ekologistak", "catalan": "moviments ecologistes", "gallego": "movementos ecoloxistas", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "naturaleza", "euskera": "natura", "catalan": "natura", "gallego": "natureza", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "océano", "euskera": "ozeanoa", "catalan": "oceà", "gallego": "océano", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "ONG ambientalistas", "euskera": "ingurumeneko GGKE", "catalan": "ONG ambientalistes", "gallego": "ONG ambientalistas", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "políticas verdes", "euskera": "politika berdeak", "catalan": "polítiques verdes", "gallego": "políticas verdes", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "polución", "euskera": "poluzioa", "catalan": "pol·lució", "gallego": "polución", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "reciclaje", "euskera": "birziklapena", "catalan": "reciclatge", "gallego": "reciclaxe", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "regulación ecológica", "euskera": "erregulazio ekologikoa", "catalan": "regulació ecològica", "gallego": "regulación ecolóxica", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "residuos", "euskera": "hondakinak", "catalan": "residus", "gallego": "residuos", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "responsabilidad ambiental", "euskera": "ingurumen-erantzukizuna", "catalan": "responsabilitat ambiental", "gallego": "responsabilidade ambiental", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "reutilización", "euskera": "berrerabilpena", "catalan": "reutilització", "gallego": "reutilización", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "río", "euskera": "ibaia", "catalan": "riu", "gallego": "río", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "selva", "euskera": "oihana", "catalan": "selva", "gallego": "selva", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "ambiente", "euskera": "ingurunea", "catalan": "ambient", "gallego": "ambiente", "categoria": "Medio ambiente", "activo": True},
    {"castellano": "charcas", "euskera": "putzuak", "catalan": "basses", "gallego": "charcas", "categoria": "Medio ambiente", "activo": True},
    # --- Fauna / GREFA histórico ---
    {"castellano": "fauna salvaje", "euskera": "basa-fauna", "catalan": "fauna salvatge", "gallego": "fauna salvaxe", "categoria": "Fauna y conservación", "activo": True},
    {"castellano": "recuperación de fauna", "euskera": "faunaren berreskurapena", "catalan": "recuperació de fauna", "gallego": "recuperación de fauna", "categoria": "Fauna y conservación", "activo": True},
    {"castellano": "estudio de poblaciones", "euskera": "populazioen azterketa", "catalan": "estudi de poblacions", "gallego": "estudo de poboacións", "categoria": "Fauna y conservación", "activo": True},
    {"castellano": "marcado de aves", "euskera": "hegaztien markaketa", "catalan": "marcatge d'ocells", "gallego": "marcado de aves", "categoria": "Fauna y conservación", "activo": True},
    {"castellano": "telemetría", "euskera": "telemetria", "catalan": "telemetria", "gallego": "telemetría", "categoria": "Fauna y conservación", "activo": True},
    {"castellano": "control biológico", "euskera": "kontrol biologikoa", "catalan": "control biològic", "gallego": "control biolóxico", "categoria": "Fauna y conservación", "activo": True},
    {"castellano": "buitre negro", "euskera": "sai beltza", "catalan": "voltor negre", "gallego": "voitre negro", "categoria": "Especies específicas", "activo": True},
    {"castellano": "águila de Bonelli", "euskera": "Bonelli arranoa", "catalan": "àguila cuabarrada", "gallego": "aguia de Bonelli", "categoria": "Especies específicas", "activo": True},
    {"castellano": "cernícalo primilla", "euskera": "belatz txikia", "catalan": "xoriguer petit", "gallego": "lagarteiro das torres", "categoria": "Especies específicas", "activo": True},
    {"castellano": "topillo campesino", "euskera": "sator landatarra", "catalan": "talpó comú", "gallego": "rán da terra", "categoria": "Especies específicas", "activo": True},
    {"castellano": "galápago europeo", "euskera": "apoarmatu europearra", "catalan": "tortuga d'estany", "gallego": "sapoconcho europeo", "categoria": "Especies específicas", "activo": True},
    {"castellano": "milano", "euskera": "mirua", "catalan": "milà", "gallego": "miñato", "categoria": "Especies específicas", "activo": True},
    {"castellano": "veterinario", "euskera": "albaitaria", "catalan": "veterinari", "gallego": "veterinario", "categoria": "Servicios", "activo": True},
    {"castellano": "centro de interpretación", "euskera": "interpretazio-zentroa", "catalan": "centre d'interpretació", "gallego": "centro de interpretación", "categoria": "Servicios", "activo": True},
    {"castellano": "voluntariado ambiental", "euskera": "ingurumen-boluntariotza", "catalan": "voluntariat ambiental", "gallego": "voluntariado ambiental", "categoria": "Servicios", "activo": True},
    # --- Entidades / infraestructuras ---
    {"castellano": "ONG", "euskera": "GGKE", "catalan": "ONG", "gallego": "ONG", "categoria": "Entidades", "activo": True},
    {"castellano": "asociaciones", "euskera": "elkarteak", "catalan": "associacions", "gallego": "asociacións", "categoria": "Entidades", "activo": True},
    {"castellano": "ADIF", "euskera": "ADIF", "catalan": "ADIF", "gallego": "ADIF", "categoria": "Infraestructuras", "activo": True},
    {"castellano": "infraestructuras ferroviarias", "euskera": "trenbide-azpiegiturak", "catalan": "infraestructures ferroviàries", "gallego": "infraestruturas ferroviarias", "categoria": "Infraestructuras", "activo": True},
    {"castellano": "RENFE", "euskera": "RENFE", "catalan": "RENFE", "gallego": "RENFE", "categoria": "Infraestructuras", "activo": True},
    {"castellano": "línea A", "euskera": "A linea", "catalan": "línia A", "gallego": "liña A", "categoria": "Infraestructuras", "activo": True},
    {"castellano": "línea B", "euskera": "B linea", "catalan": "línia B", "gallego": "liña B", "categoria": "Infraestructuras", "activo": True},
    {"castellano": "comunidad de madrid", "euskera": "Madrilgo Erkidegoa", "catalan": "Comunitat de Madrid", "gallego": "Comunidade de Madrid", "categoria": "Administraciones", "activo": True},
    {"castellano": "Junta de Andalucía", "euskera": "Andaluziako Junta", "catalan": "Junta d'Andalusia", "gallego": "Junta de Andalucía", "categoria": "Administraciones", "activo": True},
]


def default_term_catalog() -> list[TerminoCatalogo]:
    """Copia independiente del catálogo por defecto."""
    return [dict(t) for t in DEFAULT_TERM_CATALOG]  # type: ignore[misc]


def variants_of(termino: TerminoCatalogo | dict) -> list[str]:
    """Todas las formas lingüísticas no vacías de un término."""
    vistos: set[str] = set()
    resultado: list[str] = []
    for clave in ("castellano", "euskera", "catalan", "gallego"):
        valor = str(termino.get(clave, "") or "").strip()
        if not valor:
            continue
        clave_norm = valor.lower()
        if clave_norm not in vistos:
            vistos.add(clave_norm)
            resultado.append(valor)
    return resultado


def active_search_terms(catalogo: list[TerminoCatalogo] | list[dict]) -> list[str]:
    """Lista plana de variantes a buscar (solo términos activos)."""
    plano: list[str] = []
    vistos: set[str] = set()
    for termino in catalogo:
        if not termino.get("activo", True):
            continue
        for variante in variants_of(termino):
            clave = variante.lower()
            if clave not in vistos:
                vistos.add(clave)
                plano.append(variante)
    return plano


def active_keywords_grouped(catalogo: list[TerminoCatalogo] | list[dict]) -> dict[str, list[str]]:
    """Agrupa por categoría los términos castellanos activos (para la UI)."""
    grupos: dict[str, list[str]] = {}
    for termino in catalogo:
        if not termino.get("activo", True):
            continue
        castellano = str(termino.get("castellano", "")).strip()
        if not castellano:
            continue
        categoria = str(termino.get("categoria", "") or "Sin categoría")
        grupos.setdefault(categoria, []).append(castellano)
    return grupos


def canonical_for_variant(catalogo: list[dict], variante: str) -> str:
    """Devuelve el castellano canónico de una variante coincidente."""
    objetivo = variante.strip().lower()
    for termino in catalogo:
        for v in variants_of(termino):
            if v.lower() == objetivo:
                return str(termino.get("castellano") or v)
    return variante
