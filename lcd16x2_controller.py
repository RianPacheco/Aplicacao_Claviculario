import smbus2
import time

# Endereço padrão do PCF8574 I2C do LCD 16x2 no Raspberry Pi
I2C_ADDR = 0x27 

# Comandos do LCD
LCD_CHR = 1 # Enviando dados
LCD_CMD = 0 # Enviando comando

LCD_LINE_1 = 0x80 # 1ª linha do LCD
LCD_LINE_2 = 0xC0 # 2ª linha do LCD

LCD_BACKLIGHT = 0x08  # Luz de fundo ligada

ENABLE = 0b00000100 # Habilita bit

# Temporizadores
E_PULSE = 0.0005
E_DELAY = 0.0005

bus = smbus2.SMBus(1) # Abre /dev/i2c-1

def lcd_toggle_enable(bits):
    time.sleep(E_DELAY)
    bus.write_byte(I2C_ADDR, (bits | ENABLE))
    time.sleep(E_PULSE)
    bus.write_byte(I2C_ADDR, (bits & ~ENABLE))
    time.sleep(E_DELAY)

def lcd_byte(bits, mode):
    bits_high = mode | (bits & 0xF0) | LCD_BACKLIGHT
    bits_low = mode | ((bits << 4) & 0xF0) | LCD_BACKLIGHT
    bus.write_byte(I2C_ADDR, bits_high)
    lcd_toggle_enable(bits_high)
    bus.write_byte(I2C_ADDR, bits_low)
    lcd_toggle_enable(bits_low)

def iniciar_lcd():
    try:
        lcd_byte(0x33, LCD_CMD) # Inicializa
        lcd_byte(0x32, LCD_CMD) # Inicializa
        lcd_byte(0x06, LCD_CMD) # Cursor
        lcd_byte(0x0C, LCD_CMD) # Display on, cursor off
        lcd_byte(0x28, LCD_CMD) # 4 bits, 2 linhas
        lcd_byte(0x01, LCD_CMD) # Limpa tela
        time.sleep(E_DELAY)
    except Exception as e:
        print(f"Erro ao inicializar LCD I2C: {e}")

def lcd_limpar():
    lcd_byte(0x01, LCD_CMD)

def lcd_texto(linha1, linha2=""):
    lcd_byte(LCD_LINE_1, LCD_CMD)
    for char in linha1.ljust(16)[:16]:
        lcd_byte(ord(char), LCD_CHR)
    
    lcd_byte(LCD_LINE_2, LCD_CMD)
    for char in linha2.ljust(16)[:16]:
        lcd_byte(ord(char), LCD_CHR)

def lcd_texto_pausado(linha1, linha2, delay=2):
    lcd_texto(linha1, linha2)
    time.sleep(delay)

LCD_OK = True
