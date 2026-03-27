import time
import os
import mysql.connector
from mysql.connector import Error
from enum import Enum

# Importar o controlador LCD local (lcd16x2_controller.py)
from lcd16x2_controller import (
    iniciar_lcd, lcd_texto, lcd_limpar, LCD_OK
)

# ============================================================
# ⚙️ MÁQUINA DE ESTADOS
# ============================================================
class Estado(Enum):
    IDLE                 = 1   # Esperando qualquer crachá
    PROFESSOR_OK         = 2   # Professor reconhecido, verificando situação
    AGUARDANDO_DEVOLUCAO = 3   # Professor tem chave, aguarda passar a chave
    AGUARDANDO_CHAVE     = 4   # Professor livre, aguarda chave para pegar

# Contexto da transação atual
ctx = {
    "professor": None,        # {"id": int, "nome": str}
    "emprestimo": None,       # (emprestimo_id, chave_id) quando há devolução pendente
}

# ============================================================
# 🗄️ BANCO DE DADOS (Com Retry Automático para Docker)
# ============================================================
def conectar_banco():
    """Conecta ao MariaDB com sistema de Retry para Docker."""
    host = os.environ.get("DB_HOST", "db")
    user = os.environ.get("DB_USER", "app_chaves")
    password = os.environ.get("DB_PASSWORD", "chaves123")
    database = os.environ.get("DB_NAME", "chaves_professores")

    tentativas = 5
    for i in range(tentativas):
        try:
            print(f"[{time.strftime('%H:%M:%S')}] Tentando conectar ao banco ({i+1}/{tentativas})...")
            conn = mysql.connector.connect(
                host=host,
                user=user,
                password=password,
                database=database,
                autocommit=False,
                connection_timeout=5
            )
            print("✅ Conectado ao MariaDB com sucesso!")
            return conn
        except Error as err:
            print(f"⚠️ Banco ainda não respondeu (Erro {err.errno}). Aguardando 5 segundos...")
            time.sleep(5)
            
    raise Exception("❌ Não foi possível conectar ao banco de dados após várias tentativas.")

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

# ============================================================
# 📡 LEITURA RFID
# ============================================================
def aguardar_rfid_idle(leitor):
    """
    Modo IDLE: fica bloqueado esperando qualquer cartão sem timeout.
    Retorna o id_str quando algo for lido.
    """
    print("\n[Aguardando leitura do crachá na porta física...]")
    while True:
        try:
            id_cartao, _ = leitor.read_no_block()
            if id_cartao is not None:
                id_str = str(id_cartao).strip()
                print(f"📡 RFID lido fisicamente: {id_str}")
                return id_str
        except Exception as e:
            print(f"Erro de leitura RFID no IDLE: {e}")
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
                print("Muitas falhas de leitura, abortando timeout.")
                break

        time.sleep(0.15)

    print("Timeout — nenhum cartão lido.")
    return None

# ============================================================
# 🔍 CONSULTAS AO BANCO
# ============================================================
def buscar_professor(cursor, rfid):
    """Busca professor pelo código RFID. Retorna dict ou None."""
    print(f"🔍 Consultando professor no banco para o RFID: {rfid}")
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
    print(f"🔍 Consultando chave no banco para o RFID: {rfid}")
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

# ============================================================
# 📝 TRANSAÇÕES
# ============================================================
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
        print(f"✅ Devolução registrada no MariaDB: empréstimo {emprestimo_id}")
        return True
    except Error as e:
        print(f"❌ Erro ao registrar devolução: {e}")
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
        print(f"✅ Empréstimo registrado no MariaDB: professor {professor_id} -> chave {chave_id}")
        return "ok"

    except Error as e:
        print(f"❌ Erro ao registrar empréstimo: {e}")
        try:
            conexao.rollback()
        except:
            pass
        return "erro"

