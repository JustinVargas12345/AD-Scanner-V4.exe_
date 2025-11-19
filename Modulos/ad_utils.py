'''
import socket
import subprocess
import platform
import time
from datetime import datetime
from ldap3 import Server, Connection, ALL
from Datos.db_conexion import conectar_sql
from Configs.logs_utils import escribir_log
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from cryptography.fernet import Fernet  # <-- nuevo

estado_ping = {}

# ------------------------
# Helpers de encriptación
# ------------------------
KEY_FILE = "secret.key"

def _cargar_fernet():
    """
    Intenta cargar la key desde KEY_FILE y devuelve un objeto Fernet.
    Si falla, devuelve None (se sigue funcionando con texto plano).
    """
    try:
        with open(KEY_FILE, "rb") as f:
            key = f.read()
        return Fernet(key)
    except Exception as e:
        # No es crítico — sólo avisamos en logs
        escribir_log(f"No se pudo cargar '{KEY_FILE}': {e}", tipo="WARNING")
        return None

def _maybe_decrypt(value):
    """
    Si value parece ser una cadena encriptada con Fernet, intenta desencriptarla.
    Si no, devuelve value tal cual.
    """
    if not value:
        return value
    f = _cargar_fernet()
    if not f:
        return value
    try:
        # si no es decryptable, lanzará excepción y retornaremos value original
        return f.decrypt(value.encode()).decode()
    except Exception:
        return value



# ------------------------
# Validar credenciales AD
# ------------------------
def validar_ad(credenciales):
    """
    Valida paso por paso qué campo de Active Directory está incorrecto.
    Devuelve un diccionario con el primer error encontrado.
    """
    server = credenciales.get("AD_SERVER")
    user = credenciales.get("AD_USER")
    password = credenciales.get("AD_PASSWORD")
    base = credenciales.get("AD_SEARCH_BASE")

    # Validar que el servidor existe
    try:
        srv = Server(server, get_info=ALL)
    except Exception as e:
        return {"ok": False, "error": "AD_SERVER", "detalle": str(e)}

    # Validar credenciales
    try:
        conn = Connection(srv, user=user, password=password, auto_bind=True)
    except Exception as e:
        return {"ok": False, "error": "AD_USER/AD_PASSWORD", "detalle": str(e)}

    # Validar base de búsqueda
    try:
        conn.search(base, "(objectClass=*)", attributes=["cn"])
    except Exception as e:
        return {"ok": False, "error": "AD_SEARCH_BASE", "detalle": str(e)}

    return {"ok": True}
# ------------------------
# Obtener equipos desde AD
# ------------------------


def obtener_equipos_ad(config):
    """
    Obtiene los equipos de AD usando las credenciales actuales.
    Acepta credenciales en texto plano o encriptadas.
    """
    equipos = []
    try:
        server = Server(config["AD_SERVER"], get_info=ALL)
        user = _maybe_decrypt(config.get("AD_USER", ""))
        password = _maybe_decrypt(config.get("AD_PASSWORD", ""))
        conn = Connection(server, user=user, password=password, auto_bind=True)
        conn.search(
            config["AD_SEARCH_BASE"],
            "(objectClass=computer)",
            attributes=[
                "name", "dNSHostName", "operatingSystem", "operatingSystemVersion",
                "description", "whenCreated", "lastLogonTimestamp", "managedBy",
                "location", "userAccountControl"
            ]
        )
        for entry in conn.entries:
            nombre = str(entry.name)
            so = str(entry.operatingSystem) if hasattr(entry, 'operatingSystem') else "N/A"
            desc = str(entry.description) if hasattr(entry, 'description') else "N/A"
            nombre_dns = str(entry.dNSHostName) if hasattr(entry, 'dNSHostName') else "N/A"
            version_so = str(entry.operatingSystemVersion) if hasattr(entry, 'operatingSystemVersion') else "N/A"
            creado_el = str(entry.whenCreated) if hasattr(entry, 'whenCreated') else "N/A"
            ultimo_logon = str(entry.lastLogonTimestamp) if hasattr(entry, 'lastLogonTimestamp') else "N/A"
            responsable = str(entry.managedBy) if hasattr(entry, 'managedBy') else "N/A"
            ubicacion = str(entry.location) if hasattr(entry, 'location') else "N/A"
            estado_cuenta = str(entry.userAccountControl) if hasattr(entry, 'userAccountControl') else "N/A"

            try:
                ip = socket.gethostbyname(nombre)
            except socket.gaierror:
                ip = "No resuelve"

            equipos.append({
                "nombre": nombre,
                "so": so,
                "descripcion": desc,
                "ip": ip,
                "nombredns": nombre_dns,
                "versionso": version_so,
                "creadoel": creado_el,
                "ultimologon": ultimo_logon,
                "responsable": responsable,
                "ubicacion": ubicacion,
                "estadocuenta": estado_cuenta
            })

        escribir_log(f"Equipos obtenidos desde AD: {len(equipos)}", tipo="INFO")

    except Exception as e:
        escribir_log(f"Excepción al leer AD: {e}", tipo="ERROR")

    return equipos

# ------------------------
# Función de ping
# ------------------------
def hacer_ping(host):
    try:
        param = "-n" if platform.system().lower() == "windows" else "-c"
        result = subprocess.run(["ping", param, "1", host], capture_output=True, timeout=6)
        estado = "Activo" if result.returncode == 0 else "Inactivo"

        if estado != "Activo":
            escribir_log(f"Ping fallido: {host} → {estado}", tipo="WARNING")
        return estado

    except subprocess.TimeoutExpired:
        escribir_log(f"Ping timeout: {host}", tipo="ERROR")
        return "Timeout"
    except Exception as e:
        escribir_log(f"Error en ping {host}: {e}", tipo="ERROR")
        return "Error"

# ------------------------
# Ejecutar SQL con reintento
# ------------------------
def ejecutar_sql_reintento(conn, query, params=(), reintentos=3, espera=5):
    for intento in range(1, reintentos + 1):
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return True
        except Exception as e:
            escribir_log(f"SQL intento {intento} fallido: {e}", tipo="ERROR")
            if intento < reintentos:
                time.sleep(espera)
                # Intentar reconectar (si conectar_sql soporta config debería recibir config)
                try:
                    conn = conectar_sql()
                except Exception:
                    pass
            else:
                return False

# ------------------------
# Insertar o actualizar equipos con multithreading para ping
# ------------------------
# Lock global para acceso a SQL
sql_lock = Lock()


def insertar_o_actualizar(conn, equipos, equipos_ad_actuales, ping_interval, max_threads=10):
    """
    Inserta o actualiza los registros de AD en la base de datos.
    Los pings se hacen en paralelo, pero las consultas SQL se serializan usando un lock.
    """

    def procesar_equipo(eq):
        ping = hacer_ping(eq["nombre"])
        estado_ad = "Dentro de AD" if eq["nombre"] in equipos_ad_actuales else "Removido de AD"

        # Actualizar estado_ping
        if eq["nombre"] in estado_ping:
            anterior = estado_ping[eq["nombre"]]["estado"]
            if anterior != ping:
                escribir_log(f"Estado de {eq['nombre']} cambió de {anterior} a {ping}")
                estado_ping[eq["nombre"]]["estado"] = ping
                estado_ping[eq["nombre"]]["contador"] = 1
            else:
                estado_ping[eq["nombre"]]["contador"] += 1
        else:
            estado_ping[eq["nombre"]] = {"estado": ping, "contador": 1}

        inactivo_desde = estado_ping[eq["nombre"]].get("inactivo_desde")
        if ping in ("Inactivo", "Timeout", "Error"):
            if not inactivo_desde:
                estado_ping[eq["nombre"]]["inactivo_desde"] = datetime.now()
        else:
            estado_ping[eq["nombre"]]["inactivo_desde"] = None

        # Calcular tiempo total en segundos
        tiempo_total_segundos = estado_ping[eq["nombre"]]["contador"] * ping_interval

        # Formato viejo (HH:MM:SS) para compatibilidad
        horas = tiempo_total_segundos // 3600
        minutos = (tiempo_total_segundos % 3600) // 60
        segundos = tiempo_total_segundos % 60
        tiempo_formateado = f"{horas:02}:{minutos:02}:{segundos:02}"

        # Nuevo campo ActivoTiempo (NULL si está inactivo)
        if ping not in ("Inactivo", "Timeout", "Error"):
            dias = tiempo_total_segundos // 86400
            horas_activo = (tiempo_total_segundos % 86400) // 3600
            minutos_activo = (tiempo_total_segundos % 3600) // 60
            segundos_activo = tiempo_total_segundos % 60
            activo_tiempo = f"{dias}d {horas_activo:02}:{minutos_activo:02}:{segundos_activo:02}"
        else:
            activo_tiempo = None  # Pasará como NULL a SQL Server

        # Preparar fecha de inactivo para SQL Server
        inactivo_sql = estado_ping[eq["nombre"]]["inactivo_desde"]
        

        query = """
            MERGE EquiposAD AS target
            USING (SELECT ? AS Nombre, ? AS SO, ? AS Descripcion, ? AS IP, ? AS NombreDNS,
                          ? AS VersionSO, ? AS CreadoEl, ? AS UltimoLogon, ? AS Responsable,
                          ? AS Ubicacion, ? AS EstadoCuenta, ? AS PingStatus, ? AS TiempoPing,
                          ? AS InactivoDesde, ? AS EstadoAD, ? AS ActivoTiempo) AS src
            ON target.Nombre = src.Nombre
            WHEN MATCHED THEN
                UPDATE SET target.SO = src.SO,
                           target.Descripcion = src.Descripcion,
                           target.IP = src.IP,
                           target.NombreDNS = src.NombreDNS,
                           target.VersionSO = src.VersionSO,
                           target.CreadoEl = src.CreadoEl,
                           target.UltimoLogon = src.UltimoLogon,
                           target.Responsable = src.Responsable,
                           target.Ubicacion = src.Ubicacion,
                           target.EstadoCuenta = src.EstadoCuenta,
                           target.PingStatus = src.PingStatus,
                           target.TiempoPing = src.TiempoPing,
                           target.InactivoDesde = src.InactivoDesde,
                           target.EstadoAD = src.EstadoAD,
                           target.ActivoTiempo = src.ActivoTiempo,
                           target.UltimaActualizacion = GETDATE()
            WHEN NOT MATCHED THEN
                INSERT (Nombre, SO, Descripcion, IP, NombreDNS, VersionSO, CreadoEl,
                        UltimoLogon, Responsable, Ubicacion, EstadoCuenta, PingStatus,
                        TiempoPing, InactivoDesde, EstadoAD, ActivoTiempo)
                VALUES (src.Nombre, src.SO, src.Descripcion, src.IP, src.NombreDNS,
                        src.VersionSO, src.CreadoEl, src.UltimoLogon, src.Responsable,
                        src.Ubicacion, src.EstadoCuenta, src.PingStatus, src.TiempoPing,
                        src.InactivoDesde, src.EstadoAD, src.ActivoTiempo);
        """

        with sql_lock:
            ejecutar_sql_reintento(conn, query, (
                eq["nombre"], eq["so"], eq["descripcion"], eq["ip"], eq["nombredns"],
                eq["versionso"], eq["creadoel"], eq["ultimologon"], eq["responsable"],
                eq["ubicacion"], eq["estadocuenta"], ping, tiempo_formateado,
                inactivo_sql, estado_ad, activo_tiempo
            ))

        texto_fecha = f" | Inactivo desde: {estado_ping[eq['nombre']].get('inactivo_desde')}" if estado_ping[eq["nombre"]].get('inactivo_desde') else ""
        print(f"[PING] {eq['nombre']} ({eq['ip']}) → {ping} | {estado_ad} ({tiempo_formateado}){texto_fecha}")

    # Ejecutar pings en paralelo
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(procesar_equipo, eq) for eq in equipos]
        for _ in as_completed(futures):
            pass

'''
import socket
import platform
import time
from datetime import datetime
from ldap3 import Server, Connection, ALL
from Datos.db_conexion import conectar_sql
from Configs.logs_utils import escribir_log
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from cryptography.fernet import Fernet
from ping3 import ping  # <-- reemplazo por ping3

