import re
import pandas as pd
import streamlit as st
from google.oauth2 import service_account
import gspread

st.set_page_config(page_title="Ordens de Serviço - WhatsApp", layout="wide")

st.title("📲 Ordens de Serviço (WhatsApp)")
st.markdown("Consulte as ordens salvas ou envie um novo arquivo `chat.txt` para atualizar a planilha do Google.")

# Função de autenticação direta via Google Service Account
def conectar_google_sheets():
    try:
        conf = dict(st.secrets["connections"]["gsheets"])
        
        # Trata e reconstrói a chave privada para o formato PEM válido
        pk = conf["private_key"]
        pk = pk.replace("\\n", "\n")
        
        if "-----BEGIN PRIVATE KEY-----" in pk:
            corpo = pk.split("-----BEGIN PRIVATE KEY-----")[-1].split("-----END PRIVATE KEY-----")[0]
            corpo_limpo = "\n".join([linha.strip() for linha in corpo.split() if linha.strip()])
            pk_formatada = f"-----BEGIN PRIVATE KEY-----\n{corpo_limpo}\n-----END PRIVATE KEY-----\n"
        else:
            pk_formatada = pk

        creds_dict = {
            "type": conf.get("type", "service_account"),
            "project_id": conf.get("project_id"),
            "private_key_id": conf.get("private_key_id"),
            "private_key": pk_formatada,
            "client_email": conf.get("client_email"),
            "client_id": conf.get("client_id"),
            "auth_uri": conf.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
            "token_uri": conf.get("token_uri", "https://oauth2.googleapis.com/token"),
            "auth_provider_x509_cert_url": conf.get("auth_provider_x509_cert_url"),
            "client_x509_cert_url": conf.get("client_x509_cert_url")
        }
        
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        credentials = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(credentials)
        sheet = client.open_by_url(conf["spreadsheet"]).sheet1
        return sheet
    except Exception as e:
        st.error(f"Erro ao conectar com Google Sheets: {e}")
        return None

sheet_obj = conectar_google_sheets()

def carregar_dados_planilha():
    if sheet_obj is None:
        return pd.DataFrame()
    try:
        dados = sheet_obj.get_all_records()
        return pd.DataFrame(dados)
    except Exception:
        return pd.DataFrame()

st.sidebar.title("📁 Importar Chat")
uploaded_chat = st.sidebar.file_uploader("Selecione o ficheiro chat.txt", type=["txt"])

def extrair_dados_whatsapp(texto_completo):
    blocos = re.split(r"(?=ORDEM\s+(?:DE\s+)?SERVIÇO)", texto_completo, flags=re.IGNORECASE)
    registos = []
    
    for bloco in blocos:
        bloco_upper = bloco.upper()
        if "ORDEM" not in bloco_upper or "SERVIÇO" not in bloco_upper:
            continue
            
        def buscar_campo(padrao, padrao_padrao="N/I"):
            match = re.search(padrao, bloco, re.IGNORECASE)
            return match.group(1).strip() if match and match.group(1).strip() else padrao_padrao

        if "ADM" in bloco_upper:
            categoria = "OS ADM"
        elif "ZML" in bloco_upper:
            categoria = "OS ZML"
        else:
            categoria = "OS Geral"

        cidade_raw = buscar_campo(r"CIDADE\s*:\s*([^\n\r]+)")
        cidade_limpa = re.sub(r"(?i)^CIDADE\s*:\s*", "", cidade_raw).strip()

        data_str = buscar_campo(r"DATA\s*:\s*([^\n\r]+)")
        motorista = buscar_campo(r"MOTORISTA\s*:\s*([^\n\r]+)")
        executor = buscar_campo(r"(?:EXECUTOR|EXECUTORES|PASSAGEIROS)\s*:\s*([^\n\r]+)")
        veiculo = buscar_campo(r"VEÍCULO\s*:\s*([^\n\r]+)")
        
        saida_base = buscar_campo(r"SAÍDA DA BASE\s*:\s*([^\n\r]+)")
        chegada_srv = buscar_campo(r"CHEGADA SERVIÇO\s*:\s*([^\n\r]+)")
        saida_srv = buscar_campo(r"SAÍDA SERVIÇO\s*:\s*([^\n\r]+)")
        chegada_base = buscar_campo(r"CHEGADA BASE\s*:\s*([^\n\r]+)")

        registos.append({
            "Data": data_str,
            "Categoria": categoria,
            "Cidade / Município": cidade_limpa.upper() if cidade_limpa != "N/I" else "N/I",
            "Motorista": motorista,
            "Executor / Passageiros": executor,
            "Saída Base": saida_base,
            "Chegada Serviço": chegada_srv,
            "Saída Serviço": saida_srv,
            "Chegada Base": chegada_base,
            "Veículo": veiculo
        })

    return pd.DataFrame(registos)

