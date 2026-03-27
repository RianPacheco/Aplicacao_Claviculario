FROM python:3.11-slim

WORKDIR /app

# Dependências do sistema para SPI (RFID) e I2C (LCD)
RUN apt-get update && apt-get install -y \
    gcc \
    i2c-tools \
    && rm -rf /var/lib/apt/lists/*

# Dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código da aplicação
COPY . .

CMD ["python", "-u", "sistema_chaves_v3.py"]
