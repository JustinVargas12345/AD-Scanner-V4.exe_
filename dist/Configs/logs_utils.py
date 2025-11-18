'''
import os
from datetime import datetime

LOG_FILE = "ad_scanner.log"
LOG_MAX_LINES = 1000

def escribir_log(mensaje, tipo="INFO"):
    """
    Escribe un mensaje en el log con timestamp y tipo de mensaje.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linea = f"[{timestamp}] [{tipo}] {mensaje}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(linea)






def eliminar_logs():
    """
    Revisa el archivo de logs y elimina las líneas más antiguas si supera LOG_MAX_LINES.
    Solo conserva las últimas LOG_MAX_LINES.
    """
    if not os.path.exists(LOG_FILE):
        return  # No hay archivo que limpiar

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lineas = f.readlines()

        if len(lineas) > LOG_MAX_LINES:
            # Solo conservar las últimas LOG_MAX_LINES
            lineas = lineas[-LOG_MAX_LINES:]
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(lineas)
            print(f"[INFO] Logs limpiados automáticamente. Se conservaron las últimas {LOG_MAX_LINES} líneas.")
    except Exception as e:
        print(f"[ERROR] No se pudo limpiar el log: {e}")
'''

import os
from datetime import datetime

LOG_FILE = "ad_scanner.log"
LOG_MAX_MB = 5               # Tamaño máximo permitido antes de rotar (en MB)
LOG_MAX_BACKUPS = 5          # Cantidad de archivos de respaldo


def _rotar_logs():
    """
    Rota los archivos de log cuando el archivo principal supera el tamaño permitido.
    Mueve:
      ad_scanner.log -> ad_scanner.log.1
      ad_scanner.log.1 -> ad_scanner.log.2
      ...
    """
    # Eliminar el backup más viejo si excede el límite
    ultimo_backup = f"{LOG_FILE}.{LOG_MAX_BACKUPS}"
    if os.path.exists(ultimo_backup):
        os.remove(ultimo_backup)

    # Rotar en reversa (4->5, 3->4, 2->3...)
    for i in range(LOG_MAX_BACKUPS - 1, 0, -1):
        origen = f"{LOG_FILE}.{i}"
        destino = f"{LOG_FILE}.{i+1}"
        if os.path.exists(origen):
            os.rename(origen, destino)

    # Ahora rotamos el archivo principal
    if os.path.exists(LOG_FILE):
        os.rename(LOG_FILE, f"{LOG_FILE}.1")


def _excede_tamano_maximo():
    """
    Devuelve True si el archivo principal supera LOG_MAX_MB megabytes.
    """
    if not os.path.exists(LOG_FILE):
        return False

    tamano_bytes = os.path.getsize(LOG_FILE)
    tamano_mb = tamano_bytes / (1024 * 1024)

    return tamano_mb >= LOG_MAX_MB


def escribir_log(mensaje, tipo="INFO"):
    """
    Escribe un mensaje al log y rota automáticamente cuando el archivo
    exceda el tamaño máximo configurado.
    """
    # Revisar si debe rotarse
    try:
        if _excede_tamano_maximo():
            _rotar_logs()
    except Exception as e:
        print(f"[WARN] No se pudo verificar el tamaño del log: {e}")

    # Escribir mensaje
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linea = f"[{timestamp}] [{tipo}] {mensaje}\n"

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(linea)
    except Exception as e:
        print(f"[ERROR] No se pudo escribir en el log: {e}")
