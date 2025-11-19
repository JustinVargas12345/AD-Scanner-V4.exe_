# AD Scanner – Monitor de Equipos y Alertas

## Descripción
**AD Scanner** es una herramienta automatizada para el monitoreo de equipos en un entorno de Active Directory (AD) y el envío de alertas a través de un webhook o API mediante peticiones HTTP POST. El sistema mantiene información actualizada sobre la actividad de los equipos, realiza pings periódicos y registra el estado de inactividad en la base de datos, incluyendo el último webhook enviado.

El proyecto está diseñado para ser estable y flexible, con configuración sencilla mediante interfaz gráfica y archivos de configuración. Es ideal para entornos corporativos donde se requiere un monitoreo constante de servidores y equipos de red.

---

## Características Principales
- Monitoreo en tiempo real de equipos en Active Directory.
- Envío automático de alertas vía POST a un webhook o API configurado.
- Registro de última actividad (`UltimoWebhook`) para evitar duplicidad de alertas.
- Interfaz gráfica sencilla para configurar credenciales de AD, base de datos y webhook.
- Registro de logs con rotación automática.
- Configuración de lapso mínimo para alertas de inactividad.
- JWT opcional para autenticar solicitudes POST.
- Las credenciales de AD y los passwords se almacenan cifrados usando `cryptography.Fernet`.
- Funciona como script ejecutable (`.exe`) o desde Python directamente.

---

## Requisitos Previos
- Python >= 3.10
- SQL Server o base de datos compatible.
- Permisos necesarios para acceder a AD y a la base de datos.
- Opcional: SQL Management Studio para validar credenciales.

---

## Instalación
1. Clonar el repositorio:
   ```powershell
   git clone https://github.com/usuario/nuevo-repo.git
   cd nuevo-repo
Instalar dependencias:

powershell
Copiar código
pip install -r requirements.txt
Generar ejecutable (opcional):

powershell
Copiar código
pyinstaller --onefile --console main.py
Mantener --console activo para monitorear logs en tiempo real.

Copiar archivo webhook_config.json en:

bash

Configs/personal_info/
Aquí se define la URL del webhook y el secreto opcional.

Configuración
Interfaz Gráfica
Al ejecutar el .exe se abrirá una interfaz con los campos estrictamente necesarios:

Active Directory:

Nombre del servidor

Usuario AD (cifrado)

Password AD (cifrado)

Base de búsqueda

Base de datos SQL:

Driver

Servidor

Base de datos

Usuario / Password (opcional si Trusted Connection está activado)

Webhook / API:

URL donde se enviarán los POST

JWT opcional (secreto)

Intervalos de ping y alertas:

Intervalo de chequeo de equipos

Lapso mínimo para alertas de inactividad (configurable en personal_info)

Recomendación: Mantener SQL Server con Trusted Connection activado para mayor estabilidad de conexión. Tener a mano SQL Management Studio facilita la verificación de credenciales y conectividad.

Archivo de Configuración
Configs/personal_info/webhook_config.json
Contiene:

json
{
  "webhook_url": "https://miapi.com/post",
  "webhook_secret": "secretoOpcional",
  "min_seconds_inactivo": 86400
}

webhook_url: URL a donde se enviarán las alertas.

webhook_secret: JWT opcional para autenticar POSTs.

min_seconds_inactivo: Tiempo mínimo en segundos para enviar alerta de inactividad del mismo equipo (por defecto 24 horas = 86400 segundos).

Logs:
Se almacenan en Configs/personal_info/logs.txt. Contienen principalmente eventos fallidos y estadísticas de ejecución.

Funcionamiento
El script se conecta a AD y consulta todos los equipos.

Realiza ping a cada equipo para verificar actividad.

Inserta o actualiza información en la base de datos (EquiposAD).

Envía POST al webhook configurado si el equipo está inactivo por más del lapso definido.

Registra en la tabla AlertasEnviadas y actualiza la columna UltimoWebhook para evitar duplicidad.

Logs se generan en tiempo real en la terminal y en archivo de logs. Se recomienda minimizar la terminal, no cerrarla, para mantener ejecución continua.

Manejo de Errores
Conexión a Base de Datos:
Si la conexión falla por credenciales inválidas o cambios de configuración, se recomienda reiniciar el script o contactar al desarrollador.

Credenciales AD:
Cambios en las credenciales requieren reinicio del script.

Webhook:
Errores en envío se registran en logs y se reintentará en el siguiente ciclo.

Seguridad
Los secretos (AD password, DB password, webhook secret) se almacenan cifrados usando cryptography.Fernet.

JWT opcional para autenticación de POSTs.

Evita enviar información sensible sin cifrado sobre la red.

Ejecución
Ejecutar desde Python:

powershell
Copiar código
python main.py
Ejecutar desde .exe:

powershell
Copiar código
./dist/main.exe
Consideraciones
Mantener el script corriendo continuamente para monitoreo activo.

Si se cierra la terminal o el .exe se detiene, se interpreta como finalización de ejecución.

El lapso predeterminado entre alertas del mismo servidor es 24 horas, configurable.

Es importante colocar los datos de AD y SQL con precaución, revisando que sean correctos antes de guardar.

Paquetes Python Usados
altgraph==0.17.4

certifi==2025.10.5

cffi==2.0.0

charset-normalizer==3.4.4

cryptography==46.0.3

customtkinter==5.2.2

darkdetect==0.8.0

idna==3.11

ldap3==2.9.1

numpy==2.3.4

packaging==25.0

pandas==2.3.3

pefile==2023.2.7

pillow==11.3.0

ping3==5.1.5

psutil==7.1.3

pyasn1==0.6.1

pycparser==2.23

pyinstaller==6.16.0

pyinstaller-hooks-contrib==2025.9

PyJWT==2.10.1

pyodbc==5.3.0

pyspnego==0.12.0

python-dateutil==2.9.0.post0

pytz==2025.2

pywin32==311

pywin32-ctypes==0.2.3

pywinrm==0.5.0

requests==2.32.5

requests_ntlm==1.3.0

setuptools==80.9.0

six==1.17.0

sspilib==0.4.0

ttkbootstrap==1.18.2

tzdata==2025.2

urllib3==2.5.0

WMI==1.5.1

xmltodict==1.0.2

Futuras Mejoras
Soporte para múltiples webs/webhooks.

Integración con notificaciones por correo electrónico.

Dashboard web para visualización de alertas y estadísticas.

Soporte multi-tenant para diferentes dominios AD.

AD Scanner está diseñado para ejecutarse de manera continua y confiable, garantizando que cada alerta se envíe de forma controlada y segura, minimizando riesgos de duplicidad o pérdida de información sensib