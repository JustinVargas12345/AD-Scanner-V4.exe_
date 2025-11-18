'''

import json
import requests
from datetime import datetime, timedelta
import jwt  # pip install PyJWT
from Datos.db_conexion_extras import ejecutar_sql_reintento, ejecutar_sql_fetch
from Datos.db_conexion import ejecutar_sql

WEBHOOK_CONFIG_PATH = "Configs/personal_info/webhook_config.json"


# ----------------------------------------------------
# CARGAR CONFIGURACIÓN DEL WEBHOOK
# ----------------------------------------------------
def cargar_webhook_config():
    """
    Devuelve dict con keys:
      { "webhook_url": str or None, "min_seconds_inactivo": int, "webhook_secret": str or None }
    """
    default = {"webhook_url": None, "min_seconds_inactivo": 60, "webhook_secret": None}

    try:
        with open(WEBHOOK_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

            url = data.get("webhook_url") or data.get("url") or None
            min_sec = data.get("min_seconds_inactivo", data.get("min_seconds", 60))
            secret = data.get("webhook_secret") or None

            try:
                min_sec = int(min_sec)
            except Exception:
                min_sec = 60

            return {
                "webhook_url": url,
                "min_seconds_inactivo": min_sec,
                "webhook_secret": secret,
            }

    except FileNotFoundError:
        return default

    except Exception as e:
        print("[WEBHOOK_CFG] Error leyendo config:", e)
        return default


# ----------------------------------------------------
# GENERAR JWT OPCIONAL
# ----------------------------------------------------
def generar_jwt(secret, expiracion_segundos=3600):
    payload = {
        "exp": datetime.utcnow() + timedelta(seconds=expiracion_segundos),
        "iat": datetime.utcnow()
    }

    token = jwt.encode(payload, secret, algorithm="HS256")

    if isinstance(token, bytes):
        token = token.decode("utf-8")

    return token


# ----------------------------------------------------
# ENVIAR ALERTAS DE INACTIVIDAD
# ----------------------------------------------------
def enviar_alertas_inactividad(conn):
    cfg = cargar_webhook_config()
    webhook_url = cfg["webhook_url"]
    min_seconds = cfg["min_seconds_inactivo"]
    secret = cfg.get("webhook_secret")

    if not webhook_url:
        print("[ALERTAS] No hay URL configurada. Saltando ciclo.")
        return

    # Crear tabla AlertasEnviadas si no existe
    crear_tabla_alertas = """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='AlertasEnviadas' AND xtype='U')
        CREATE TABLE AlertasEnviadas (
            Nombre NVARCHAR(255),
            Fecha DATE
        )
    """
    ejecutar_sql_reintento(conn, crear_tabla_alertas, ())

    # Buscar equipos inactivos
    query_inactivos = """
        SELECT Nombre, IP, InactivoDesde, Descripcion, Responsable, Ubicacion
        FROM EquiposAD
        WHERE InactivoDesde IS NOT NULL
    """
    inactivos = ejecutar_sql_fetch(conn, query_inactivos)

    if not inactivos:
        print("[ALERTAS] Ningún equipo está inactivo.")
        return

    ahora = datetime.now()
    hoy = ahora.date()

    for row in inactivos:
        nombre, ip, inactivo_desde, descripcion, responsable, ubicacion = row

        if not inactivo_desde:
            continue

        # Convertir si viene como string
        if isinstance(inactivo_desde, str):
            try:
                inactivo_desde = datetime.fromisoformat(inactivo_desde)
            except Exception:
                try:
                    inactivo_desde = datetime.strptime(inactivo_desde, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    print(f"[ALERTAS] No pude parsear InactivoDesde para {nombre}: {inactivo_desde}")
                    continue

        # Ver tiempo inactivo
        diff = ahora - inactivo_desde
        segundos_inactivo = diff.total_seconds()

        if segundos_inactivo < min_seconds:
            print(f"[ALERTAS] {nombre} inactivo {int(segundos_inactivo)}s < {min_seconds}s → se salta")
            continue

        # Evitar alertas duplicadas en el mismo día
        query_verificar = "SELECT 1 FROM AlertasEnviadas WHERE Nombre = ? AND Fecha = ?"
        ya = ejecutar_sql_fetch(conn, query_verificar, params=(nombre, hoy))
        if ya:
            continue

        # Payload a enviar
        payload = {
            "servidor": nombre,
            "ip": ip,
            "descripcion": descripcion,
            "responsable": responsable,
            "ubicacion": ubicacion,
            "inactivo_desde": inactivo_desde.isoformat(),
            "segundos_inactivo": int(segundos_inactivo)
        }

        headers = {}
        if secret:
            headers["Authorization"] = f"Bearer {generar_jwt(secret)}"

        # -----------------------------------------------
        # ENVÍO DE ALERTA
        # -----------------------------------------------
        try:
            resp = requests.post(webhook_url, json=payload, headers=headers, timeout=8)
            print(f"[ALERTA] Enviada → {nombre} → {resp.status_code}")

            if resp.status_code == 200:
                # Registrar que se envió hoy
                query_insert = "INSERT INTO AlertasEnviadas (Nombre, Fecha) VALUES (?, ?)"
                ejecutar_sql_reintento(conn, query_insert, params=(nombre, hoy))

                # ----------------------------------------------------------
                # 🔥 NUEVO: ACTUALIZAR COLUMNA `UltimoWebhook`
                # ----------------------------------------------------------
                query_update_webhook = """
                    UPDATE EquiposAD
                    SET UltimoWebhook = GETDATE()
                    WHERE Nombre = ?
                """
                ejecutar_sql_reintento(conn, query_update_webhook, params=(nombre,))

        except Exception as e:
            print(f"[ERROR ALERTA] No se pudo enviar a {nombre}: {e}")
            print("[ALERTAS] Se reintentará en el próximo ciclo.")
'''

