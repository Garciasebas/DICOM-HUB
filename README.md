# DICOM-HUB

Sistema web para la gestión de imágenes médicas en formato DICOM orientado a proyectos de investigación. DICOM-HUB permite organizar participantes y experimentos, administrar archivos DICOM y exportar conjuntos de datos al formato BIDS.

> **Nota:** Este proyecto se desarrolló con fines académicos y de investigación. Antes de utilizarlo con datos médicos reales, se deben evaluar y configurar adecuadamente las medidas de seguridad, privacidad, respaldo y cumplimiento normativo aplicables. La exportación BIDS incluye un proceso de anonimización; no se debe asumir que los archivos cargados quedan anonimizados automáticamente.

## Funcionalidades principales

- Gestión de participantes y sus datos demográficos.
- Organización de participantes en experimentos y grupos.
- Carga y administración de archivos DICOM.
- Gestión de documentos de consentimiento.
- Visualización de información asociada a los archivos.
- Exportación de experimentos al formato BIDS con anonimización durante la exportación.

## Tecnologías

- Python 3.12
- Django
- PostgreSQL 15
- Docker y Docker Compose
- Gunicorn
- WhiteNoise

## Requisitos

Para ejecutar la aplicación mediante Docker, necesitás:

- [Git](https://git-scm.com/)
- [Docker](https://docs.docker.com/get-docker/) con Docker Compose
- Un puerto local disponible: **8000** para la aplicación y **5432** para PostgreSQL (si se mantienen los puertos definidos en Compose)

No es necesario instalar Python ni PostgreSQL directamente en el equipo anfitrión para utilizar la configuración Docker.

## Instalación y ejecución con Docker Compose

### 1. Clonar el repositorio

```bash
git clone https://github.com/Garciasebas/DICOM-HUB.git
cd DICOM-HUB/dicom_project
```

### 2. Crear el archivo de entorno

Copiá el archivo de ejemplo:

**PowerShell (Windows):**

```powershell
Copy-Item .env.example .env
```

**Linux / macOS:**

```bash
cp .env.example .env
```

Editá el archivo `.env` y configurá, como mínimo, estas variables:

```dotenv
DB_HOST=db
DB_PORT=5432
DB_NAME=dicom_db
DB_USER=postgres
DB_PASSWORD=una_contrasena_segura

SECRET_KEY=una_clave_secreta_larga_y_aleatoria
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1
```

Usá valores propios para `DB_PASSWORD` y `SECRET_KEY`. No publiques el archivo `.env` ni compartas sus secretos. Para acceder desde otro host, ajustá `ALLOWED_HOSTS` de acuerdo con el nombre o la dirección utilizada.

### 3. Construir e iniciar los servicios

Desde el directorio `dicom_project`, ejecutá:

```bash
docker compose up --build -d
```

Docker Compose construye la imagen de Django e inicia los servicios `web` y `db`. El contenedor de la aplicación espera a PostgreSQL y, mediante el script de inicio, ejecuta las migraciones y la recolección de archivos estáticos antes de iniciar Gunicorn.

### 4. Crear el usuario administrador

```bash
docker compose exec web python manage.py createsuperuser
```

Seguí las indicaciones para definir el nombre de usuario, correo electrónico y contraseña del administrador.

### 5. Abrir la aplicación

Ingresá desde el navegador a:

- Aplicación: [http://localhost:8000/](http://localhost:8000/)
- Inicio de sesión: [http://localhost:8000/login/](http://localhost:8000/login/)
- Administración de Django: [http://localhost:8000/admin/](http://localhost:8000/admin/)

La ruta raíz redirige al inicio de sesión. Accedé con el usuario creado en el paso anterior.

## Comandos útiles

Ejecutar las pruebas de Django:

```bash
docker compose exec web python manage.py test dicom_app
```

Ver los registros de los servicios:

```bash
docker compose logs -f
```

Detener los contenedores sin eliminar los datos persistidos:

```bash
docker compose down
```

Volver a iniciar los servicios:

```bash
docker compose up -d
```

> **Importante:** los datos de PostgreSQL se almacenan en el volumen Docker `dicom_postgres_data`, y los archivos cargados se guardan en el directorio `dicom_project/media`. Para preservar los datos, no elimines los volúmenes ni el directorio de medios sin contar previamente con un respaldo. El comando `docker compose down -v` elimina los volúmenes asociados y puede provocar pérdida de datos.

## Estructura general

```text
DICOM-HUB/
├── README.md
└── dicom_project/
    ├── Dockerfile
    ├── docker-compose.yml
    ├── .env.example
    ├── entrypoint.sh
    ├── manage.py
    ├── dicom_project/       # Configuración del proyecto Django
    └── dicom_app/           # Aplicación, modelos, vistas, templates y pruebas
```

## Datos y privacidad

DICOM-HUB trabaja con imágenes médicas y documentos relacionados con participantes. Utilizá datos de prueba o debidamente autorizados durante el desarrollo. Restringí el acceso al sistema y a los archivos almacenados, protegé las credenciales y realizá respaldos adecuados.

La anonimización se aplica durante la exportación a BIDS. La carga de un archivo DICOM no implica por sí misma que el archivo original haya sido anonimizado.

## Proyecto académico

DICOM-HUB forma parte de un trabajo académico orientado a la gestión de imágenes DICOM y la preparación de datos de neuroimagen para investigación.
