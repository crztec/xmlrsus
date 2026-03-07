import sqlite3
import json
import os
from datetime import datetime

DB_PATH = "/tmp/rsus_tasks.db"

def get_connection():
    # SQLite in /tmp/ is fast and isolated in Cloud Run RAM disk
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    # Tabela principal de tarefas (Jobs)
    c.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT DEFAULT 'PENDENTE',
            created_at TEXT,
            updated_at TEXT,
            url_sistema TEXT,
            usuario TEXT,
            senha TEXT,
            total_arquivos INTEGER DEFAULT 0,
            arquivos_processados INTEGER DEFAULT 0,
            error_message TEXT
        )
    ''')
    # Tabela de arquivos (ABIs) dentro de cada tarefa
    c.execute('''
        CREATE TABLE IF NOT EXISTS task_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            nome_arquivo TEXT,
            numero_abi TEXT,
            numero_processo TEXT,
            data_registro_transacao TEXT,
            competencias TEXT,
            quantidade_processo TEXT,
            valor_total_processo TEXT,
            status_importacao TEXT DEFAULT 'Pendente',
            data_processamento TEXT,
            error_message TEXT,
            file_path TEXT,
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        )
    ''')
    # Tabela para logs da execução
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            timestamp TEXT,
            level TEXT,
            message TEXT,
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        )
    ''')
    conn.commit()
    conn.close()

def create_task(url_sistema, usuario, senha):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO tasks (status, created_at, updated_at, url_sistema, usuario, senha) VALUES (?, ?, ?, ?, ?, ?)",
        ("PENDENTE", now, now, url_sistema, usuario, senha)
    )
    task_id = c.lastrowid
    conn.commit()
    conn.close()
    return task_id

def add_file_to_task(task_id, file_info):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO task_files (
            task_id, nome_arquivo, numero_abi, numero_processo, data_registro_transacao,
            competencias, quantidade_processo, valor_total_processo, status_importacao, file_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        task_id,
        file_info['Nome do Arquivo'],
        file_info['Número ABI'],
        file_info['Número do Processo'],
        file_info['Data de Registro da Transação'],
        file_info['Datas de Competência'],
        file_info['Quantidade de Processo'],
        file_info['Valor Total do Processo'],
        'Pendente',
        file_info['file_path']
    ))
    conn.commit()
    conn.close()

def update_task_total_files(task_id, total):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE tasks SET total_arquivos = ? WHERE id = ?", (total, task_id))
    conn.commit()
    conn.close()

def add_log(task_id, level, message):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO logs (task_id, timestamp, level, message) VALUES (?, ?, ?, ?)", (task_id, now, level, message))
    conn.commit()
    conn.close()

def get_pending_task():
    conn = get_connection()
    c = conn.cursor()
    # Tenta pegar a primeira tarefa pendente e marcá-la como EM ANDAMENTO
    c.execute("BEGIN IMMEDIATE TRANSACTION")
    c.execute("SELECT id, url_sistema, usuario, senha, total_arquivos FROM tasks WHERE status = 'PENDENTE' ORDER BY created_at ASC LIMIT 1")
    task = c.fetchone()
    if task:
        c.execute("UPDATE tasks SET status = 'EM ANDAMENTO', updated_at = ? WHERE id = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task['id']))
    conn.commit()
    conn.close()
    return dict(task) if task else None

