import streamlit as st
import pandas as pd
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime, timedelta
import time
import os
import xml.etree.ElementTree as ET 
import io

# --- FUNÇÕES DE APOIO ---
def formatar_valor_monetario(valor):
    """Identifica se o valor veio com ponto (XML) ou vírgula (Excel) e formata corretamente"""
    if pd.isna(valor) or str(valor).strip() == "": return ""
    try:
        # Se o Pandas já ler como número
        if isinstance(valor, (float, int)): 
            return "{:.2f}".format(valor).replace('.', ',')
        
        s = str(valor).strip()
        
        # Se for padrão XML/Americano (ex: 1511763.69)
        if '.' in s and ',' not in s:
            val_float = float(s)
        # Se for padrão Brasileiro (ex: 1.511.763,69 ou 1308944,2)
        elif ',' in s:
            s = s.replace('.', '') 
            s = s.replace(',', '.') 
            val_float = float(s)
        # Se for um número inteiro em formato de texto
        else:
            val_float = float(s)
            
        return "{:.2f}".format(val_float).replace('.', ',')
    except: 
        return str(valor)

def formatar_competencia_site(texto_excel):
    if pd.isna(texto_excel) or str(texto_excel).strip() == "" or str(texto_excel).lower() == 'nat': return ""
    try:
        itens = [i.strip() for i in str(texto_excel).split(',')]
        datas = [datetime.strptime(i, "%m%Y") for i in itens if len(i) == 6]
        datas.sort()
        if not datas: return str(texto_excel)
        meses = [str(d.month) for d in datas]
        ano = datas[0].year
        return f"{'-'.join(meses)}/{ano}"
    except: return str(texto_excel)

def preencher_campo_angular(navegador, wait, id_campo, valor_str):
    try:
        wait.until(EC.presence_of_element_located((By.ID, id_campo)))
        script_js = f"""
        var input = document.getElementById('{id_campo}');
        input.value = '{valor_str}';
        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
        input.dispatchEvent(new Event('blur', {{ bubbles: true }}));
        """
        navegador.execute_script(script_js)
    except Exception as e: 
        st.error(f"Erro ao preencher campo {id_campo}: {e}")

def preencher_campo_seguro(wait, id_campo, valor):
    elemento = wait.until(EC.element_to_be_clickable((By.ID, id_campo)))
    elemento.click()
    elemento.clear()
    time.sleep(0.3)
    elemento.send_keys(str(valor))

# --- MÓDULO DE EXTRAÇÃO DE XML EM MEMÓRIA ---
def extrair_dados_xml(arquivos_upload):
    """Lê os arquivos XML carregados via Streamlit (em memória) e extrai os dados."""
    dados_extraidos = []
    
    for arquivo_upload in arquivos_upload:
        try:
            # Ler o conteúdo do UploadedFile em memória
            conteudo_bytes = arquivo_upload.read()
            # Reiniciar o ponteiro do arquivo para que ele possa ser lido novamente depois
            arquivo_upload.seek(0)
            
            # Fazer parse usando fromstring em vez de ler arquivo físico
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
            
            dados_extraidos.append({
                "Nome do Arquivo": nome_arq,
                "Número ABI": num_abi,
                "Valor Total do Processo": obter_texto("valorTotalProcesso"),
                "Quantidade de Processo": obter_texto("quantidadeProcesso"),
                "Datas de Competência": ", ".join(competencias),
                "Número do Processo": obter_texto("numeroProcesso"),
                "Data de Registro da Transação": obter_texto("dataRegistroTransacao"),
                "Status Importação": "Pendente",
                "Data Processamento": ""
            })
        except Exception as e:
            st.error(f"⚠️ Erro ao extrair dados do arquivo {arquivo_upload.name}: {e}")
            
    df_novo = pd.DataFrame(dados_extraidos)
    return df_novo

