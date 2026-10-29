import os
import re
import unicodedata
from datetime import date, datetime, timedelta
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Painel Integrado de OS - BLOCO C", layout="wide")

# Endpoints Sirius
API_OS_URL = "https://unserrana.com.br/sirius/v1/wp-json/app/v1/data?tipo=app_get_os"
API_VAZADOS_URL = "https://unserrana.com.br/sirius/v1/wp-json/app/v1/data?tipo=app_get_vazados"
API_ADM_URLS = [
    "https://unserrana.com.br/sirius/v1/wp-json/app/v1/data?tipo=app_get_adm",
    "https://unserrana.com.br/sirius/v1/wp-json/app/v1/data?tipo=app_get_os_adm"
]

BASE_PDF_MANUTENCAO = "https://unserrana.com.br/sirius/v1/files/file.php?local=os-manutencao&download=pdf&v="
BASE_PDF_VAZADO = "https://unserrana.com.br/sirius/v1/files/file.php?local=os-vazado&download=pdf&v="

# Cidades oficiais do Bloco C
CIDADES_BLOCO_C_PRECISAS = {
    "ANADIA": ["ANADIA"],
    "CAMPESTRE": ["CAMPESTRE"],
    "CAPELA": ["CAPELA"],
    "COLÔNIA LEOPOLDINA": ["COLONIA LEOPOLDINA", "COLÔNIA LEOPOLDINA", "CLEOP", "LEOPOLDINA"],
    "IBATEGUARA": ["IBATEGUARA"],
    "JACUÍPE": ["JACUIPE", "JACUÍPE"],
    "JOAQUIM GOMES": ["JOAQUIM GOMES", "JGOMES", "J. GOMES", "J GOMES"],
    "JUNDIÁ": ["JUNDIA", "JUNDIÁ"],
    "JAPARATINGA": ["JAPARATINGA"],
    "MAR VERMELHO": ["MAR VERMELHO", "MVERMELHO"],
    "MARAGOGI": ["MARAGOGI", "P-MAR-", "MAR-", "ABOA", "SLUZ"],
    "MATRIZ DE CAMARAGIBE": ["MATRIZ DE CAMARAGIBE", "MATRIZ", "MAT-", "P-MAT-"],
    "MARIBONDO": ["MARIBONDO"],
    "NOVO LINO": ["NOVO LINO", "NLINO", "N. LINO", "N LINO"],
    "PASSO DE CAMARAGIBE": ["PASSO DE CAMARAGIBE", "PASSO"],
    "PAULO JACINTO": ["PAULO JACINTO", "PJACINTO"],
    "PINDOBA": ["PINDOBA"],
    "PORTO DE PEDRAS": ["PORTO DE PEDRAS", "PORTO"],
    "TAQUARANA": ["TAQUARANA"]
}

def remover_acentos(texto):
    if not texto or pd.isna(texto):
        return ""
    txt_limpo = re.sub(r"&[a-zA-Z0-9#]+;", " ", str(texto))
    return "".join(c for c in unicodedata.normalize('NFD', txt_limpo) if unicodedata.category(c) != 'Mn').upper().strip()

def identificar_cidades_bloco_c_texto(texto):
    txt_norm = remover_acentos(texto)
    cidades_encontradas = []
    for mun_real, termos in CIDADES_BLOCO_C_PRECISAS.items():
        for t in termos:
            t_norm = remover_acentos(t)
            if re.search(rf"\b{re.escape(t_norm)}\b", txt_norm) or t_norm in txt_norm:
                if mun_real not in cidades_encontradas:
                    cidades_encontradas.append(mun_real)
                break
    return cidades_encontradas

def normalizar_ordem(valor):
    if pd.isna(valor) or str(valor).strip().lower() in ["none", "nan", "null", "", "n/i"]:
        return ""
    val_str = str(valor).strip().split(".")[0]
    match = re.search(r"\d+", val_str)
    return match.group(0) if match else ""

