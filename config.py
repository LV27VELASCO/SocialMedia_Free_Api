import os
from dotenv import load_dotenv

# Detecta el entorno desde variable de sistema o usa 'local' por defecto
environment = os.getenv("ENV", "local")

# Determina qué archivo cargar
env_file = f".env.{environment}"

# Carga variables
load_dotenv(env_file)
