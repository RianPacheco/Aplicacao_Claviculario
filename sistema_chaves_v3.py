import time
import mysql.connector
from mysql.connector import Error
from enum import Enum

# Importar o controlador LCD
from lcd16x2_controller import (
    iniciar_lcd, lcd_texto, lcd_texto_pausado,
    lcd_limpar, LCD_OK
)

# =========================
# MÁQUINA DE ESTADOS
# =========================
class Estado(Enum):
    IDLE                = 1   # Esperando qualquer crachá
    PROFESSOR_OK        = 2   # Professor reconhecido, verificando situação
    AGUARDANDO_DEVOLUCAO = 3  # Professor tem chave, aguarda passar a chave
    AGUARDANDO_CHAVE    = 4   # Professor livre, aguarda chave para pegar

# Contexto da transação atual (substitui o Estado.professor_atual)
ctx = {
    "professor": None,        # {"id": int, "nome": str}
    "emprestimo": None,       # (emprestimo_id, chave_id) quando há devolução pendente
}

# =========================
# BANCO DE DADOS
# =========================
def conectar_banco():
    """Conecta ao MariaDB. Host 'db' funciona no Docker, 'localhost' fora dele."""
    import os
    host = os.environ.get("DB_HOST", "localhost")
    return mysql.connector.connect(
        host=host,
        user=os.environ.get("DB_USER", "app_chaves"),
        password=os.environ.get("DB_PASSWORD", "chaves123"),
        database=os.environ.get("DB_NAME", "chaves_professores"),
        autocommit=False,
        connection_timeout=5
    )

def garantir_conexao(conexao):
    """Reconecta automaticamente se a conexão caiu."""
    try:
        conexao.ping(reconnect=True, attempts=3, delay=1)
        return conexao
    except Error as e:
        print(f"Conexão perdida: {e}. Tentando reconectar...")
        try:
            return conectar_banco()
        except Error:
            return None

# =========================
# LEITURA RFID
# =========================
def aguardar_rfid_idle(leitor):
    """
    Modo IDLE: fica bloqueado esperando qualquer cartão sem timeout.
    Retorna o id_str quando algo for lido.
    """
    print("Aguardando crachá...")
    while True:
        try:
            id_cartao, _ = leitor.read_no_block()
            if id_cartao is not None:
                id_str = str(id_cartao).strip()
                print(f"RFID lido: {id_str}")
                return id_str
        except Exception as e:
            print(f"Erro de leitura RFID: {e}")
        time.sleep(0.15)

def ler_rfid_com_timeout(leitor, timeout=20):
    """
    Lê RFID com timeout (usado após identificar o professor).
    Retorna id_str ou None se timeout.
    """
    print(f"Aguardando cartão (timeout: {timeout}s)...")
    inicio = time.time()
    falhas = 0

    while (time.time() - inicio) < timeout:
        try:
            id_cartao, _ = leitor.read_no_block()
            if id_cartao is not None:
                return str(id_cartao).strip()

            restante = int(timeout - (time.time() - inicio))
            if restante % 3 == 0:
                lcd_texto("Passe a chave...", f"Timeout: {restante}s")

        except Exception as e:
            falhas += 1
            if falhas > 50:
                print("Muitas falhas de leitura, abortando.")
                break

        time.sleep(0.15)

    print("Timeout — nenhum cartão lido.")
    return None

# =========================
# CONSULTAS AO BANCO
# =========================
def buscar_professor(cursor, rfid):
    """Busca professor pelo código RFID. Retorna dict ou None."""
    # CORREÇÃO: coluna é 'codigo', não 'codigo_rfid'
    cursor.execute(
        "SELECT id, nome FROM professores WHERE codigo = %s LIMIT 1",
        (rfid,)
    )
    row = cursor.fetchone()
    if row:
        return {"id": row[0], "nome": row[1]}
    return None

def buscar_chave(cursor, rfid):
    """Busca chave pelo código RFID. Retorna dict ou None."""
    # CORREÇÃO: coluna é 'codigo', não 'codigo_rfid'
    cursor.execute(
        "SELECT id, nome_da_chave FROM chaves WHERE codigo = %s LIMIT 1",
        (rfid,)
    )
    row = cursor.fetchone()
    if row:
        return {"id": row[0], "nome": row[1]}
    return None

def professor_tem_chave_ativa(cursor, professor_id):
    """Retorna (emprestimo_id, chave_id, nome_chave) ou None."""
    cursor.execute(
        """
        SELECT pc.id, c.id, c.nome_da_chave
        FROM professor_chaves pc
        JOIN chaves c ON c.id = pc.chave_id
        WHERE pc.professor_id = %s AND pc.data_devolucao IS NULL
        LIMIT 1
        """,
        (professor_id,)
    )
    return cursor.fetchone()