def extrair_valor(dicionario, chaves, padrao="N/I"):
    for k in chaves:
        if k in dicionario and dicionario[k]:
            v = str(dicionario[k]).strip()
            if v.lower() not in ["none", "nan", "null", "", "n", "n/i"]:
                return v
    return padrao

def tratar_equipe_api(item):
    """Extrai a equipe do JSON da API (prioriza 'equipe' e 'executor' sobre 'por')."""
    equipe_raw = item.get("equipe", [])
    if isinstance(equipe_raw, list) and len(equipe_raw) > 0:
        eq_filtrada = [str(nome).strip() for nome in equipe_raw if str(nome).strip() and str(nome).strip().lower() not in ["none", "null", "n/i", ""]]
        if eq_filtrada:
            return ", ".join(eq_filtrada)
    
    executor_raw = item.get("executor", "")
    if executor_raw and str(executor_raw).strip().lower() not in ["none", "null", "n/i", "", " "]:
        return str(executor_raw).strip()
        
    return ""

def extrair_data_dt(texto_data):
    if not texto_data or str(texto_data).lower() in ["n/i", "none", "nan", ""]:
        return None
    try:
        m_iso = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", str(texto_data))
        if m_iso:
            return date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
        m_br = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", str(texto_data))
        if m_br:
            return date(int(m_br.group(3)), int(m_br.group(2)), int(m_br.group(1)))
    except Exception:
        pass
    return None

@st.cache_data(ttl=600)
def carregar_dados_locais():
    mapeamento = {}
    for arq in os.listdir("."):
        if arq.lower().endswith((".csv", ".xls", ".xlsx")):
            df = pd.DataFrame()
            for skip in [3, 0, 1, 2, 4]:
                try:
                    if arq.lower().endswith(".csv"):
                        df_tmp = pd.read_csv(arq, skiprows=skip, low_memory=False)
                    else:
                        df_tmp = pd.read_excel(arq, skiprows=skip)

                    cols_str = [str(c).upper().strip() for c in df_tmp.columns]
                    if any("ORDEM" in c or c == "#" for c in cols_str) or df_tmp.shape[1] >= 11:
                        df = df_tmp
                        break
                except Exception:
                    continue

            if not df.empty:
                cols_map = {str(c).upper().strip(): c for c in df.columns}
                col_ordem = next((c for k, c in cols_map.items() if "ORDEM" in k or k in ["#", "SS"]), None)
                col_equipe = next((c for k, c in cols_map.items() if any(x in k for x in ["EQUIPE", "EXECUTOR", "MOTORISTA", "TECNICO", "FUNCIONARIO"])), None)
                col_servico = next((c for k, c in cols_map.items() if any(x in k for x in ["SERVIÇO", "SERVICO", "ATIVIDADE"])), None)
                col_estacao = next((c for k, c in cols_map.items() if any(x in k for x in ["ESTACAO", "LOCAL", "LOCAIS", "BAIRRO", "ENDEREÇO"])), None)

                if col_ordem is not None:
                    for _, row in df.iterrows():
                        ordem_norm = normalizar_ordem(row.get(col_ordem))
                        if ordem_norm:
                            eq = str(row.get(col_equipe, "")).strip() if col_equipe and pd.notna(row.get(col_equipe)) else ""
                            srv = str(row.get(col_servico, "")).strip() if col_servico and pd.notna(row.get(col_servico)) else ""
                            est = str(row.get(col_estacao, "")).strip() if col_estacao and pd.notna(row.get(col_estacao)) else ""

                            if ordem_norm not in mapeamento:
                                mapeamento[ordem_norm] = {"equipe": eq, "servico": srv, "estacao": est}
                            else:
                                if est and mapeamento[ordem_norm]["estacao"] == "":
                                    mapeamento[ordem_norm]["estacao"] = est
                                if eq and mapeamento[ordem_norm]["equipe"] == "":
                                    mapeamento[ordem_norm]["equipe"] = eq
    return mapeamento

