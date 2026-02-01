# Alfred AI - Bot de recordatorios (Telegram)


# 1. Estado actual del bot

## Resumen funcional
El bot permite crear recordatorios en lenguaje natural por Telegram. Interpreta el mensaje con OpenAI para extraer tarea y fecha, guarda el recordatorio en SQLite y programa una notificacion con APScheduler. Incluye flujo de registro por invitacion y comandos de administracion.

## Capacidades actuales
- Registro de usuarios con codigo de invitacion.
- Deteccion de ciudad y zona horaria del usuario durante el registro.
- Creacion de recordatorios con texto libre.
- Validacion de fechas (solo futuras).
- Listado de recordatorios pendientes.
- Eliminacion de recordatorios propios.
- Notificaciones automaticas cuando llega la hora.
- Mensajes de notificacion generados por OpenAI.
- Administracion: generar invitaciones, listar usuarios, revocar acceso.

## Flujo de usuario (registro)
1) Usuario escribe `/start`.
2) Si es admin, se le muestran comandos y finaliza el flujo.
3) Si no esta registrado, se solicita codigo de invitacion.
4) Se pide ciudad para inferir zona horaria.
5) Se solicita un nombre/apodo.
6) Se registra el usuario y queda activo.

## Flujo de usuario (recordatorios)
1) Usuario envia un mensaje con la tarea y la fecha.
2) Se genera contexto temporal (fecha/hora actual + zona horaria del usuario).
3) OpenAI devuelve JSON con tarea, fecha ISO y confirmacion.
4) Se parsea la fecha ISO y se valida que sea futura.
5) Se guarda en SQLite y se programa en APScheduler.
6) El bot responde con confirmacion y horario formateado.
7) Al llegar la hora, el scheduler dispara la notificacion.

## Comandos disponibles
- `/help`: ayuda general y ejemplos.
- `/list`: lista recordatorios pendientes del usuario.
- `/delete <id>`: elimina un recordatorio propio.
- `/start`: inicia flujo de registro (ConversationHandler).

Comandos admin (solo el user_id que esté guardado como admin):
- `/admin_invite`: genera codigo de invitacion.
- `/admin_users`: lista usuarios registrados.
- `/admin_revoke <user_id>`: desactiva usuario.



# 2. Infraestructura técnica

## Parte 1: Explicacion general del proyecto

### Requisitos
- Python 3.11+ (probado con 3.13 en el entorno actual)
- Token de bot de Telegram (BotFather)
- API key de OpenAI

### Estructura del proyecto (resumen)
- `main.py`: punto de entrada, inicializacion de servicios y arranque del bot.
- `bot/handlers.py`: comandos y mensajes de usuarios.
- `bot/registration.py`: flujo de registro por invitacion.
- `services/openai_service.py`: parseo de recordatorios + mensajes de notificacion con OpenAI.
- `services/time_service.py`: parseo/formatos de tiempo y zonas horarias.
- `services/city_service.py`: mapeo ciudad -> zona horaria via OpenAI.
- `database/db.py`: persistencia en SQLite (recordatorios, usuarios, invitaciones).
- `scheduler/reminder_scheduler.py`: programacion y ejecucion de recordatorios.
- `data/reminders.db`: base de datos (se crea/usa automaticamente).

### Flujo de uso
- Usuarios normales: deben registrarse con `/start` y un codigo de invitacion.
- Admin: con `/admin_invite` genera codigos. `/admin_users` lista usuarios. `/admin_revoke` desactiva.
- Uso normal: escribir un mensaje tipo "Recu�rdame ..." crea recordatorio.

### Base de datos
SQLite en `data/reminders.db`. Se crea automaticamente al iniciar.

### Troubleshooting
- Error de configuracion: revisa `.env` y que `ADMIN_USER_ID` sea numerico.
- OpenAI: valida la API key y el modelo configurado en `config.py`.
- Zonas horarias: el sistema usa IANA (ej: `Europe/Madrid`).

## Parte 2: Replicacion y despliegue

### Configuracion
1) Copia `.env.example` a `.env` y completa los valores:

```
TELEGRAM_TOKEN=...   # token del bot (BotFather)
OPENAI_API_KEY=...   # api key de OpenAI
DFT_TIMEZONE=Europe/Madrid
ADMIN_USER_ID=...    # tu user_id de Telegram
```

Notas:
- `ADMIN_USER_ID` es obligatorio. El admin puede generar codigos de invitacion.
- `DFT_TIMEZONE` se usa como fallback cuando un usuario no tiene zona horaria.

### Instalacion local (Windows / Linux / macOS)
Desde `alfred-ai-bot\app`:

```
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux/macOS
# source .venv/bin/activate

pip install -r requirements.txt
```

### Ejecucion local
```
python main.py
```

El bot iniciara en modo polling y quedara a la espera de mensajes.

### Docker (recomendado para despliegue simple)
1) Copia `.env.example` a `.env` y completa valores.
2) Construye la imagen:

```
docker build -t alfred-bot .
```

3) Ejecuta el contenedor (persistiendo la base de datos):

```
docker run --env-file .env -v ${PWD}/data:/app/data --name alfred-bot --restart unless-stopped alfred-bot
```

### Docker Compose
1) Copia `.env.example` a `.env` y completa valores.
2) Levanta el servicio:

```
docker compose up -d --build
```

3) Verifica logs:

```
docker compose logs -f
```

### Replicar el proceso en otra maquina (pasos claros)
1) Clona el repo en la nueva maquina.
2) Instala Python 3.11+.
3) Crea y activa un virtualenv.
4) Instala dependencias con `pip install -r requirements.txt`.
5) Copia `.env.example` a `.env` y completa valores.
6) Ejecuta `python main.py` para validar que inicia correctamente.

### Despliegue (produccion)
El bot funciona como proceso en primer plano. Para produccion se recomienda gestionarlo como servicio.

#### Opcion A: Linux (systemd)
Crea un servicio como `alfred-bot.service`:

```
[Unit]
Description=Alfred AI Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/ruta/al/proyecto/app
EnvironmentFile=/ruta/al/proyecto/app/.env
ExecStart=/ruta/al/proyecto/app/.venv/bin/python /ruta/al/proyecto/app/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Luego:
```
sudo systemctl daemon-reload
sudo systemctl enable alfred-bot
sudo systemctl start alfred-bot
sudo systemctl status alfred-bot
```

#### Opcion B: Windows (Task Scheduler o NSSM)
- **Task Scheduler**: crea una tarea que ejecute `python main.py` al iniciar sesion o al arrancar el sistema.
- **NSSM**: registra el script como servicio apuntando a `python.exe` y `main.py`.

### Logs
- El logging va a stdout. En servicios, redirige a archivo o usa el sistema de logs del SO.
