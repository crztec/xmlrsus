import time
import os
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from database import get_connection, get_pending_task, add_log

def formatar_valor_monetario(valor):
    if pd.isna(valor) or str(valor).strip() == "": return ""
    try:
        if isinstance(valor, (float, int)): 
            return "{:.2f}".format(valor).replace('.', ',')
        s = str(valor).strip()
        if '.' in s and ',' not in s: val_float = float(s)
        elif ',' in s:
            s = s.replace('.', '').replace(',', '.')
            val_float = float(s)
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
        print(f"Erro ao preencher campo {id_campo}: {e}")

def preencher_campo_seguro(wait, id_campo, valor):
    elemento = wait.until(EC.element_to_be_clickable((By.ID, id_campo)))
    elemento.click()
    elemento.clear()
    time.sleep(0.3)
    elemento.send_keys(str(valor))

def process_task(task):
    task_id = task['id']
    url_sistema = task['url_sistema']
    usuario = task['usuario']
    senha = task['senha']
    
    add_log(task_id, "INFO", "Iniciando processamento da tarefa")
    
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM task_files WHERE task_id = ?", (task_id,))
    files = [dict(row) for row in c.fetchall()]
    conn.close()
    
    # Sort files numerically by ABI just like before
    def extract_abi_num(num_abi_str):
        import re
        match = re.search(r'(\d+)', str(num_abi_str))
        return int(match.group(1)) if match else 0
        
    files.sort(key=lambda x: extract_abi_num(x['numero_abi']), reverse=True)
    total_arquivos = len(files)
    
    options = ChromeOptions()
    options.binary_location = '/usr/bin/chromium'
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--proxy-server='direct://'")
    options.add_argument("--proxy-bypass-list=*")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")
    options.add_argument("--disable-translate")
    options.add_argument("--metrics-recording-only")
    options.add_argument("--safebrowsing-disable-auto-update")
    
    servico = Service('/usr/bin/chromedriver')
    navegador = None
    
    try:
        navegador = webdriver.Chrome(service=servico, options=options)
        wait = WebDriverWait(navegador, 30)
        
        add_log(task_id, "INFO", f"Efetuando login no sistema: {url_sistema} ...")
        navegador.get(url_sistema)
        navegador.maximize_window()
        
        wait.until(EC.presence_of_element_located((By.ID, "email"))).send_keys(usuario)
        navegador.find_element(By.ID, "password").send_keys(senha)
        navegador.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        wait.until(EC.presence_of_element_located((By.ID, "numeroProtocolo")))
        
        add_log(task_id, "SUCCESS", "Login efetuado com sucesso!")
        
        concluidos = 0
        
        for file_info in files:
            start_time = time.time()
            file_id = file_info['id']
            concluidos += 1
            nome_xml = file_info['nome_arquivo']
            num_abi = file_info['numero_abi']
            caminho_xml_temp = file_info['file_path']
            
            add_log(task_id, "INFO", f"Processando ({concluidos}/{total_arquivos}): Iniciando ABI {num_abi} (Arquivo: {nome_xml})")
            
            status_imp = "Erro Desconhecido"
            
            try:
                preencher_campo_seguro(wait, "numeroProtocolo", file_info['numero_processo'])
                
                dt_oficio_str = file_info['data_registro_transacao']
                # Tenta parsear a data
                dt_oficio = None
                try:
                    dt_oficio = pd.to_datetime(dt_oficio_str)
                except: pass
                
                if dt_oficio and pd.notna(dt_oficio): 
                    data_receb = dt_oficio.strftime("%d/%m/%Y")
                    prazo_ans = (dt_oficio + timedelta(days=30)).strftime("%d/%m/%Y")
                    preencher_campo_angular(navegador, wait, "dataRecebimentoOficio", data_receb)
                    preencher_campo_angular(navegador, wait, "dataPrazoRespostaAns", prazo_ans)

                val_comp = formatar_competencia_site(file_info['competencias'])
                preencher_campo_angular(navegador, wait, "competencias", val_comp)
                
                preencher_campo_seguro(wait, "quantidadeAtendimentos", file_info['quantidade_processo'])
                
                valor_final = formatar_valor_monetario(file_info['valor_total_processo'])
                preencher_campo_seguro(wait, "valorTotalABI", valor_final)

                if not os.path.exists(caminho_xml_temp):
                    raise Exception(f"Arquivo temporário ausente: {caminho_xml_temp}")

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
                        add_log(task_id, "WARNING", f"Erro SIS00017 detectado. Verificando o anexo {nome_xml}...")
                        codigo_fonte = navegador.page_source.lower()
                        input_file = navegador.find_element(By.XPATH, "//input[@type='file']")
                        valor_interno_botao = str(input_file.get_attribute("value")).lower()
                        
                        if nome_xml.lower() in codigo_fonte or nome_xml.lower() in valor_interno_botao:
                            add_log(task_id, "INFO", "Arquivo detectado. Re-tentando importação...")
                            continue
                        else:
                            add_log(task_id, "ERROR", f"O arquivo {nome_xml} sumiu do campo de upload! Pulando para o próximo.")
                            break
                    else: 
                        sucesso_importacao = True
                        break 
                
                if sucesso_importacao:
                    status_imp = "Sucesso"
                    elapsed = round(time.time() - start_time, 2)
                    add_log(task_id, "SUCCESS", f"ABI {num_abi} finalizada com Sucesso! (Tempo: {elapsed}s)")
                else:
                    status_imp = "Erro: Arquivo sumiu"
                    
            except Exception as e:
                status_imp = f"Erro: {str(e)[:50]}"
                add_log(task_id, "ERROR", f"Erro ao processar ABI {num_abi}: {e}")
            
            # Atualiza status na tabela de arquivos
            conn = get_connection()
            conn.execute("UPDATE task_files SET status_importacao = ?, data_processamento = ? WHERE id = ?", 
                         (status_imp, datetime.now().strftime("%d/%m/%Y %H:%M"), file_id))
            conn.execute("UPDATE tasks SET arquivos_processados = ? WHERE id = ?", (concluidos, task_id))
            conn.commit()
            conn.close()
            
            # Cleanup do arquivo físico
            try:
                os.remove(caminho_xml_temp)
            except: pass
            
            time.sleep(5)
            
            # Retornar a tela se não for o último
            if concluidos < total_arquivos:
                try:
                    btn_ret = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(normalize-space(.), 'Selecionar arquivo')]")))
                    navegador.execute_script("arguments[0].click();", btn_ret)
                    wait.until(EC.presence_of_element_located((By.ID, "numeroProtocolo")))
                    
                    add_log(task_id, "INFO", "Aguardando 120 segundos para evitar sobrecarga no sistema...")
                    time.sleep(120) 
                except Exception as e_retorno:
                    add_log(task_id, "ERROR", f"Erro ao retornar para a tela inicial: {e_retorno}. Tentando recarregar a página...")
                    navegador.get(url_sistema)
                    wait.until(EC.presence_of_element_located((By.ID, "numeroProtocolo")))

        # Fim de todas as ABIs
        conn = get_connection()
        conn.execute("UPDATE tasks SET status = 'CONCLUIDO', updated_at = ? WHERE id = ?", 
                     (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task_id))
        conn.commit()
        conn.close()
        add_log(task_id, "SUCCESS", "Todas as ABIs foram processadas!")

    except Exception as e:
        add_log(task_id, "ERROR", f"Erro crítico no robô: {e}")
        conn = get_connection()
        conn.execute("UPDATE tasks SET status = 'FALHOU', updated_at = ?, error_message = ? WHERE id = ?", 
                     (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(e), task_id))
        conn.commit()
        conn.close()
    finally:
        if navegador: navegador.quit()

def main():
    print("Iniciando background worker...")
    from database import init_db
    init_db()
    while True:
        task = get_pending_task()
        if task:
            try:
                process_task(task)
            except Exception as e:
                print(f"Erro fatal ao processar a tarefa {task['id']}: {e}")
                # Fallback error status
                conn = get_connection()
                conn.execute("UPDATE tasks SET status = 'FALHOU', error_message = ? WHERE id = ?", (str(e), task['id']))
                conn.commit()
                conn.close()
        time.sleep(5) # Poll a cada 5 segundos

if __name__ == "__main__":
    main()