def main():
    st.set_page_config(page_title="Robô de Importação XML", page_icon="🤖", layout="wide")
    st.title("🤖 Importador Automático de XML - RSUS")

    st.sidebar.header("Configurações do Sistema")
    url_sistema = st.sidebar.text_input("URL do Sistema", value="https://rsuscampinas.cubeti.com.br/importacao/novo")
    usuario = st.sidebar.text_input("Usuário")
    senha = st.sidebar.text_input("Senha", type="password")

    st.header("Upload de Arquivos")
    arquivos_xml = st.file_uploader("Selecione os arquivos XML", type=["xml"], accept_multiple_files=True)

    if st.button("Iniciar Importação"):
        if not usuario or not senha:
            st.error("Por favor, preencha o Usuário e a Senha antes de iniciar.")
            return
        
        if not arquivos_xml:
            st.warning("Nenhum arquivo XML selecionado.")
            return

        st.info("Extraindo dados dos arquivos XML...")
        df = extrair_dados_xml(arquivos_xml)

        if df.empty:
            st.error("❌ Nenhum arquivo XML válido encontrado na seleção.")
            return
            
        df['Data de Registro da Transação'] = pd.to_datetime(df['Data de Registro da Transação'], errors='coerce')
        df_limpo = df.dropna(subset=['Nome do Arquivo']).copy()
        df_limpo['ABI_NUMERICA'] = df_limpo['Número ABI'].astype(str).str.extract(r'(\d+)').astype(int)
        df_ordenado = df_limpo.sort_values(by='ABI_NUMERICA', ascending=False)
        
        # Mapear os objetos UploadedFile por nome para acesso posterior
        arquivos_dict = {f.name: f for f in arquivos_xml}

        # Cria a barra de progresso e a área de log
        total_arquivos = len(df_ordenado)
        progress_bar = st.progress(0)
        status_text = st.empty()
        log_container = st.container()

        # Configurar Selenium Headless
        options = FirefoxOptions()
        options.add_argument("--headless")
        options.add_argument("--width=1920")
        options.add_argument("--height=1080")
        
        # O Cloud Run tem permissões restritas em algumas pastas, usar /tmp para o cache do Firefox ajuda a prevenir crashes
        options.set_preference("browser.cache.disk.dir", "/tmp")
        options.set_preference("browser.cache.offline.dir", "/tmp")
        options.set_preference("dom.ipc.processCount", 1)  # Restringe Firefox a um único processo para poupar memória
        options.set_preference("network.http.phishy-userpass-length", 255)
        options.set_preference("network.proxy.type", 0)
        options.set_preference("network.dns.disableIPv6", True)
        
        servico = Service(GeckoDriverManager().install(), log_path=os.devnull)
        
        status_text.text("Iniciando o navegador em segundo plano...")
        navegador = None
        # Mudar a pasta temporária para /tmp, que é o RAM disk rápido no Cloud Run
        temp_dir = "/tmp/temp_xml_uploads"
        
        try:
            navegador = webdriver.Firefox(service=servico, options=options)
            wait = WebDriverWait(navegador, 30)
            
            status_text.text(f"Efetuando login no sistema: {url_sistema} ...")
            navegador.get(url_sistema)
            navegador.maximize_window()
            
            wait.until(EC.presence_of_element_located((By.ID, "email"))).send_keys(usuario)
            navegador.find_element(By.ID, "password").send_keys(senha)
            navegador.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
            wait.until(EC.presence_of_element_located((By.ID, "numeroProtocolo")))
            
            log_container.success("Login efetuado com sucesso!")
            
            concluidos = 0
            # Diretório temporário para salvar os XMLs para o Selenium
            os.makedirs(temp_dir, exist_ok=True)
            
            for index, linha in df_ordenado.iterrows():
                start_time = time.time()
                concluidos += 1
                progress = concluidos / total_arquivos
                progress_bar.progress(progress)
                status_text.text(f"Processando: {concluidos}/{total_arquivos} | ABI {linha['Número ABI']}")
                
                log_container.info(f"Iniciando ABI {linha['Número ABI']} (Arquivo: {linha['Nome do Arquivo']})")
                
                try:
                    preencher_campo_seguro(wait, "numeroProtocolo", linha['Número do Processo'])
                    
                    dt_oficio = linha['Data de Registro da Transação']
                    if pd.notna(dt_oficio) and isinstance(dt_oficio, datetime): 
                        data_receb = dt_oficio.strftime("%d/%m/%Y")
                        prazo_ans = (dt_oficio + timedelta(days=30)).strftime("%d/%m/%Y")
                        preencher_campo_angular(navegador, wait, "dataRecebimentoOficio", data_receb)
                        preencher_campo_angular(navegador, wait, "dataPrazoRespostaAns", prazo_ans)

                    val_comp = formatar_competencia_site(linha['Datas de Competência'])
                    preencher_campo_angular(navegador, wait, "competencias", val_comp)
                    
                    preencher_campo_seguro(wait, "quantidadeAtendimentos", linha['Quantidade de Processo'])
                    
                    valor_final = formatar_valor_monetario(linha['Valor Total do Processo'])
                    preencher_campo_seguro(wait, "valorTotalABI", valor_final)

                    nome_xml = str(linha['Nome do Arquivo']).strip()
                    
                    # Salva arquivo temporariamente para o Selenium fazer upload
                    caminho_xml_temp = os.path.join(temp_dir, nome_xml)
                    if nome_xml in arquivos_dict:
                        arquivo_upload = arquivos_dict[nome_xml]
                        arquivo_upload.seek(0)
                        with open(caminho_xml_temp, "wb") as f:
                            f.write(arquivo_upload.read())
                    else:
                        raise Exception("Arquivo XML não encontrado na memória.")

                    # Fazer Upload
                    wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))).send_keys(os.path.abspath(caminho_xml_temp))
                    time.sleep(3) 
                    
                    sucesso_importacao = False
                    for tentativa in range(3):
                        btn_imp = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(normalize-space(.), 'Importar arquivo')]")))
                        navegador.execute_script("arguments[0].click();", btn_imp)
                        time.sleep(2)

                        avisos = navegador.find_elements(By.XPATH, "//*[contains(text(), 'SIS00017')]")
                        if avisos:
                            log_container.warning(f"⚠️ Erro SIS00017 detectado. Verificando o anexo {nome_xml}...")
                            codigo_fonte = navegador.page_source.lower()
                            input_file = navegador.find_element(By.XPATH, "//input[@type='file']")
                            valor_interno_botao = str(input_file.get_attribute("value")).lower()
                            
                            if nome_xml.lower() in codigo_fonte or nome_xml.lower() in valor_interno_botao:
                                log_container.info("🔄 Arquivo detectado. Re-tentando importação...")
                                continue
                            else:
                                log_container.error(f"❌ O arquivo {nome_xml} sumiu do campo de upload! Pulando para o próximo.")
                                # Marcar como Erro e quebrar o loop de tentativas
                                break
                        else: 
                            sucesso_importacao = True
                            break 
                    
                    if sucesso_importacao:
                        df_ordenado.at[index, 'Status Importação'] = "Sucesso"
                        df_ordenado.at[index, 'Data Processamento'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                        elapsed = round(time.time() - start_time, 2)
                        log_container.success(f"✅ ABI {linha['Número ABI']} finalizada com Sucesso! (Tempo: {elapsed}s)")
                    else:
                        df_ordenado.at[index, 'Status Importação'] = "Erro: Arquivo sumiu"
                        df_ordenado.at[index, 'Data Processamento'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                        
                except Exception as iter_e:
                    log_container.error(f"❌ Erro ao processar ABI {linha['Número ABI']}: {iter_e}")
                    df_ordenado.at[index, 'Status Importação'] = f"Erro: {str(iter_e)[:50]}"
                    df_ordenado.at[index, 'Data Processamento'] = datetime.now().strftime("%d/%m/%Y %H:%M")
                
                # Cleanup do arquivo temporário
                if 'caminho_xml_temp' in locals() and os.path.exists(caminho_xml_temp):
                    try:
                        os.remove(caminho_xml_temp)
                    except:
                        pass
                
                time.sleep(5)
                
                # Retornar a tela para a próxima ABI
                if concluidos < total_arquivos:
                    try:
                        btn_ret = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(normalize-space(.), 'Selecionar arquivo')]")))
                        navegador.execute_script("arguments[0].click();", btn_ret)
                        wait.until(EC.presence_of_element_located((By.ID, "numeroProtocolo")))
                        
                        log_container.info("⏳ Aguardando 120 segundos para evitar sobrecarga no sistema...")
                        time.sleep(120) 
                    except Exception as e_retorno:
                        log_container.error(f"Erro ao retornar para a tela inicial: {e_retorno}. Tentando recarregar a página...")
                        navegador.get(url_sistema)
                        wait.until(EC.presence_of_element_located((By.ID, "numeroProtocolo")))

            status_text.text("🚀 Todas as ABIs foram processadas!")
            st.balloons()
            
            # Preparar o Excel final na sessão do Streamlit
            st.session_state['df_resultado'] = df_ordenado
            
        except Exception as e:
            st.error(f"❌ Erro crítico no robô: {e}")
        finally:
            if navegador:
                navegador.quit()
                
            # Limpeza extra da pasta temp
            if os.path.exists(temp_dir):
                for f in os.listdir(temp_dir):
                    try:
                        os.remove(os.path.join(temp_dir, f))
                    except:
                        pass
                try:
                    os.rmdir(temp_dir)
                except:
                    pass

    # Exibe botão de download se o processamento terminou e salvou algo na sessão
    if 'df_resultado' in st.session_state:
        st.subheader("🎉 Processamento Concluído!")
        st.dataframe(st.session_state['df_resultado'][['Nome do Arquivo', 'Número ABI', 'Status Importação', 'Data Processamento']])
        
        # Gera o Excel em memória para download
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            st.session_state['df_resultado'].to_excel(writer, index=False)
        excel_data = output.getvalue()
        
        st.download_button(
            label="📥 Baixar Planilha de Resultados",
            data=excel_data,
            file_name=f"Resultado_Importacao_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

if __name__ == "__main__":
    main()