def requisitar_api(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, dict):
                for k in ["data", "os", "vazados", "registros", "adm", "itens", "dados"]:
                    if k in dados and isinstance(dados[k], list):
                        return dados[k]
            elif isinstance(dados, list):
                return dados
    except Exception:
        pass
    return []

@st.cache_data(ttl=300)
def carregar_dados():
    todas_os = []
    mapeamento_local = carregar_dados_locais()

    # 1. OS DE SERVIÇO
    dados_os = requisitar_api(API_OS_URL)
    for item in dados_os:
        if isinstance(item, dict):
            bloco = extrair_valor(item, ["bloco", "regional"], "")
            municipio_api = extrair_valor(item, ["municipio_nome", "cidade", "municipio"], "")
            conteudo_item = f"{bloco} {municipio_api} " + " ".join([f"{v}" for v in item.values() if v])

            cidades_enc = identificar_cidades_bloco_c_texto(conteudo_item)
            if "Bloco C" in bloco or "ZML" in bloco or cidades_enc:
                num_os = extrair_valor(item, ["id", "ordem", "#", "os", "numero"])
                os_norm = normalizar_ordem(num_os)
                if os_norm:
                    dt_txt = extrair_valor(item, ["data", "created_at", "data_os", "data_saida"])
                    
                    # 1. Tenta extrair a equipe da API Sirius primeiro
                    equipe_api = tratar_equipe_api(item)
                    # 2. Se não tiver, busca no mapeamento local de arquivos
                    eq_local = mapeamento_local.get(os_norm, {}).get("equipe", "")
                    # 3. Se ainda assim não encontrar, exibe quem criou ou aviso
                    cadastrador = extrair_valor(item, ["por", "solicitante"], "N/I")
                    
                    if equipe_api:
                        pessoa_final = equipe_api
                    elif eq_local:
                        pessoa_final = eq_local
                    else:
                        pessoa_final = cadastrador if cadastrador != "N/I" else "N/I"

                    est_api = extrair_valor(item, ["estacao_nome", "estacao", "unidade", "local"], "")
                    est_local = mapeamento_local.get(os_norm, {}).get("estacao", "")
                    est_final = est_local if est_local else (est_api if est_api != "N/I" else "N/I")

                    mun_final = ", ".join(cidades_enc) if cidades_enc else (municipio_api if municipio_api != "N/I" else "Bloco C")
                    srv_api = extrair_valor(item, ["servico", "descricao", "atividade", "motivo"], "Manutenção Eletromecânica")

                    todas_os.append({
                        "Data / Hora": dt_txt,
                        "# OS": os_norm,
                        "Categoria": "OS de Serviço",
                        "Município": mun_final,
                        "Local / Estação": est_final,
                        "Serviço / Info": srv_api,
                        "Equipe / Responsáveis": pessoa_final,
                        "Status": extrair_valor(item, ["status_sistema", "status", "situacao"], "Finalizado"),
                        "Link_PDF": f"{BASE_PDF_MANUTENCAO}{os_norm}",
                        "dt_date": extrair_data_dt(dt_txt)
                    })

    # 2. OS DE VAZAMENTO
    dados_vazados = requisitar_api(API_VAZADOS_URL)
    for item in dados_vazados:
        if isinstance(item, dict):
            conteudo_item = " ".join([f"{v}" for v in item.values() if v])
            cidades_enc = identificar_cidades_bloco_c_texto(conteudo_item)
            if cidades_enc or "ZML" in remover_acentos(conteudo_item) or "BLOCO C" in remover_acentos(conteudo_item):
                num_os = extrair_valor(item, ["id", "ordem", "#", "os", "numero"])
                os_norm = normalizar_ordem(num_os)
                if os_norm:
                    dt_txt = extrair_valor(item, ["data", "created_at", "data_os"])
                    
                    equipe_api = tratar_equipe_api(item)
                    eq_local = mapeamento_local.get(os_norm, {}).get("equipe", "")
                    cadastrador = extrair_valor(item, ["por", "solicitante"], "N/I")
                    
                    pessoa_final = equipe_api if equipe_api else (eq_local if eq_local else cadastrador)

                    mun = extrair_valor(item, ["municipio_nome", "municipio", "cidade"])
                    est = extrair_valor(item, ["estacao_nome", "estacao", "local", "bairro"])
                    srv = extrair_valor(item, ["servico", "descricao"], "Vazamento de Água/Esgoto")

                    todas_os.append({
                        "Data / Hora": dt_txt,
                        "# OS": os_norm,
                        "Categoria": "OS de Vazamento",
                        "Município": ", ".join(cidades_enc) if cidades_enc else (mun if mun != "N/I" else "Bloco C"),
                        "Local / Estação": est,
                        "Serviço / Info": srv,
                        "Equipe / Responsáveis": pessoa_final,
                        "Status": extrair_valor(item, ["status_sistema", "status"], "Finalizado"),
                        "Link_PDF": f"{BASE_PDF_VAZADO}{os_norm}",
                        "dt_date": extrair_data_dt(dt_txt)
                    })

    # 3. OS ADM - REGRAS DE VALIDAÇÃO AMPLIADAS
    for url_adm in API_ADM_URLS:
        dados_adm = requisitar_api(url_adm)
        for item in dados_adm:
            if isinstance(item, dict):
                regional_adm = extrair_valor(item, ["regional", "bloco"], "")
                locais_api = extrair_valor(item, ["locais", "destino", "municipio_nome", "municipio", "local"], "")
                obs_api = extrair_valor(item, ["observacao", "observacoes", "descricao", "servico", "atividade"], "")
                texto_total_adm = f"{regional_adm} {locais_api} {obs_api} " + " ".join([f"{v}" for v in item.values() if v])

                cidades_bloco_c_adm = identificar_cidades_bloco_c_texto(texto_total_adm)

                # Aceita se tiver cidade do Bloco C, ou se a regional for ZML / Bloco C
                if cidades_bloco_c_adm or "ZML" in remover_acentos(texto_total_adm) or "BLOCO C" in remover_acentos(texto_total_adm):
                    num_os = extrair_valor(item, ["id", "ordem", "#", "os", "numero", "codigo"])
                    os_norm = normalizar_ordem(num_os)
                    if os_norm:
                        dt_txt = extrair_valor(item, ["data", "data_saida", "created_at", "data_os"])
                        
                        # Tratamento da equipe/motorista no ADM
                        equipe_api = tratar_equipe_api(item)
                        mot = extrair_valor(item, ["motorista", "motorista_nome", "por", "responsavel", "usuario", "solicitante"])
                        pessoa_final = equipe_api if equipe_api else (mot if mot != "N/I" else "N/I")

                        ativ = extrair_valor(item, ["atividade", "servico", "descricao", "motivo"], "Deslocamento ADM")
                        veic = extrair_valor(item, ["veiculo", "veiculo_placa", "placa"], "")

                        locais_formatados = ", ".join(cidades_bloco_c_adm) if cidades_bloco_c_adm else (locais_api if locais_api != "N/I" else "Bloco C")

                        todas_os.append({
                            "Data / Hora": dt_txt,
                            "# OS": os_norm,
                            "Categoria": "OS ADM / Deslocamento",
                            "Município": locais_formatados,
                            "Local / Estação": locais_api if locais_api != "N/I" else locais_formatados,
                            "Serviço / Info": f"{ativ} ({veic})" if veic and veic != "N/I" else str(ativ),
                            "Equipe / Responsáveis": pessoa_final,
                            "Status": extrair_valor(item, ["status_sistema", "status", "situacao"], "Finalizado"),
                            "Link_PDF": f"{BASE_PDF_MANUTENCAO}{os_norm}",
                            "dt_date": extrair_data_dt(dt_txt)
                        })

    df = pd.DataFrame(todas_os)
    if not df.empty:
        df.drop_duplicates(subset=["# OS"], inplace=True)

    return df