if uploaded_chat is not None:
    conteudo_texto = uploaded_chat.read().decode("utf-8")
    df_fichas = extrair_dados_whatsapp(conteudo_texto)

    if not df_fichas.empty:
        st.success(f"Foram identificadas **{len(df_fichas)}** Ordens de Serviço no arquivo carregado!")
        if st.button("📊 Enviar Dados para Planilha Google", use_container_width=True):
            if sheet_obj is not None:
                try:
                    sheet_obj.clear()
                    sheet_obj.update([df_fichas.columns.values.tolist()] + df_fichas.astype(str).values.tolist())
                    st.success("✅ Dados sincronizados com sucesso no Google Sheets!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao atualizar a planilha: {e}")
            else:
                st.error("Não foi possível conectar com a planilha do Google.")
    else:
        st.warning("Não foram encontradas mensagens no padrão de OS no arquivo enviado.")
        df_fichas = pd.DataFrame()
else:
    with st.spinner("Carregando Ordens de Serviço sincronizadas do Google Sheets..."):
        df_fichas = carregar_dados_planilha()

if not df_fichas.empty:
    st.markdown("---")
    m1, m2, m3 = st.columns(3)
    m1.metric("Total de OS", len(df_fichas))
    
    cat_col = "Categoria" if "Categoria" in df_fichas.columns else None
    if cat_col:
        m2.metric("OS ADM", len(df_fichas[df_fichas[cat_col] == "OS ADM"]))
        m3.metric("OS ZML", len(df_fichas[df_fichas[cat_col] == "OS ZML"]))

    st.markdown("---")
    st.markdown("### 🔍 Filtros Específicos")
    
    c1, c2, c3 = st.columns(3)
    with c1:
        cat_filtro = st.selectbox("Categoria:", ["Todas", "OS ADM", "OS ZML"])
    with c2:
        mun_filtro = st.text_input("Cidade / Município:")
    with c3:
        pessoa_filtro = st.text_input("Motorista / Executor:")

    df_exibir = df_fichas.copy()

    if cat_filtro != "Todas" and "Categoria" in df_exibir.columns:
        df_exibir = df_exibir[df_exibir["Categoria"] == cat_filtro]
    if mun_filtro and "Cidade / Município" in df_exibir.columns:
        df_exibir = df_exibir[df_exibir["Cidade / Município"].astype(str).str.contains(mun_filtro, case=False, na=False)]
    if pessoa_filtro:
        cond_mot = df_exibir["Motorista"].astype(str).str.contains(pessoa_filtro, case=False, na=False) if "Motorista" in df_exibir.columns else False
        cond_exe = df_exibir["Executor / Passageiros"].astype(str).str.contains(pessoa_filtro, case=False, na=False) if "Executor / Passageiros" in df_exibir.columns else False
        df_exibir = df_exibir[cond_mot | cond_exe]

    st.markdown("---")
    st.dataframe(df_exibir, use_container_width=True, hide_index=True)
else:
    st.info("Nenhum dado encontrado na planilha do Google. Faça o upload do arquivo `chat.txt` na barra lateral para alimentar a base.")