# ============================================================
# 🌀 MÁQUINA DE ESTADOS PRINCIPAL
# ============================================================
def loop_principal(leitor, conexao):
    estado = Estado.IDLE

    while True:
        try:
            # ── IDLE: aguarda crachá do professor ────────────────────────
            if estado == Estado.IDLE:
                ctx["professor"] = None
                ctx["emprestimo"] = None

                lcd_texto("SISTEMA CHAVES", "Passe o cracha")
                print("\n" + "="*50)
                print("🏁 ESTADO: IDLE (Aguardando professor)")

                rfid = aguardar_rfid_idle(leitor)

                print("🔗 Validando conexão do banco antes da query...")
                conexao = garantir_conexao(conexao)
                if not conexao:
                    lcd_texto("ERRO BD!", "Reconectando...")
                    time.sleep(3)
                    continue

                # Buffer=True impede o conector python de travar
                cursor = conexao.cursor(buffered=True) 
                professor = buscar_professor(cursor, rfid)

                if not professor:
                    print(f"⚠️ RFID [{rfid}] lido, mas não é um professor cadastrado no Banco.")
                    lcd_texto("Nao reconhecido", "Tente novamente")
                    time.sleep(2)
                    cursor.close()
                    continue 

                ctx["professor"] = professor
                print(f"✅ Professor Encontrado: {professor['nome']}")
                lcd_texto("Bem-vindo!", professor["nome"][:16])
                time.sleep(1.5)
                estado = Estado.PROFESSOR_OK
                cursor.close()

            # ── PROFESSOR_OK: decide o fluxo (Retirada ou Devolução) ──────
            elif estado == Estado.PROFESSOR_OK:
                print("🔄 ESTADO: PROFESSOR_OK (Avaliando pendências...)")
                cursor = conexao.cursor(buffered=True)
                professor = ctx["professor"]
                chave_ativa = professor_tem_chave_ativa(cursor, professor["id"])

                if chave_ativa:
                    emprestimo_id, chave_id, nome_chave = chave_ativa
                    ctx["emprestimo"] = (emprestimo_id, chave_id)

                    print(f"⚠️ Professor já possui uma chave pendente: {nome_chave}")
                    lcd_texto("Devolver:", nome_chave[:16])
                    time.sleep(1.5)
                    estado = Estado.AGUARDANDO_DEVOLUCAO
                else:
                    print("✅ Professor livre. Prosseguindo para pegar nova chave.")
                    lcd_texto("Pegar chave:", "Passe a chave")
                    time.sleep(1.5)
                    estado = Estado.AGUARDANDO_CHAVE
                
                cursor.close()

            # ── AGUARDANDO_DEVOLUCAO ──────────────────────────────────────
            elif estado == Estado.AGUARDANDO_DEVOLUCAO:
                print("🔄 ESTADO: AGUARDANDO_DEVOLUCAO (Esperando chave pendente ser lida)")
                emprestimo_id, chave_id_esperada = ctx["emprestimo"]

                lcd_texto("Passe a chave", "para devolver")
                rfid_chave = ler_rfid_com_timeout(leitor, timeout=20)

                if not rfid_chave:
                    lcd_texto("Timeout!", "Operacao cancelada")
                    time.sleep(2)
                    estado = Estado.IDLE
                    continue

                cursor = conexao.cursor(buffered=True)
                chave = buscar_chave(cursor, rfid_chave)

                if not chave:
                    lcd_texto("RFID invalido!", "Nao e uma chave")
                    time.sleep(2)
                    estado = Estado.IDLE
                    cursor.close()
                    continue

                if chave["id"] != chave_id_esperada:
                    print(f"❌ Chave errada! Esperava ID {chave_id_esperada}, recebeu {chave['id']}")
                    lcd_texto("Chave errada!", "Tente novamente")
                    time.sleep(2)
                    estado = Estado.IDLE
                    cursor.close()
                    continue

                if registrar_devolucao(cursor, conexao, emprestimo_id):
                    lcd_texto("Devolvido!", "Obrigado :)")
                    time.sleep(3)
                else:
                    lcd_texto("ERRO no BD!", "Tente depois")
                    time.sleep(2)

                cursor.close()
                estado = Estado.IDLE

            # ── AGUARDANDO_CHAVE (Empréstimo) ─────────────────────────────
            elif estado == Estado.AGUARDANDO_CHAVE:
                print("🔄 ESTADO: AGUARDANDO_CHAVE (Esperando a chave física a ser retirada ser lida)")
                professor = ctx["professor"]

                lcd_texto("Passe a chave", "para pegar")
                rfid_chave = ler_rfid_com_timeout(leitor, timeout=20)

                if not rfid_chave:
                    lcd_texto("Timeout!", "Operacao cancelada")
                    time.sleep(2)
                    estado = Estado.IDLE
                    continue

                cursor = conexao.cursor(buffered=True)
                chave = buscar_chave(cursor, rfid_chave)

                if not chave:
                    lcd_texto("RFID invalido!", "Nao e uma chave")
                    time.sleep(2)
                    estado = Estado.IDLE
                    cursor.close()
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

                cursor.close()
                estado = Estado.IDLE

        except KeyboardInterrupt:
            raise

        except Exception as e:
            print(f"❌ Erro imprevisto no ciclo: {type(e).__name__} - {e}")
            lcd_texto("ERRO!", str(e)[:16])
            time.sleep(2)
            estado = Estado.IDLE

# ============================================================
# 🚀 MAIN (Inicialização do Sistema)
# ============================================================
def main():
    print("\n🚀 Iniciando Sistema de Controle de Chaves Claviculário...")
    print(f"📅 Data/Hora do Raspberry: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    iniciar_lcd()

    # Inicializar RFID
    try:
        from mfrc522 import SimpleMFRC522
        leitor_rfid = SimpleMFRC522()
        print("✅ Leitor de Sensor MFRC522 inicializado fisicamente.")
    except Exception as e:
        print(f"❌ Erro ao inicializar sensor RFID físico: {e}")
        lcd_texto("ERRO RFID!", "Verifique hw")
        return

    conexao = None

    try:
        print("🔗 Abrindo conexão com o container MariaDB...")
        conexao = conectar_banco()
        lcd_texto("SISTEMA PRONTO", "Aguardando...")
        time.sleep(1)

        loop_principal(leitor_rfid, conexao)

    except KeyboardInterrupt:
        print("\n🛑 Encerrando sistema (Ctrl+C manual)...")
        lcd_texto("Encerrando...", "Aguarde")

    except Error as e:
        print(f"❌ Erro fatal de conexão final: {e}")
        lcd_texto("ERRO BD!", str(e)[:16])

    finally:
        if conexao and conexao.is_connected():
            try:
                conexao.close()
                print("🔌 Conexão com o Banco de Dados fechada com segurança.")
            except:
                pass

        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup()
            print("🧹 Pinos GPIO limpos com sucesso da placa física do Raspberry.")
        except:
            pass

        lcd_texto("SISTEMA", "ENCERRADO")
        print("🏁 Sistema finalizado com segurança.")

if __name__ == "__main__":
    main()
