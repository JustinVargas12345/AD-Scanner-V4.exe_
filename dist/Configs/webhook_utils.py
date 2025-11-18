# webhook_utils.py  (o pégalo dentro de webhook_alerts.py)
import traceback
from Configs.webhook_alerts import enviar_alertas_inactividad
from Configs.logs_utils import escribir_log

def enviar_notificacion_webhook(conn):
    """
    Wrapper seguro: llama a enviar_alertas_inactividad(conn).
    Si ocurre cualquier excepción, lo registra en logs y no propaga el error.
    """
    try:
        enviar_alertas_inactividad(conn)
    except Exception as e:
        # Registrar el error pero NO detener el programa
        escribir_log(f"Error en enviar_notificacion_webhook: {e}", tipo="ERROR")
        # opcional: también volcar stack trace al log
        escribir_log(traceback.format_exc(), tipo="ERROR")