estado_ping = {}

# ------------------------
# Helpers de encriptación
# ------------------------
KEY_FILE = "secret.key"

def _cargar_fernet():
    try:
        with open(KEY_FILE, "rb") as f:
            key = f.read()
        return Fernet(key)
    except Exception as e:
        escribir_log(f"No se pudo cargar '{KEY_FILE}': {e}", tipo="WARNING")
        return None

def _maybe_decrypt(value):
    if not value:
        return value
    f = _cargar_fernet()
    if not f:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except Exception:
        return value

# ------------------------
# Validar credenciales AD
# ------------------------
def validar_ad(credenciales):
    server = credenciales.get("AD_SERVER")
    user = credenciales.get("AD_USER")
    password = credenciales.get("AD_PASSWORD")
    base = credenciales.get("AD_SEARCH_BASE")

    try:
        srv = Server(server, get_info=ALL)
    except Exception as e:
        return {"ok": False, "error": "AD_SERVER", "detalle": str(e)}

    try:
        conn = Connection(srv, user=user, password=password, auto_bind=True)
    except Exception as e:
        return {"ok": False, "error": "AD_USER/AD_PASSWORD", "detalle": str(e)}

    try:
        conn.search(base, "(objectClass=*)", attributes=["cn"])
    except Exception as e:
        return {"ok": False, "error": "AD_SEARCH_BASE", "detalle": str(e)}

    return {"ok": True}