# =========================
# TRANSAÇÕES
# =========================
def registrar_devolucao(cursor, conexao, emprestimo_id):
    """Registra devolução. Retorna True/False."""
    try:
        cursor.execute(
            """
            UPDATE professor_chaves
            SET data_devolucao = NOW()
            WHERE id = %s AND data_devolucao IS NULL
            """,
            (emprestimo_id,)
        )
        if cursor.rowcount == 0:
            print(f"Empréstimo {emprestimo_id} não encontrado ou já devolvido.")
            return False
        conexao.commit()
        print(f"Devolução registrada: empréstimo {emprestimo_id}")
        return True
    except Error as e:
        print(f"Erro ao registrar devolução: {e}")
        try:
            conexao.rollback()
        except:
            pass
        return False

def registrar_emprestimo(cursor, conexao, professor_id, chave_id):
    """
    Registra empréstimo com validações.
    Retorna: 'ok' | 'professor_com_chave' | 'chave_indisponivel' | 'erro'
    """
    try:
        cursor.execute(
            "SELECT id FROM professor_chaves WHERE professor_id = %s AND data_devolucao IS NULL LIMIT 1",
            (professor_id,)
        )
        if cursor.fetchone():
            return "professor_com_chave"

        cursor.execute(
            "SELECT id FROM professor_chaves WHERE chave_id = %s AND data_devolucao IS NULL LIMIT 1",
            (chave_id,)
        )
        if cursor.fetchone():
            return "chave_indisponivel"

        cursor.execute(
            "INSERT INTO professor_chaves (professor_id, chave_id, data_emprestimo) VALUES (%s, %s, NOW())",
            (professor_id, chave_id)
        )
        conexao.commit()
        print(f"Empréstimo registrado: professor {professor_id} -> chave {chave_id}")
        return "ok"

    except Error as e:
        print(f"Erro ao registrar empréstimo: {e}")
        try:
            conexao.rollback()
        except:
            pass
        return "erro"