# --- INTERFACE PRINCIPAL STREAMLIT ---
st.title("📋 Painel Unificado de OS - BLOCO C")

col_top1, col_top2 = st.columns([8, 2])
with col_top2:
    if st.button("🔄 Atualizar Dados", use_container_width=True):
        st.cache_data.clear()

with st.spinner("Carregando dados unificados do Bloco C..."):
    df_geral = carregar_dados()

if not df_geral.empty:
    st.markdown("---")
    st.markdown("### 📅 Filtro por Categoria e Período")
    
    c_chk, c_dt1, c_dt2, c_cat = st.columns([1, 1.5, 1.5, 2])

    hoje = date.today()
    tres_dias_atras = hoje - timedelta(days=3)

    with c_chk:
        filtrar_por_data = st.checkbox("Ativar Filtro de Data", value=True)
    with c_dt1:
        data_inicio = st.date_input("Data Inicial:", value=tres_dias_atras, format="DD/MM/YYYY")
    with c_dt2:
        data_fim = st.date_input("Data Final:", value=hoje, format="DD/MM/YYYY")
    with c_cat:
        filtro_categoria = st.selectbox(
            "Categoria de OS:",
            ["Todas as Categorias", "OS de Serviço", "OS de Vazamento", "OS ADM / Deslocamento"]
        )

    st.markdown("### 🔍 Filtros Específicos")
    col2, col3, col4, col5 = st.columns([1, 1, 1, 1.2])

    with col2:
        busca_municipio = st.text_input("🏙️ Município:")
    with col3:
        busca_estacao = st.text_input("📍 Unidade / Estação:")
    with col4:
        busca_pessoa = st.text_input("👤 Funcionário / Equipe:")
    with col5:
        busca_geral = st.text_input("🔍 Busca Geral (# OS, Serviço):")

    df_filtrado = df_geral.copy()

    if filtrar_por_data:
        df_filtrado = df_filtrado[
            df_filtrado["dt_date"].apply(
                lambda d: True if d is None else (data_inicio <= d <= data_fim)
            )
        ]

    if filtro_categoria != "Todas as Categorias":
        df_filtrado = df_filtrado[df_filtrado["Categoria"] == filtro_categoria]

    if busca_municipio:
        df_filtrado = df_filtrado[df_filtrado["Município"].astype(str).str.contains(busca_municipio, case=False, na=False)]
    if busca_estacao:
        df_filtrado = df_filtrado[df_filtrado["Local / Estação"].astype(str).str.contains(busca_estacao, case=False, na=False)]
    if busca_pessoa:
        df_filtrado = df_filtrado[df_filtrado["Equipe / Responsáveis"].astype(str).str.contains(busca_pessoa, case=False, na=False)]
    if busca_geral:
        df_filtrado = df_filtrado[
            df_filtrado["# OS"].astype(str).str.contains(busca_geral, case=False, na=False) |
            df_filtrado["Serviço / Info"].astype(str).str.contains(busca_geral, case=False, na=False)
        ]

    # Métricas
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Exibido", len(df_filtrado))
    m2.metric("OS Serviço", len(df_filtrado[df_filtrado["Categoria"] == "OS de Serviço"]))
    m3.metric("OS Vazamentos", len(df_filtrado[df_filtrado["Categoria"] == "OS de Vazamento"]))
    m4.metric("OS ADM", len(df_filtrado[df_filtrado["Categoria"] == "OS ADM / Deslocamento"]))

    st.markdown("---")

    colunas_tabela = [
        "Data / Hora", "# OS", "Categoria", "Município", 
        "Local / Estação", "Serviço / Info", "Equipe / Responsáveis", 
        "Status", "Link_PDF"
    ]

    st.dataframe(
        df_filtrado[colunas_tabela],
        column_config={
            "Link_PDF": st.column_config.LinkColumn("Documento PDF", display_text="📄 Abrir PDF")
        },
        use_container_width=True,
        hide_index=True
    )
else:
    st.warning("Nenhuma ordem de serviço do Bloco C foi encontrada no período selecionado.")