# ------------------------
# Obtener equipos desde AD
# ------------------------
def obtener_equipos_ad(config):
    equipos = []
    try:
        server = Server(config["AD_SERVER"], get_info=ALL)
        user = _maybe_decrypt(config.get("AD_USER", ""))
        password = _maybe_decrypt(config.get("AD_PASSWORD", ""))
        conn = Connection(server, user=user, password=password, auto_bind=True)
        conn.search(
            config["AD_SEARCH_BASE"],
            "(objectClass=computer)",
            attributes=[
                "name", "dNSHostName", "operatingSystem", "operatingSystemVersion",
                "description", "whenCreated", "lastLogonTimestamp", "managedBy",
                "location", "userAccountControl"
            ]
        )
        for entry in conn.entries:
            nombre = str(entry.name)
            so = str(entry.operatingSystem) if hasattr(entry, 'operatingSystem') else "N/A"
            desc = str(entry.description) if hasattr(entry, 'description') else "N/A"
            nombre_dns = str(entry.dNSHostName) if hasattr(entry, 'dNSHostName') else "N/A"
            version_so = str(entry.operatingSystemVersion) if hasattr(entry, 'operatingSystemVersion') else "N/A"
            creado_el = str(entry.whenCreated) if hasattr(entry, 'whenCreated') else "N/A"
            ultimo_logon = str(entry.lastLogonTimestamp) if hasattr(entry, 'lastLogonTimestamp') else "N/A"
            responsable = str(entry.managedBy) if hasattr(entry, 'managedBy') else "N/A"
            ubicacion = str(entry.location) if hasattr(entry, 'location') else "N/A"
            estado_cuenta = str(entry.userAccountControl) if hasattr(entry, 'userAccountControl') else "N/A"

            try:
                ip = socket.gethostbyname(nombre)
            except socket.gaierror:
                ip = "No resuelve"

            equipos.append({
                "nombre": nombre,
                "so": so,
                "descripcion": desc,
                "ip": ip,
                "nombredns": nombre_dns,
                "versionso": version_so,
                "creadoel": creado_el,
                "ultimologon": ultimo_logon,
                "responsable": responsable,
                "ubicacion": ubicacion,
                "estadocuenta": estado_cuenta
            })

        escribir_log(f"Equipos obtenidos desde AD: {len(equipos)}", tipo="INFO")

    except Exception as e:
        escribir_log(f"Excepción al leer AD: {e}", tipo="ERROR")

    return equipos