# =========================
# MÁQUINA DE ESTADOS PRINCIPAL
# =========================
def loop_principal(leitor, conexao):
    """
    Loop principal da máquina de estados.

    Arquitetura:
    - IDLE: fica bloqueado esperando crachá (sem timeout, sem loop ocupado)
    - Ao reconhecer o professor, decide o próximo estado imediatamente
    - Cada estado seguinte aguarda a chave com timeout de 20s
    - Sempre volta para IDLE ao final da operação (ok ou timeout)
    """
    estado = Estado.IDLE

    while True:
        try:
            cursor = conexao.cursor()

            # ── IDLE: aguarda crachá do professor ────────────────────────
            if estado == Estado.IDLE:
                ctx["professor"] = None
                ctx["emprestimo"] = None

                lcd_texto("SISTEMA CHAVES", "Passe o cracha")
                print("\n" + "="*50)
                print("IDLE — aguardando crachá...")

                rfid = aguardar_rfid_idle(leitor)

                conexao = garantir_conexao(conexao)
                if not conexao:
                    lcd_texto("ERRO BD!", "Reconectando...")
                    time.sleep(3)
                    continue

                cursor = conexao.cursor()
                professor = buscar_professor(cursor, rfid)

                if not professor:
                    print(f"RFID {rfid} não é professor.")
                    lcd_texto("Nao reconhecido", "Tente novamente")
                    time.sleep(2)
                    continue  # Fica no IDLE

                # Professor reconhecido
                ctx["professor"] = professor
                print(f"Professor: {professor['nome']}")
                lcd_texto("Bem-vindo!", professor["nome"][:16])
                time.sleep(1.5)
                estado = Estado.PROFESSOR_OK

            # ── PROFESSOR_OK: decide o fluxo ─────────────────────────────
            elif estado == Estado.PROFESSOR_OK:
                professor = ctx["professor"]
                chave_ativa = professor_tem_chave_ativa(cursor, professor["id"])

                if chave_ativa:
                    emprestimo_id, chave_id, nome_chave = chave_ativa
                    ctx["emprestimo"] = (emprestimo_id, chave_id)

                    print(f"Chave pendente: {nome_chave}")
                    lcd_texto("Devolver:", nome_chave[:16])
                    time.sleep(1)
                    estado = Estado.AGUARDANDO_DEVOLUCAO
                else:
                    print("Professor pode pegar chave.")
                    lcd_texto("Pegar chave:", "Passe a chave")
                    time.sleep(1)
                    estado = Estado.AGUARDANDO_CHAVE

            # ── AGUARDANDO_DEVOLUCAO ──────────────────────────────────────
            elif estado == Estado.AGUARDANDO_DEVOLUCAO:
                emprestimo_id, chave_id_esperada = ctx["emprestimo"]

                lcd_texto("Passe a chave", "para devolver")
                rfid_chave = ler_rfid_com_timeout(leitor, timeout=20)

                if not rfid_chave:
                    lcd_texto("Timeout!", "Operacao cancelada")
                    time.sleep(2)
                    estado = Estado.IDLE
                    continue

                chave = buscar_chave(cursor, rfid_chave)

                if not chave:
                    lcd_texto("RFID invalido!", "Nao e uma chave")
                    time.sleep(2)
                    estado = Estado.IDLE
                    continue

                if chave["id"] != chave_id_esperada:
                    print(f"Chave errada! Esperava {chave_id_esperada}, recebeu {chave['id']}")
                    lcd_texto("Chave errada!", "Tente novamente")
                    time.sleep(2)
                    estado = Estado.IDLE
                    continue

                if registrar_devolucao(cursor, conexao, emprestimo_id):
                    lcd_texto("Devolvido!", "Obrigado :)")
                    time.sleep(3)
                else:
                    lcd_texto("ERRO no BD!", "Tente depois")
                    time.sleep(2)

                estado = Estado.IDLE

            # ── AGUARDANDO_CHAVE (empréstimo) ─────────────────────────────
            elif estado == Estado.AGUARDANDO_CHAVE:
                professor = ctx["professor"]

                lcd_texto("Passe a chave", "para pegar")
                rfid_chave = ler_rfid_com_timeout(leitor, timeout=20)

                if not rfid_chave:
                    lcd_texto("Timeout!", "Operacao cancelada")
                    time.sleep(2)
                    estado = Estado.IDLE
                    continue

                chave = buscar_chave(cursor, rfid_chave)

                if not chave:
                    lcd_texto("RFID invalido!", "Nao e uma chave")
                    time.sleep(2)
                    estado = Estado.IDLE
                    continue

                resultado = registrar_emprestimo(cursor, conexao, professor["id"], chave["id"])

                if resultado == "ok":
                    lcd_texto("Emprestado!", "Boa aula! :)")
                    time.sleep(3)
                elif resultado == "professor_com_chave":
                    lcd_texto("Voce ja tem", "uma chave!")
                    time.sleep(2.5)
                elif resultado == "chave_indisponivel":
                    lcd_texto("Chave ocupada!", "Outro professor")
                    time.sleep(2.5)
                else:
                    lcd_texto("ERRO no BD!", "Tente depois")
                    time.sleep(2)

                estado = Estado.IDLE

        except KeyboardInterrupt:
            raise

        except Exception as e:
            print(f"Erro no ciclo: {type(e).__name__} - {e}")
            lcd_texto("ERRO!", str(e)[:16])
            time.sleep(2)
            estado = Estado.IDLE

        finally:
            try:
                cursor.close()
            except:
                pass

# =========================
# MAIN
# =========================
def main():
    print("Iniciando Sistema de Controle de Chaves...")
    print(f"Hora: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    iniciar_lcd()

    # Inicializar RFID
    try:
        from mfrc522 import SimpleMFRC522
        leitor_rfid = SimpleMFRC522()
        print("Leitor RFID inicializado.")
    except Exception as e:
        print(f"Erro ao inicializar RFID: {e}")
        lcd_texto("ERRO RFID!", "Verifique hw")
        return

    conexao = None

    try:
        print("Conectando ao banco de dados...")
        conexao = conectar_banco()
        print("Conectado ao banco!")
        lcd_texto("SISTEMA PRONTO", "Aguardando...")
        time.sleep(2)

        loop_principal(leitor_rfid, conexao)

    except KeyboardInterrupt:
        print("\nEncerrando (Ctrl+C)...")
        lcd_texto("Encerrando...", "Aguarde")

    except Error as e:
        print(f"Erro de conexão: {e}")
        lcd_texto("ERRO BD!", str(e)[:16])

    finally:
        if conexao and conexao.is_connected():
            try:
                conexao.close()
                print("Conexão BD fechada.")
            except:
                pass

        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup()
            print("GPIO limpo.")
        except:
            pass

        lcd_texto("SISTEMA", "ENCERRADO")
        print("Sistema finalizado.")

if __name__ == "__main__":
    main()