import json
import requests
from datetime import datetime, timedelta
import jwt  # pip install PyJWT
from Datos.db_conexion_extras import ejecutar_sql_reintento, ejecutar_sql_fetch
from Datos.db_conexion import ejecutar_sql

import os
from cryptography.fernet import Fernet

WEBHOOK_CONFIG_PATH = "Configs/personal_info/webhook_config.json"
KEY_FILE = "secret.key"


# ----------------------------------------------------
# ENCRIPTACIÓN / DESENCRIPTACIÓN SOLO PARA SECRET
# ----------------------------------------------------
def cargar_key():
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
    else:
        with open(KEY_FILE, "rb") as f:
            key = f.read()

    return Fernet(key)


fernet = cargar_key()


def encrypt_value(value):
    if not value:
        return value
    return fernet.encrypt(value.encode()).decode()


def decrypt_value(value):
    if not value:
        return value
    try:
        return fernet.decrypt(value.encode()).decode()
    except Exception:
        return value


# ----------------------------------------------------
# CARGAR CONFIGURACIÓN DEL WEBHOOK
# ----------------------------------------------------
def cargar_webhook_config():
    """
    Devuelve dict con keys:
      { "webhook_url": str or None, "min_seconds_inactivo": int, "webhook_secret": str or None }
    """
    default = {"webhook_url": None, "min_seconds_inactivo": 60, "webhook_secret": None}

    try:
        with open(WEBHOOK_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        url = data.get("webhook_url") or data.get("url") or None
        min_sec = data.get("min_seconds_inactivo", data.get("min_seconds", 60))

        secret = data.get("webhook_secret")
        if secret:
            secret = decrypt_value(secret)

        try:
            min_sec = int(min_sec)
        except Exception:
            min_sec = 60

        return {
            "webhook_url": url,
            "min_seconds_inactivo": min_sec,
            "webhook_secret": secret,
        }

    except FileNotFoundError:
        return default

    except Exception as e:
        print("[WEBHOOK_CFG] Error leyendo config:", e)
        return default


# ----------------------------------------------------
# GUARDAR CONFIGURACIÓN (SOLO SE USA SI TIENES FORM GUI)
# ----------------------------------------------------
def guardar_webhook_config(data: dict):
    try:
        final_data = dict(data)
        if "webhook_secret" in final_data and final_data["webhook_secret"]:
            final_data["webhook_secret"] = encrypt_value(final_data["webhook_secret"])

        with open(WEBHOOK_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(final_data, f, indent=2)

        return True
    except Exception as e:
        print("[WEBHOOK_CFG] Error guardando:", e)
        return False


# ----------------------------------------------------
# GENERAR JWT OPCIONAL
# ----------------------------------------------------

def generar_jwt(secret):
    payload = {
        "iat": datetime.utcnow()  # Solo fecha de creación, sin expiración
    }

    token = jwt.encode(payload, secret, algorithm="HS256")

    if isinstance(token, bytes):
        token = token.decode("utf-8")

    return token


'''
def generar_jwt(secret, expiracion_segundos=3600):
    payload = {
        "exp": datetime.utcnow() + timedelta(seconds=expiracion_segundos),
        "iat": datetime.utcnow()
    }

    token = jwt.encode(payload, secret, algorithm="HS256")

    if isinstance(token, bytes):
        token = token.decode("utf-8")

    return token
'''

# ----------------------------------------------------
# ENVIAR ALERTAS DE INACTIVIDAD
# ----------------------------------------------------
def enviar_alertas_inactividad(conn):
    cfg = cargar_webhook_config()
    webhook_url = cfg["webhook_url"]
    min_seconds = cfg["min_seconds_inactivo"]
    secret = cfg.get("webhook_secret")

    if not webhook_url:
        print("[ALERTAS] No hay URL configurada. Saltando ciclo.")
        return

    # Crear tabla AlertasEnviadas si no existe
    crear_tabla_alertas = """
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='AlertasEnviadas' AND xtype='U')
        CREATE TABLE AlertasEnviadas (
            Nombre NVARCHAR(255),
            Fecha DATE
        )
    """
    ejecutar_sql_reintento(conn, crear_tabla_alertas, ())

    # Buscar equipos inactivos
    query_inactivos = """
        SELECT Nombre, IP, InactivoDesde, Descripcion, Responsable, Ubicacion
        FROM EquiposAD
        WHERE InactivoDesde IS NOT NULL
    """
    inactivos = ejecutar_sql_fetch(conn, query_inactivos)

    if not inactivos:
        print("[ALERTAS] Ningún equipo está inactivo.")
        return

    ahora = datetime.now()
    hoy = ahora.date()

    for row in inactivos:
        nombre, ip, inactivo_desde, descripcion, responsable, ubicacion = row

        if not inactivo_desde:
            continue

        # Convertir si viene como string
        if isinstance(inactivo_desde, str):
            try:
                inactivo_desde = datetime.fromisoformat(inactivo_desde)
            except Exception:
                try:
                    inactivo_desde = datetime.strptime(inactivo_desde, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    print(f"[ALERTAS] No pude parsear InactivoDesde para {nombre}: {inactivo_desde}")
                    continue

        # Ver tiempo inactivo
        diff = ahora - inactivo_desde
        segundos_inactivo = diff.total_seconds()

        if segundos_inactivo < min_seconds:
            print(f"[ALERTAS] {nombre} inactivo {int(segundos_inactivo)}s < {min_seconds}s → se salta")
            continue

        # Evitar alertas duplicadas en el mismo día
        query_verificar = "SELECT 1 FROM AlertasEnviadas WHERE Nombre = ? AND Fecha = ?"
        ya = ejecutar_sql_fetch(conn, query_verificar, params=(nombre, hoy))
        if ya:
            continue

        # Payload a enviar
        payload = {
            "servidor": nombre,
            "ip": ip,
            "descripcion": descripcion,
            "responsable": responsable,
            "ubicacion": ubicacion,
            "inactivo_desde": inactivo_desde.isoformat(),
            "segundos_inactivo": int(segundos_inactivo)
        }

        headers = {}
        if secret:
            headers["Authorization"] = f"Bearer {generar_jwt(secret)}"

        # -----------------------------------------------
        # ENVÍO DE ALERTA
        # -----------------------------------------------
        try:
            resp = requests.post(webhook_url, json=payload, headers=headers, timeout=8)
            print(f"[ALERTA] Enviada → {nombre} → {resp.status_code}")

            if resp.status_code == 200:
                # Registrar que se envió hoy
                query_insert = "INSERT INTO AlertasEnviadas (Nombre, Fecha) VALUES (?, ?)"
                ejecutar_sql_reintento(conn, query_insert, params=(nombre, hoy))

                # 🔥 Actualizar UltimoWebhook
                query_update_webhook = """
                    UPDATE EquiposAD
                    SET UltimoWebhook = GETDATE()
                    WHERE Nombre = ?
                """
                ejecutar_sql_reintento(conn, query_update_webhook, params=(nombre,))

        except Exception as e:
            print(f"[ERROR ALERTA] No se pudo enviar a {nombre}: {e}")
            print("[ALERTAS] Se reintentará en el próximo ciclo.")