# ------------------------
# Función de ping con ping3
# ------------------------
def hacer_ping(host):
    try:
        result = ping(host, timeout=6)
        estado = "Activo" if result else "Inactivo"

        if estado != "Activo":
            escribir_log(f"Ping fallido: {host} → {estado}", tipo="WARNING")
        return estado

    except Exception as e:
        escribir_log(f"Error en ping {host}: {e}", tipo="ERROR")
        return "Error"

# ------------------------
# Ejecutar SQL con reintento
# ------------------------
def ejecutar_sql_reintento(conn, query, params=(), reintentos=3, espera=5):
    for intento in range(1, reintentos + 1):
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return True
        except Exception as e:
            escribir_log(f"SQL intento {intento} fallido: {e}", tipo="ERROR")
            if intento < reintentos:
                time.sleep(espera)
                try:
                    conn = conectar_sql()
                except Exception:
                    pass
            else:
                return False

# ------------------------
# Insertar o actualizar equipos con multithreading para ping
# ------------------------
sql_lock = Lock()

def insertar_o_actualizar(conn, equipos, equipos_ad_actuales, ping_interval, max_threads=10):
    def procesar_equipo(eq):
        ping_status = hacer_ping(eq["nombre"])
        estado_ad = "Dentro de AD" if eq["nombre"] in equipos_ad_actuales else "Removido de AD"

        if eq["nombre"] in estado_ping:
            anterior = estado_ping[eq["nombre"]]["estado"]
            if anterior != ping_status:
                escribir_log(f"Estado de {eq['nombre']} cambió de {anterior} a {ping_status}")
                estado_ping[eq["nombre"]]["estado"] = ping_status
                estado_ping[eq["nombre"]]["contador"] = 1
            else:
                estado_ping[eq["nombre"]]["contador"] += 1
        else:
            estado_ping[eq["nombre"]] = {"estado": ping_status, "contador": 1}

        inactivo_desde = estado_ping[eq["nombre"]].get("inactivo_desde")
        if ping_status in ("Inactivo", "Error"):
            if not inactivo_desde:
                estado_ping[eq["nombre"]]["inactivo_desde"] = datetime.now()
        else:
            estado_ping[eq["nombre"]]["inactivo_desde"] = None

        tiempo_total_segundos = estado_ping[eq["nombre"]]["contador"] * ping_interval
        horas = tiempo_total_segundos // 3600
        minutos = (tiempo_total_segundos % 3600) // 60
        segundos = tiempo_total_segundos % 60
        tiempo_formateado = f"{horas:02}:{minutos:02}:{segundos:02}"

        if ping_status not in ("Inactivo", "Error"):
            dias = tiempo_total_segundos // 86400
            horas_activo = (tiempo_total_segundos % 86400) // 3600
            minutos_activo = (tiempo_total_segundos % 3600) // 60
            segundos_activo = tiempo_total_segundos % 60
            activo_tiempo = f"{dias}d {horas_activo:02}:{minutos_activo:02}:{segundos_activo:02}"
        else:
            activo_tiempo = None

        inactivo_sql = estado_ping[eq["nombre"]]["inactivo_desde"]

        query = """
            MERGE EquiposAD AS target
            USING (SELECT ? AS Nombre, ? AS SO, ? AS Descripcion, ? AS IP, ? AS NombreDNS,
                          ? AS VersionSO, ? AS CreadoEl, ? AS UltimoLogon, ? AS Responsable,
                          ? AS Ubicacion, ? AS EstadoCuenta, ? AS PingStatus, ? AS TiempoPing,
                          ? AS InactivoDesde, ? AS EstadoAD, ? AS ActivoTiempo) AS src
            ON target.Nombre = src.Nombre
            WHEN MATCHED THEN
                UPDATE SET target.SO = src.SO,
                           target.Descripcion = src.Descripcion,
                           target.IP = src.IP,
                           target.NombreDNS = src.NombreDNS,
                           target.VersionSO = src.VersionSO,
                           target.CreadoEl = src.CreadoEl,
                           target.UltimoLogon = src.UltimoLogon,
                           target.Responsable = src.Responsable,
                           target.Ubicacion = src.Ubicacion,
                           target.EstadoCuenta = src.EstadoCuenta,
                           target.PingStatus = src.PingStatus,
                           target.TiempoPing = src.TiempoPing,
                           target.InactivoDesde = src.InactivoDesde,
                           target.EstadoAD = src.EstadoAD,
                           target.ActivoTiempo = src.ActivoTiempo,
                           target.UltimaActualizacion = GETDATE()
            WHEN NOT MATCHED THEN
                INSERT (Nombre, SO, Descripcion, IP, NombreDNS, VersionSO, CreadoEl,
                        UltimoLogon, Responsable, Ubicacion, EstadoCuenta, PingStatus,
                        TiempoPing, InactivoDesde, EstadoAD, ActivoTiempo)
                VALUES (src.Nombre, src.SO, src.Descripcion, src.IP, src.NombreDNS,
                        src.VersionSO, src.CreadoEl, src.UltimoLogon, src.Responsable,
                        src.Ubicacion, src.EstadoCuenta, src.PingStatus, src.TiempoPing,
                        src.InactivoDesde, src.EstadoAD, src.ActivoTiempo);
        """

        with sql_lock:
            ejecutar_sql_reintento(conn, query, (
                eq["nombre"], eq["so"], eq["descripcion"], eq["ip"], eq["nombredns"],
                eq["versionso"], eq["creadoel"], eq["ultimologon"], eq["responsable"],
                eq["ubicacion"], eq["estadocuenta"], ping_status, tiempo_formateado,
                inactivo_sql, estado_ad, activo_tiempo
            ))

        texto_fecha = f" | Inactivo desde: {estado_ping[eq['nombre']].get('inactivo_desde')}" if estado_ping[eq["nombre"]].get('inactivo_desde') else ""
        print(f"[PING] {eq['nombre']} ({eq['ip']}) → {ping_status} | {estado_ad} ({tiempo_formateado}){texto_fecha}")

    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(procesar_equipo, eq) for eq in equipos]
        for _ in as_completed(futures):
            pass
