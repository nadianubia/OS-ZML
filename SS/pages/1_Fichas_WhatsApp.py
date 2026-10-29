import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Ordens de Serviço - WhatsApp", layout="wide")

st.title("📲 Ordens de Serviço (WhatsApp)")
st.markdown("Faça o upload do arquivo `chat.txt` na barra lateral para carregar e filtrar as Ordens de Serviço.")

# Barra lateral para upload do arquivo chat.txt
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
        
        # Extrai o campo Atividade (buscando por ATIVIDADE, ATIVIDADES ou SERVIÇO)
        atividade = buscar_campo(r"(?:ATIVIDADES?|DESCRIÇÃO\s+(?:DA\s+)?ATIVIDADE|SERVIÇOS?)\s*:\s*([^\n\r]+)")
        
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
            "Atividade": atividade
        })

    return pd.DataFrame(registos)

# Leitura e processamento do arquivo
if uploaded_chat is not None:
    conteudo_texto = uploaded_chat.read().decode("utf-8")
    df_fichas = extrair_dados_whatsapp(conteudo_texto)

    if not df_fichas.empty:
        st.success(f"Foram identificadas **{len(df_fichas)}** Ordens de Serviço no arquivo carregado!")
        
        # Exibição de métricas rápidas
        st.markdown("---")
        m1, m2, m3 = st.columns(3)
        m1.metric("Total de OS", len(df_fichas))
        
        cat_col = "Categoria" if "Categoria" in df_fichas.columns else None
        if cat_col:
            m2.metric("OS ADM", len(df_fichas[df_fichas[cat_col] == "OS ADM"]))
            m3.metric("OS ZML", len(df_fichas[df_fichas[cat_col] == "OS ZML"]))

        # Seção de Filtros
        st.markdown("---")
        st.markdown("### 🔍 Filtros Específicos")
        
        # Linha 1 de Filtros: Período de Datas
        r1_c1, r1_c2 = st.columns(2)
        with r1_c1:
            data_inicio = st.date_input("Data Inicial:", value=None, format="DD/MM/YYYY")
        with r1_c2:
            data_fim = st.date_input("Data Final:", value=None, format="DD/MM/YYYY")

        # Linha 2 de Filtros: Categoria, Cidade, Pessoas
        r2_c1, r2_c2, r2_c3 = st.columns(3)
        with r2_c1:
            cat_filtro = st.selectbox("Categoria:", ["Todas", "OS ADM", "OS ZML"])
        with r2_c2:
            mun_filtro = st.text_input("Cidade / Município:")
        with r2_c3:
            pessoa_filtro = st.text_input("Motorista / Executor:")

        # Linha 3 de Filtros: Horários e Atividade
        r3_c1, r3_c2, r3_c3 = st.columns(3)
        with r3_c1:
            saida_base_filtro = st.text_input("Hora Saída da Base (ex: 08:00):")
        with r3_c2:
            chegada_base_filtro = st.text_input("Hora Chegada na Base (ex: 18:00):")
        with r3_c3:
            atividade_filtro = st.text_input("Atividade:")

        df_exibir = df_fichas.copy()

        # Filtro de Intervalo de Datas
        if "Data" in df_exibir.columns and (data_inicio or data_fim):
            datas_convertidas = pd.to_datetime(df_exibir["Data"], dayfirst=True, errors="coerce").dt.date
            if data_inicio:
                df_exibir = df_exibir[datas_convertidas >= data_inicio]
            if data_fim:
                df_exibir = df_exibir[datas_convertidas <= data_fim]

        # Aplicação dos demais filtros
        if cat_filtro != "Todas" and "Categoria" in df_exibir.columns:
            df_exibir = df_exibir[df_exibir["Categoria"] == cat_filtro]
        if mun_filtro and "Cidade / Município" in df_exibir.columns:
            df_exibir = df_exibir[df_exibir["Cidade / Município"].astype(str).str.contains(mun_filtro, case=False, na=False)]
        if pessoa_filtro:
            cond_mot = df_exibir["Motorista"].astype(str).str.contains(pessoa_filtro, case=False, na=False) if "Motorista" in df_exibir.columns else False
            cond_exe = df_exibir["Executor / Passageiros"].astype(str).str.contains(pessoa_filtro, case=False, na=False) if "Executor / Passageiros" in df_exibir.columns else False
            df_exibir = df_exibir[cond_mot | cond_exe]
        
        if saida_base_filtro and "Saída Base" in df_exibir.columns:
            df_exibir = df_exibir[df_exibir["Saída Base"].astype(str).str.contains(saida_base_filtro, case=False, na=False)]
        if chegada_base_filtro and "Chegada Base" in df_exibir.columns:
            df_exibir = df_exibir[df_exibir["Chegada Base"].astype(str).str.contains(chegada_base_filtro, case=False, na=False)]
        if atividade_filtro and "Atividade" in df_exibir.columns:
            df_exibir = df_exibir[df_exibir["Atividade"].astype(str).str.contains(atividade_filtro, case=False, na=False)]

        st.markdown("---")
        st.dataframe(df_exibir, use_container_width=True, hide_index=True)
    else:
        st.warning("Não foram encontradas mensagens no padrão de OS no arquivo enviado.")
else:
    st.info("👆 Selecione o arquivo `chat.txt` na barra lateral esquerda para visualizar e filtrar as Ordens de Serviço.")
