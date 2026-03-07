import streamlit as st
import pandas as pd
from datetime import datetime
import os
import xml.etree.ElementTree as ET 
import io
import time
from database import init_db, create_task, add_file_to_task, update_task_total_files, get_connection

# Inicializa banco de dados
init_db()

# --- MÓDULO DE EXTRAÇÃO DE XML EM MEMÓRIA ---
def extrair_dados_xml(arquivos_upload, temp_dir):
    """Lê os arquivos XML carregados via Streamlit e extrai os dados, salvando os arquivos no disco temporário."""
    dados_extraidos = []
    os.makedirs(temp_dir, exist_ok=True)
    
    for arquivo_upload in arquivos_upload:
        try:
            conteudo_bytes = arquivo_upload.read()
            arquivo_upload.seek(0)
            
            root = ET.fromstring(conteudo_bytes)
            
            def obter_texto(tag_nome):
                for elem in root.iter():
                    if elem.tag.split('}')[-1] == tag_nome:
                        return elem.text if elem.text else ""
                return ""
            
            nome_arq = arquivo_upload.name
            num_abi = obter_texto("numeroABI")
            if not num_abi: continue 
            
            competencias = []
            for elem in root.iter():
                if elem.tag.split('}')[-1] == "competencia":
                    comp = elem.text
                    if comp and comp not in competencias:
                        competencias.append(comp)
                        if len(competencias) == 3: break
            
            # Salvar no disco temporário para o worker pegar depois
            file_path = os.path.join(temp_dir, f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{nome_arq}")
            with open(file_path, "wb") as f:
                f.write(conteudo_bytes)
                
            dados_extraidos.append({
                "Nome do Arquivo": nome_arq,
                "Número ABI": num_abi,
                "Valor Total do Processo": obter_texto("valorTotalProcesso"),
                "Quantidade de Processo": obter_texto("quantidadeProcesso"),
                "Datas de Competência": ", ".join(competencias),
                "Número do Processo": obter_texto("numeroProcesso"),
                "Data de Registro da Transação": obter_texto("dataRegistroTransacao"),
                "file_path": file_path
            })
        except Exception as e:
            st.error(f"⚠️ Erro ao extrair dados do arquivo {arquivo_upload.name}: {e}")
            
    df_novo = pd.DataFrame(dados_extraidos)
    return df_novo

def show_dashboard():
    st.header("📊 Painel de Acompanhamento")
    conn = get_connection()
    # Pega as últimas 5 tarefas
    c = conn.cursor()
    c.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 5")
    tasks = c.fetchall()
    
    if not tasks:
        st.info("Nenhuma importação iniciada ainda.")
        return
        
    for task in tasks:
        with st.expander(f"Tarefa #{task['id']} - Status: {task['status']} ({task['created_at']})", expanded=(task['status'] in ['PENDENTE', 'EM ANDAMENTO'])):
            col1, col2, col3 = st.columns(3)
            col1.metric("Arquivos Processados", f"{task['arquivos_processados']} / {task['total_arquivos']}")
            col2.metric("Status da Fila", task['status'])
            if task['status'] == 'EM ANDAMENTO':
                progresso = task['arquivos_processados'] / max(1, task['total_arquivos'])
                st.progress(progresso)
            elif task['status'] == 'FALHOU':
                st.error(f"Erro Crítico: {task['error_message']}")
                
            # Mostra logs e arquivos
            tab1, tab2 = st.tabs(["Arquivos (ABIs)", "Logs de Execução"])
            
            with tab1:
                # Carrega arquivos dessa task
                c.execute("SELECT nome_arquivo, numero_abi, status_importacao, data_processamento FROM task_files WHERE task_id = ?", (task['id'],))
                files_data = c.fetchall()
                if files_data:
                    df_files = pd.DataFrame([dict(row) for row in files_data])
                    df_files.rename(columns={
                        'nome_arquivo': 'Arquivo',
                        'numero_abi': 'ABI',
                        'status_importacao': 'Status',
                        'data_processamento': 'Processado em'
                    }, inplace=True)
                    st.dataframe(df_files, use_container_width=True)
                    
                    # Botão para baixar planilha
                    if task['status'] == 'CONCLUIDO' or task['status'] == 'FALHOU':
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df_files.to_excel(writer, index=False)
                        excel_data = output.getvalue()
                        st.download_button(
                            label=f"📥 Baixar Relatório da Tarefa #{task['id']}",
                            data=excel_data,
                            file_name=f"Resultado_Tarefa_{task['id']}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_{task['id']}"
                        )
            
            with tab2:
                c.execute("SELECT timestamp, level, message FROM logs WHERE task_id = ? ORDER BY id DESC LIMIT 50", (task['id'],))
                logs_data = c.fetchall()
                if logs_data:
                    for log in logs_data:
                        icon = "ℹ️"
                        if log['level'] == 'SUCCESS': icon = "✅"
                        elif log['level'] == 'ERROR': icon = "❌"
                        elif log['level'] == 'WARNING': icon = "⚠️"
                        st.text(f"{icon} [{log['timestamp']}] {log['message']}")

def main():
    st.set_page_config(page_title="Robô de Importação XML", page_icon="🤖", layout="wide")
    st.title("🤖 Importador Automático de XML - RSUS")

    # Mudar a pasta temporária para /tmp, que é o RAM disk rápido no Cloud Run
    temp_dir = "/tmp/temp_xml_uploads"

    st.sidebar.header("Configurações do Sistema")
    url_sistema = st.sidebar.text_input("URL do Sistema", value="https://rsuscampinas.cubeti.com.br/importacao/novo")
    usuario = st.sidebar.text_input("Usuário")
    senha = st.sidebar.text_input("Senha", type="password")

    tab_upload, tab_dash = st.tabs(["📤 Nova Importação", "📊 Acompanhamento em Tempo Real"])
    
    with tab_upload:
        st.header("Upload de Arquivos")
        arquivos_xml = st.file_uploader("Selecione os arquivos XML", type=["xml"], accept_multiple_files=True)

        if st.button("Iniciar Importação"):
            if not usuario or not senha:
                st.error("Por favor, preencha o Usuário e a Senha antes de iniciar.")
                return
            
            if not arquivos_xml:
                st.warning("Nenhum arquivo XML selecionado.")
                return

            st.info("Extraindo dados dos arquivos XML e enfileirando tarefa...")
            df = extrair_dados_xml(arquivos_xml, temp_dir)

            if df.empty:
                st.error("❌ Nenhum arquivo XML válido encontrado na seleção.")
                return
            
            # Limpa e ordena ABIs no UI para inserir no BD
            df['Data de Registro da Transação'] = pd.to_datetime(df['Data de Registro da Transação'], errors='coerce')
            df_limpo = df.dropna(subset=['Nome do Arquivo']).copy()
            df_limpo['ABI_NUMERICA'] = df_limpo['Número ABI'].astype(str).str.extract(r'(\d+)').astype(int)
            df_ordenado = df_limpo.sort_values(by='ABI_NUMERICA', ascending=False)
            
            # Cria a tarefa no SQLite
            task_id = create_task(url_sistema, usuario, senha)
            
            for index, linha in df_ordenado.iterrows():
                add_file_to_task(task_id, linha.to_dict())
                
            update_task_total_files(task_id, len(df_ordenado))
            
            st.success(f"✅ Arquivos enfileirados com sucesso! Tarefa #{task_id} criada. O robô irá iniciar o processamento em segundo plano.")
            st.info("Vá para a aba 'Acompanhamento em Tempo Real' para ver o progresso (atualizado a cada 5 segundos).")
            
    with tab_dash:
        show_dashboard()
        # Recarregar interface de tempos em tempos para atualizar logs
        time.sleep(5)
        st.rerun()

if __name__ == "__main__":
    main()
