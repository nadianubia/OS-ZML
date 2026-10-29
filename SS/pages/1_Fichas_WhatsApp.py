import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Ordens de Serviço - WhatsApp", layout="wide")

st.title("📲 Ordens de Serviço (WhatsApp)")
st.markdown("Faça o upload do arquivo `chat.txt` na barra lateral para carregar e filtrar as Ordens de Serviço.")

# Barra lateral para upload do ficheiro chat.txt
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
        st.warning("Não foram encontradas mensagens no padrão de OS no arquivo enviado.")
else:
    st.info("👆 Selecione o arquivo `chat.txt` na barra lateral esquerda para visualizar e filtrar as Ordens de Serviço.")
