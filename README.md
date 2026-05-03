# CPT Route Manager 🚚

Este proyecto es una aplicación web basada en **Flask** diseñada para facilitar la gestión, visualización y generación de reportes de rutas de transporte (específicamente centrada en rutas con origen CLRM03 y agrupación por CPT - *Critical Pull Time*).

El sistema está preparado para recibir archivos CSV con la planificación de rutas, procesar los datos bajo reglas de negocio específicas, y presentarlos de manera amigable tanto en una interfaz web interactiva como en documentos PDF listos para imprimir o compartir.

## 🌟 ¿Qué problema resuelve?

En la operación logística diaria, las empresas de transporte manejan grandes volúmenes de datos sobre rutas, conductores, horarios de salida (ETD) y destinos. Manejar esta información directamente desde archivos CSV o Excel en crudo es ineficiente y propenso a errores. 

Este proyecto resuelve este problema automatizando:
- **Limpieza y filtrado de datos:** Oculta información irrelevante y aplica filtros por rangos horarios de operación.
- **Agrupación inteligente:** Clasifica automáticamente las rutas según su horario CPT y las agrupa geográficamente por zonas (Sur, Centro, Norte, Metropolitana).
- **Gestión de Conductores y Rutas Manuales:** Permite mantener un directorio de teléfonos de conductores y añadir rutas de última hora que no venían en el archivo original, manteniendo todo centralizado.
- **Generación de Reportes:** Crea instantáneamente un documento PDF estructurado y fácil de leer para los despachadores y operadores de patio.

## ✨ Características Principales

* **Subida y Procesamiento de CSV:** Interfaz para cargar la matriz de rutas diaria y procesarla al instante.
* **Dashboard "Ver Rutas":** 
  * Vista agrupada por CPT (horario de corte).
  * Vista agrupada por zonas geográficas.
  * Resumen de volumen total de rutas.
* **Generación de PDF:** Creación automática de un reporte en PDF utilizando `reportlab`, con formato de tablas, casillas de verificación (arribo/partida) y espacio para observaciones.
* **Panel de Administración:**
  * Acceso protegido por contraseña.
  * Gestión de contactos (teléfonos) de los conductores.
  * Capacidad de agregar o eliminar rutas manualmente.
* **Persistencia en la Nube:** Integración nativa con **Vercel KV (Upstash Redis)** para almacenar estados de subida, rutas manuales y contactos temporalmente, con un *fallback* a archivos JSON locales para entornos de desarrollo.

## 🛠️ Tecnologías Utilizadas

* **Backend:** Python con [Flask](https://flask.palletsprojects.com/)
* **Generación de PDF:** [ReportLab](https://pypi.org/project/reportlab/)
* **Base de Datos / Caché:** [Redis](https://redis.io/) (Vercel KV)
* **Frontend:** HTML5, CSS3, y Jinja2 (Templates de Flask)
* **Despliegue:** Optimizado para despliegue serverless en [Vercel](https://vercel.com/) (incluye archivo `vercel.json`).

## 🚀 Instalación y Ejecución Local

1. Clona el repositorio:
   ```bash
   git clone <URL_DEL_REPOSITORIO>
   cd CPT_routes
   ```

2. Crea un entorno virtual (opcional pero recomendado):
   ```bash
   python -m venv venv
   source venv/bin/activate # En Windows usa: venv\Scripts\activate
   ```

3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

4. Variables de Entorno (Opcional):
   Puedes configurar las siguientes variables de entorno para usar las funciones completas. Si no configuras Redis, la app usará archivos temporales locales para funcionar.
   - `APP_PASSWORD`: Contraseña para el panel de admin (por defecto: `admin123`).
   - `SECRET_KEY`: Llave secreta para las sesiones de Flask.
   - `KV_URL` o `REDIS_URL`: URL de conexión a tu base de datos Redis.

5. Ejecuta la aplicación:
   ```bash
   python app.py
   ```
   La aplicación estará disponible en `http://localhost:5000`.

## 📁 Estructura del Proyecto

* `app.py`: Archivo principal que contiene toda la lógica del backend, el enrutamiento de Flask y la generación de reportes.
* `/templates/`: Contiene las vistas HTML (login, subida de archivos, dashboard de rutas, panel de administración).
* `/static/`: Archivos estáticos como hojas de estilo (CSS) e imágenes.
* `/json/`: Archivos de configuración estática (como `ramplas.json`).
* `requirements.txt`: Lista de dependencias de Python.
* `vercel.json`: Configuración para el despliegue en Vercel.
