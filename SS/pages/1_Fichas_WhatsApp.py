import re
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Fichas Operacionais - WhatsApp", layout="wide")

st.title("📲 Fichas Operacionais (WhatsApp)")
st.markdown("Carregue o arquivo `chat.txt` para extrair, consultar e sincronizar as fichas com o Google Sheets.")

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
        
        atividade = buscar_campo(r"ATIVIDADE\s*:\s*(.*)", padrao_padrao="Serviço Registado no WhatsApp")

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
            "Veículo": veiculo,
            "Atividade / Detalhes": atividade
        })

    return pd.DataFrame(registos)

if uploaded_chat is not None:
    conteudo_texto = uploaded_chat.read().decode("utf-8")
    df_fichas = extrair_dados_whatsapp(conteudo_texto)

    if not df_fichas.empty:
        st.success(f"Foram identificadas **{len(df_fichas)}** fichas de OS no arquivo!")
        
        # BOTÃO DE SINCRONIZAÇÃO COM O GOOGLE SHEETS
        col_btn1, col_btn2 = st.columns([4, 6])
        with col_btn1:
            if st.button("📊 Enviar Dados para Planilha Google", use_container_width=True):
                try:
                    conn = st.connection("gsheets", type=GSheetsConnection)
                    conn.update(data=df_fichas)
                    st.success("✅ Dados sincronizados com sucesso no Google Sheets!")
                except Exception as e:
                    st.error(f"Erro ao conectar com Google Sheets: {e}")

        st.markdown("---")
        m1, m2, m3 = st.columns(3)
        m1.metric("Total de Fichas", len(df_fichas))
        m2.metric("OS ADM", len(df_fichas[df_fichas["Categoria"] == "OS ADM"]))
        m3.metric("OS ZML", len(df_fichas[df_fichas["Categoria"] == "OS ZML"]))

        st.markdown("---")
        st.markdown("### 🔍 Filtros Específicos")
        
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            cat_filtro = st.selectbox("Categoria:", ["Todas", "OS ADM", "OS ZML"])
        with c2:
            mun_filtro = st.text_input("Cidade / Município:")
        with c3:
            pessoa_filtro = st.text_input("Motorista / Executor:")
        with c4:
            busca_geral = st.text_input("Busca na Atividade:")

        df_exibir = df_fichas.copy()

        if cat_filtro != "Todas":
            df_exibir = df_exibir[df_exibir["Categoria"] == cat_filtro]
        if mun_filtro:
            df_exibir = df_exibir[df_exibir["Cidade / Município"].str.contains(mun_filtro, case=False, na=False)]
        if pessoa_filtro:
            df_exibir = df_exibir[
                df_exibir["Motorista"].str.contains(pessoa_filtro, case=False, na=False) |
                df_exibir["Executor / Passageiros"].str.contains(pessoa_filtro, case=False, na=False)
            ]
        if busca_geral:
            df_exibir = df_exibir[
                df_exibir["Atividade / Detalhes"].str.contains(busca_geral, case=False, na=False)
            ]

        colunas_exibicao = [
            "Data", "Categoria", "Cidade / Município", 
            "Motorista", "Executor / Passageiros", "Veículo",
            "Saída Base", "Chegada Serviço", "Saída Serviço", "Chegada Base",
            "Atividade / Detalhes"
        ]

        st.markdown("---")
        st.dataframe(df_exibir[colunas_exibicao], use_container_width=True, hide_index=True)
    else:
        st.warning("Não foram encontradas mensagens no padrão de OS no arquivo enviado.")
else:
    st.info("Aguardando o envio do arquivo `chat.txt` na barra lateral para carregar o painel.")