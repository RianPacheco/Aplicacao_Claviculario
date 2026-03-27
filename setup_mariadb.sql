-- ============================================================
-- SISTEMA DE CONTROLE DE CHAVES - CEAP
-- Script SQL Simplificado
-- Apenas os campos necessários
-- ============================================================

-- 1️⃣ CRIAR BANCO DE DADOS
-- ============================================================

CREATE DATABASE IF NOT EXISTS chaves_professores
CHARACTER SET utf8mb4 
COLLATE utf8mb4_unicode_ci;

USE chaves_professores;

-- ============================================================
-- 2️⃣ TABELA: PROFESSORES
-- Campos: Id, Nome, Codigo (RFID)
-- ============================================================

CREATE TABLE IF NOT EXISTS professores (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome VARCHAR(150) NOT NULL,
    codigo VARCHAR(50) UNIQUE NOT NULL,
    
    INDEX idx_codigo (codigo)
) ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4 
COLLATE utf8mb4_unicode_ci;

-- ============================================================
-- 3️⃣ TABELA: CHAVES
-- Campos: Id, Nome_da_chave, Codigo (RFID)
-- ============================================================

CREATE TABLE IF NOT EXISTS chaves (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nome_da_chave VARCHAR(100) NOT NULL,
    codigo VARCHAR(50) UNIQUE NOT NULL,
    
    INDEX idx_codigo (codigo)
) ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4 
COLLATE utf8mb4_unicode_ci;

-- ============================================================
-- 4️⃣ TABELA: PROFESSOR_CHAVES
-- Campos: Id, Professor_Id, Chave_Id, Data_Emprestimo, Data_Devolucao
-- ============================================================

CREATE TABLE IF NOT EXISTS professor_chaves (
    id INT AUTO_INCREMENT PRIMARY KEY,
    professor_id INT NOT NULL,
    chave_id INT NOT NULL,
    data_emprestimo TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_devolucao TIMESTAMP NULL,
    
    FOREIGN KEY (professor_id) REFERENCES professores(id) ON DELETE CASCADE,
    FOREIGN KEY (chave_id) REFERENCES chaves(id) ON DELETE CASCADE,
    
    INDEX idx_professor (professor_id),
    INDEX idx_chave (chave_id),
    INDEX idx_data_emprestimo (data_emprestimo),
    INDEX idx_data_devolucao (data_devolucao)
) ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4 
COLLATE utf8mb4_unicode_ci;

-- ============================================================
-- 5️⃣ INSERIR PROFESSORES (37 total)
-- Códigos RFID sem vírgula
-- ============================================================

INSERT INTO professores (nome, codigo) VALUES
('ADRIANO COTA', '01937042'),
('ALEF JESUS', '11200065'),
('ALLAN ARAÚJO', '22037305'),
('AUGUSTO NUNES', '01951007'),
('CARLOS ALBERTO', '01931185'),
('CESAR CONCEIÇÃO', '07603765'),
('DANILLO FEITOSA', '11928868'),
('DIEGO BORGES', '05137868'),
('EVERTON FRANCO', '01832174'),
('FÁBIO SANTOS', '05156204'),
('FERNANDO NITZSCHE', '01833422'),
('FERNANDO SALLES', '01903597'),
('GILSON EDUARDO', '01937461'),
('GUSTAVO SOUSA', '04935995'),
('GUILHERME BARBOSA', '05143991'),
('HARRISON PARIZOTO', '05152158'),
('HUGO PEREIRA', '01841943'),
('JOSÉ ROBERTO', '05123551'),
('LEONARDO MONTEIRO', '01855642'),
('LUCAS MOTA', '01864269'),
('LUCAS LUCENA', '01909436'),
('LUCCA BORRO', '07550416'),
('MARCELO HENRIQUE', '01949216'),
('MATHEUS BARRETO', '15307617'),
('PABLO SANTOS', '05110876'),
('PAULO HENRIQUE', '08427922'),
('REGYS ALVES', '08406121'),
('REINALDO SANTOS', '01948355'),
('RIAN AMORIM', '07516866'),
('RIAN PACHECO', '07460472'),
('RICARDO SHIGUEMITI', '01838083'),
('RODRIGO MOURA', '11931738'),
('RONALDO CESAR', '01834798'),
('RAFAEL SASAKI', '01840842'),
('SUNAO KOBAYASHI', '01831991'),
('THIAGO GOMES', '01907355'),
('VINÍCIUS MATOS', '01951509');

-- ============================================================
-- 6️⃣ CRIAR USUÁRIO DE APLICAÇÃO
-- ============================================================

DROP USER IF EXISTS 'app_chaves'@'localhost';

CREATE USER 'app_chaves'@'localhost' IDENTIFIED BY 'chaves123';

GRANT SELECT, INSERT, UPDATE, DELETE 
ON chaves_professores.* 
TO 'app_chaves'@'localhost';

FLUSH PRIVILEGES;

-- ============================================================
-- 7️⃣ VIEWS ÚTEIS
-- ============================================================

-- View: Empréstimos Ativos
CREATE OR REPLACE VIEW v_emprestimos_ativos AS
SELECT 
    pc.id,
    p.id as professor_id,
    p.nome as professor,
    c.id as chave_id,
    c.nome_da_chave,
    pc.data_emprestimo
FROM professor_chaves pc
JOIN professores p ON p.id = pc.professor_id
JOIN chaves c ON c.id = pc.chave_id
WHERE pc.data_devolucao IS NULL
ORDER BY pc.data_emprestimo DESC;

-- View: Histórico de Empréstimos
CREATE OR REPLACE VIEW v_historico_emprestimos AS
SELECT 
    pc.id,
    p.nome as professor,
    c.nome_da_chave as chave,
    pc.data_emprestimo,
    pc.data_devolucao
FROM professor_chaves pc
JOIN professores p ON p.id = pc.professor_id
JOIN chaves c ON c.id = pc.chave_id
ORDER BY pc.data_emprestimo DESC;

-- View: Chaves Disponíveis
CREATE OR REPLACE VIEW v_chaves_disponiveis AS
SELECT 
    c.id,
    c.nome_da_chave,
    c.codigo,
    CASE 
        WHEN pc.id IS NULL THEN 'Disponível'
        ELSE 'Em uso'
    END as status,
    p.nome as professor_atual
FROM chaves c
LEFT JOIN professor_chaves pc ON pc.chave_id = c.id AND pc.data_devolucao IS NULL
LEFT JOIN professores p ON p.id = pc.professor_id;

-- ============================================================
-- 8️⃣ VERIFICAÇÃO FINAL
-- ============================================================

SELECT '✅ Banco criado com sucesso!' as status;
SELECT COUNT(*) as total_professores FROM professores;
SELECT COUNT(*) as total_chaves FROM chaves;

-- ============================================================
-- PRÓXIMAS AÇÕES
-- ============================================================

-- 1. Adicionar chaves com seus códigos RFID:
--    INSERT INTO chaves (nome_da_chave, codigo) VALUES ('Sala 101', 'CODIGO_AQUI');

-- 2. Testar empréstimo:
--    INSERT INTO professor_chaves (professor_id, chave_id) VALUES (1, 1);

-- 3. Registrar devolução:
--    UPDATE professor_chaves SET data_devolucao = NOW() WHERE id = 1;

-- 4. Ver empréstimos ativos:
--    SELECT * FROM v_emprestimos_ativos;
