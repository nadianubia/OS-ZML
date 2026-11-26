import base64
import hashlib
import os
import re
import tomllib
import unicodedata
from datetime import date, time, timedelta
import pandas as pd
import streamlit as st
from google.cloud import bigquery
from google.oauth2 import service_account

st.set_page_config(page_title="Ordens de Serviço - ZML / CASAL", layout="wide")

# --- CONFIGURAÇÃO BIGQUERY ---
BQ_PROJECT = "os-whatsapp-513112"
BQ_DATASET = "os_whatsapp"
BQ_TABLE = "os_bloco_c"

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
    "TAQUARANA": ["TAQUARANA"],
}

COLUNAS_TABELA = [
    "Data",
    "Saída da Base",
    "Chegada Serviço",
    "Saída Serviço",
    "Chegada Base",
    "Categoria",
    "Unidade / Estação",
    "Motorista / Executor",
    "Serviço / Info",
    "Material Utilizado",
]


def remover_acentos(texto):
    if not texto or pd.isna(texto):
        return ""
    txt_limpo = re.sub(r"&[a-zA-Z0-9#]+;", " ", str(texto))
    return "".join(
        c for c in unicodedata.normalize("NFD", txt_limpo) if unicodedata.category(c) != "Mn"
    ).upper().strip()


def gerar_chave_dedup(data_str, hora_ref, local, municipio=""):
    dh_norm = re.sub(r"\s+", " ", remover_acentos(f"{data_str} {hora_ref}"))
    loc_norm = re.sub(r"\s+", " ", remover_acentos(local))
    if not loc_norm or loc_norm in ["N/I", "NONE", "NAN"]:
        loc_norm = re.sub(r"\s+", " ", remover_acentos(municipio))
    base = f"{dh_norm}|{loc_norm}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def identificar_cidades_bloco_c(texto):
    txt_norm = remover_acentos(texto)
    encontradas = []
    for mun_real, termos in CIDADES_BLOCO_C_PRECISAS.items():
        for t in termos:
            t_norm = remover_acentos(t)
            if re.search(rf"\b{re.escape(t_norm)}\b", txt_norm) or t_norm in txt_norm:
                if mun_real not in encontradas:
                    encontradas.append(mun_real)
                break
    return encontradas


def extrair_data_dt(texto):
    if not texto or str(texto).strip().lower() in ["n/i", "none", "nan", ""]:
        return None
    s = str(texto).strip()
    m_br = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", s)
    if m_br:
        dia, mes, ano = int(m_br.group(1)), int(m_br.group(2)), int(m_br.group(3))
        if ano < 100:
            ano += 2000
        try:
            return date(ano, mes, dia)
        except ValueError:
            return None
    return None


def extrair_hora_time(texto):
    if not texto or str(texto).strip().lower() in ["n/i", "none", "nan", ""]:
        return None
    m = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", str(texto))
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        s = int(m.group(3)) if m.group(3) else 0
        if 0 <= h <= 23 and 0 <= mi <= 59 and 0 <= s <= 59:
            return time(h, mi, s)
    return None


def _formatar_hora_col(val):
    t = val if isinstance(val, time) else extrair_hora_time(val)
    return t.strftime("%H:%M") if t is not None else "N/I"


def _buscar_dict_credenciais(fonte_dict):
    if not isinstance(fonte_dict, dict):
        return None

    for secao in ["gcp_service_account", "bigquery"]:
        if secao in fonte_dict and isinstance(fonte_dict[secao], dict):
            info = dict(fonte_dict[secao])
            if info.get("private_key") and info.get("client_email"):
                return info

    conns = fonte_dict.get("connections")
    if isinstance(conns, dict) and isinstance(conns.get("gsheets"), dict):
        info = dict(conns["gsheets"])
        if info.get("private_key") and info.get("client_email"):
            return info

    if fonte_dict.get("private_key") and fonte_dict.get("client_email"):
        return {k: v for k, v in fonte_dict.items() if not isinstance(v, dict)}

    return None


def _extrair_info_service_account():
    try:
        info = _buscar_dict_credenciais(dict(st.secrets))
        if info:
            return info
    except Exception:
        pass

    base_dir = os.path.dirname(os.path.abspath(__file__))
    caminhos_candidatos = [
        os.path.join(".streamlit", "secrets.toml"),
        "secrets.toml",
        os.path.join(base_dir, ".streamlit", "secrets.toml"),
        os.path.join(base_dir, "secrets.toml"),
    ]
    for caminho in caminhos_candidatos:
        if os.path.exists(caminho):
            try:
                with open(caminho, "rb") as f:
                    dados_toml = tomllib.load(f)
                info_arq = _buscar_dict_credenciais(dados_toml)
                if info_arq:
                    return info_arq
            except Exception:
                pass
    return None


@st.cache_resource
def obter_cliente_bq():
    try:
        info = _extrair_info_service_account()
        if info:
            creds = service_account.Credentials.from_service_account_info(info)
            proj = info.get("project_id") or BQ_PROJECT
            return bigquery.Client(project=proj, credentials=creds)
        return bigquery.Client(project=BQ_PROJECT)
    except Exception as e:
        st.error(f"Erro ao conectar ao BigQuery: {e}")
        return None


def garantir_tabela_bq(client):
    dataset_ref = bigquery.DatasetReference(client.project, BQ_DATASET)
    try:
        client.get_dataset(dataset_ref)
    except Exception:
        try:
            ds = bigquery.Dataset(dataset_ref)
            ds.location = "US"
            client.create_dataset(ds, exists_ok=True)
        except Exception:
            pass

    schema = [
        bigquery.SchemaField("chave_dedup", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("data_hora", "STRING"),
        bigquery.SchemaField("saida_base", "STRING"),
        bigquery.SchemaField("chegada_servico", "STRING"),
        bigquery.SchemaField("saida_servico", "STRING"),
        bigquery.SchemaField("chegada_base", "STRING"),
        bigquery.SchemaField("num_os", "STRING"),
        bigquery.SchemaField("categoria", "STRING"),
        bigquery.SchemaField("municipio", "STRING"),
        bigquery.SchemaField("local_estacao", "STRING"),
        bigquery.SchemaField("servico_info", "STRING"),
        bigquery.SchemaField("material_utilizado", "STRING"),
        bigquery.SchemaField("equipe_responsaveis", "STRING"),
        bigquery.SchemaField("status", "STRING"),
        bigquery.SchemaField("dt_date", "DATE"),
    ]
    table_ref = dataset_ref.table(BQ_TABLE)
    table = bigquery.Table(table_ref, schema=schema)
    table = client.create_table(table, exists_ok=True)
    tabela_fqn = f"`{client.project}.{BQ_DATASET}.{BQ_TABLE}`"

    colunas_existentes = {campo.name.lower() for campo in table.schema}
    for campo in schema:
        if campo.name.lower() not in colunas_existentes:
            client.query(
                f"ALTER TABLE {tabela_fqn} ADD COLUMN IF NOT EXISTS {campo.name} {campo.field_type}"
            ).result()

    return tabela_fqn


def normalizar_df(df):
    cols_time_aux = ["t_saida_base", "t_chegada_servico", "t_saida_servico", "t_chegada_base"]
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUNAS_TABELA + ["dt_date", "chave_dedup", "Município"] + cols_time_aux)

    out = df.copy()
    if "dt_date" not in out.columns:
        origem_dt = out["Data"] if "Data" in out.columns else out.get("Data / Hora", pd.Series([None] * len(out)))
        out["dt_date"] = origem_dt.apply(extrair_data_dt)
    else:
        out["dt_date"] = pd.to_datetime(out["dt_date"], errors="coerce").dt.date
        sem_dt = out["dt_date"].isna()
        if sem_dt.any():
            origem_dt = out.loc[sem_dt, "Data"] if "Data" in out.columns else out.loc[sem_dt, "Data / Hora"]
            out.loc[sem_dt, "dt_date"] = origem_dt.apply(extrair_data_dt)

    out["Data"] = out["dt_date"].apply(lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "N/I")

    mapa_col_time = {
        "Saída da Base": "t_saida_base",
        "Chegada Serviço": "t_chegada_servico",
        "Saída Serviço": "t_saida_servico",
        "Chegada Base": "t_chegada_base",
    }
    for col_txt, col_t in mapa_col_time.items():
        if col_t not in out.columns:
            origem = out[col_txt] if col_txt in out.columns else pd.Series([None] * len(out), index=out.index)
            out[col_t] = origem.apply(extrair_hora_time)
        else:
            out[col_t] = out[col_t].apply(lambda v: v if isinstance(v, time) else extrair_hora_time(v))
        out[col_txt] = out[col_t].apply(_formatar_hora_col)

    for col in COLUNAS_TABELA:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str).str.strip()

    mask_mat_embutido = (
        out["Serviço / Info"].str.contains(r"\|\s*Material:\s*", case=False, na=False)
        & out["Material Utilizado"].isin(["", "N/I", "None", "nan"])
    )
    if mask_mat_embutido.any():
        for idx in out[mask_mat_embutido].index:
            txt_srv = out.at[idx, "Serviço / Info"]
            m_mat = re.search(r"\|\s*Material:\s*(.+)$", txt_srv, flags=re.IGNORECASE)
            if m_mat:
                out.at[idx, "Material Utilizado"] = m_mat.group(1).strip()
                out.at[idx, "Serviço / Info"] = re.sub(r"\s*\|\s*Material:\s*.+$", "", txt_srv).strip()

    if "Município" not in out.columns:
        out["Município"] = ""
    else:
        out["Município"] = out["Município"].fillna("").astype(str).str.strip()

    out["chave_dedup"] = out.apply(
        lambda r: gerar_chave_dedup(
            r["Data"],
            r["Saída da Base"] if r["Saída da Base"] != "N/I" else r["Chegada Serviço"],
            r["Unidade / Estação"],
            r["Município"],
        ),
        axis=1,
    )
    out.drop_duplicates(subset=["chave_dedup"], keep="first", inplace=True)
    return out


def ler_dados_bq(data_inicial=None, data_final=None):
    client = obter_cliente_bq()
    if client is None:
        return pd.DataFrame()
    try:
        tabela_fqn = garantir_tabela_bq(client)
        if data_inicial is not None and data_final is not None:
            query = f"""
                SELECT
                    saida_base,
                    chegada_servico,
                    saida_servico,
                    chegada_base,
                    categoria,
                    municipio,
                    local_estacao,
                    servico_info,
                    material_utilizado,
                    equipe_responsaveis,
                    dt_date,
                    chave_dedup
                FROM {tabela_fqn}
                WHERE dt_date BETWEEN @dt_ini AND @dt_fim
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("dt_ini", "DATE", data_inicial),
                    bigquery.ScalarQueryParameter("dt_fim", "DATE", data_final),
                ]
            )
            df_bq = client.query(query, job_config=job_config).to_dataframe()
        else:
            query = f"""
                WITH ultima_data AS (
                    SELECT MAX(dt_date) AS max_dt
                    FROM {tabela_fqn}
                    WHERE dt_date IS NOT NULL
                )
                SELECT
                    t.saida_base,
                    t.chegada_servico,
                    t.saida_servico,
                    t.chegada_base,
                    t.categoria,
                    t.municipio,
                    t.local_estacao,
                    t.servico_info,
                    t.material_utilizado,
                    t.equipe_responsaveis,
                    t.dt_date,
                    t.chave_dedup
                FROM {tabela_fqn} t
                CROSS JOIN ultima_data u
                WHERE u.max_dt IS NULL OR t.dt_date = u.max_dt
            """
            df_bq = client.query(query).to_dataframe()

        if df_bq is not None and not df_bq.empty:
            df_bq = df_bq.rename(columns={
                "saida_base": "Saída da Base",
                "chegada_servico": "Chegada Serviço",
                "saida_servico": "Saída Serviço",
                "chegada_base": "Chegada Base",
                "categoria": "Categoria",
                "municipio": "Município",
                "local_estacao": "Unidade / Estação",
                "servico_info": "Serviço / Info",
                "material_utilizado": "Material Utilizado",
                "equipe_responsaveis": "Motorista / Executor",
            })

        return normalizar_df(df_bq)
    except Exception as e:
        st.error(f"Erro ao buscar dados no BigQuery: {e}")
        return pd.DataFrame()


def salvar_no_bq(df_novos):
    client = obter_cliente_bq()
    if client is None or df_novos is None or df_novos.empty:
        return 0
    prep = normalizar_df(df_novos)
    if prep.empty:
        return 0
    try:
        tabela_fqn = garantir_tabela_bq(client)
        existentes = client.query(f"SELECT DISTINCT chave_dedup FROM {tabela_fqn}").to_dataframe()
        chaves_existentes = set(existentes["chave_dedup"].dropna().astype(str)) if not existentes.empty else set()

        inserir = prep[~prep["chave_dedup"].isin(chaves_existentes)].copy()
        if inserir.empty:
            return 0

        upload_df = pd.DataFrame({
            "chave_dedup": inserir["chave_dedup"].astype(str),
            "data_hora": (inserir["Data"].astype(str) + " " + inserir["Saída da Base"].astype(str)).str.strip(),
            "saida_base": inserir["Saída da Base"].astype(str),
            "chegada_servico": inserir["Chegada Serviço"].astype(str),
            "saida_servico": inserir["Saída Serviço"].astype(str),
            "chegada_base": inserir["Chegada Base"].astype(str),
            "num_os": "",
            "categoria": inserir["Categoria"].astype(str),
            "municipio": inserir["Município"].astype(str),
            "local_estacao": inserir["Unidade / Estação"].astype(str),
            "servico_info": inserir["Serviço / Info"].astype(str),
            "material_utilizado": inserir["Material Utilizado"].astype(str),
            "equipe_responsaveis": inserir["Motorista / Executor"].astype(str),
            "status": "",
            "dt_date": pd.to_datetime(inserir["dt_date"], errors="coerce").dt.date,
        })

        job_config = bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_APPEND)
        job = client.load_table_from_dataframe(upload_df, tabela_fqn.replace("`", ""), job_config=job_config)
        job.result()
        return len(upload_df)
    except Exception as e:
        st.error(f"Erro ao fazer upload no BigQuery: {e}")
        return 0


def _normalizar_nome_campo(rotulo):
    limpo = remover_acentos(rotulo)
    limpo = re.sub(r"\s+", " ", limpo).strip()
    if limpo in ["SAIDA DA BASE", "SAIDA BASE"]:
        return "SAIDA_DA_BASE"
    if limpo in ["CHEGADA SERVICO", "CHEGADA NO SERVICO", "CHEGADA AO SERVICO"]:
        return "CHEGADA_SERVICO"
    if limpo in ["SAIDA SERVICO", "SAIDA DO SERVICO"]:
        return "SAIDA_SERVICO"
    if limpo in ["CHEGADA BASE", "CHEGADA NA BASE", "CHEGADA DA BASE"]:
        return "CHEGADA_BASE"
    return limpo.replace(" ", "_")


def _extrair_campos_rotulados(linhas):
    campos = {}
    chave_atual = None

    for linha in linhas:
        s = linha.strip()
        if not s:
            continue

        s_limpa = re.sub(
            r"^\[?\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\]?\s*(?:-\s*[^:]+:\s*)?",
            "",
            s,
        )

        m = re.match(
            r"^(SS|CIDADE|DATA|ID\s*LOCAL|CLASSIFICA[ÇC][ÃA]O|EXECUTOR|SA[ÍI]DA\s*(?:DA\s*)?BASE|CHEGADA\s*(?:NO\s*|AO\s*)?SERVI[ÇC]O|SA[ÍI]DA\s*(?:DO\s*)?SERVI[ÇC]O|CHEGADA\s*(?:NA\s*|DA\s*)?BASE|VE[ÍI]CULO|MOTORISTA|PASSAGEIROS|DI[ÁA]RIA|KM\s*SA[ÍI]DA|KM\s*CHEGADA|ATIVIDADE|PAROU\s*O\s*SISTEMA|EXECUTADO|MATERIAL\s*UTILIZADO)\s*[:.]\s*(.*)$",
            s_limpa,
            re.IGNORECASE,
        )
        if m:
            chave = _normalizar_nome_campo(m.group(1))
            valor = m.group(2).strip()
            if valor:
                campos[chave] = valor
                chave_atual = chave
            else:
                campos.setdefault(chave, "")
                chave_atual = chave
        elif chave_atual:
            if campos[chave_atual]:
                campos[chave_atual] += f" | {s_limpa}"
            else:
                campos[chave_atual] = s_limpa

    return campos


def _classificar_os(campos, texto_bloco):
    cabecalho_e_bloco = remover_acentos(texto_bloco)
    classificacao_txt = remover_acentos(campos.get("CLASSIFICACAO", ""))
    atividade_txt = remover_acentos(campos.get("ATIVIDADE", ""))

    if "ORDEM SERVICO ADM" in cabecalho_e_bloco or "PARA DESLOCAMENTOS" in cabecalho_e_bloco:
        return "OS ADM (Deslocamento)"

    if "VAZAMENTO" in classificacao_txt or "VAZAMENTO" in atividade_txt or "VAZAMENTO" in cabecalho_e_bloco:
        return "Vazamento"

    return "OS de Serviços"


def parsear_arquivo_txt(conteudo_txt):
    linhas_raw = [l.strip() for l in conteudo_txt.splitlines() if l.strip()]
    blocos = []
    atual = []
    padrao_cabecalho_os = re.compile(r"ORDEM\s+SERVI[ÇC]O\s+(?:ADM|ZML)", re.IGNORECASE)
    padrao_msg_wa = re.compile(r"^\[?\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\]?")

    for linha in linhas_raw:
        if atual and padrao_cabecalho_os.search(linha):
            texto_atual_norm = remover_acentos(" ".join(atual))
            if "ORDEM SERVICO ADM" in texto_atual_norm or "ORDEM SERVICO ZML" in texto_atual_norm:
                blocos.append(atual)
                atual = [linha]
                continue
        if atual and padrao_msg_wa.match(linha):
            texto_atual_norm = remover_acentos(" ".join(atual))
            if "ORDEM SERVICO ADM" in texto_atual_norm or "ORDEM SERVICO ZML" in texto_atual_norm:
                blocos.append(atual)
                atual = [linha]
                continue
        atual.append(linha)

    if atual:
        blocos.append(atual)

    registros = []
    for b in blocos:
        texto_bloco = " ".join(b)
        campos = _extrair_campos_rotulados(b)

        cidades = identificar_cidades_bloco_c(f"{campos.get('CIDADE', '')} {texto_bloco}")
        if not cidades and "BLOCO C" not in remover_acentos(texto_bloco) and "ZML" not in remover_acentos(texto_bloco):
            continue

        dt_obj = extrair_data_dt(campos.get("DATA", ""))
        t_saida_base = extrair_hora_time(campos.get("SAIDA_DA_BASE", ""))
        t_chegada_serv = extrair_hora_time(campos.get("CHEGADA_SERVICO", ""))
        t_saida_serv = extrair_hora_time(campos.get("SAIDA_SERVICO", ""))
        t_chegada_base = extrair_hora_time(campos.get("CHEGADA_BASE", ""))

        categoria = _classificar_os(campos, texto_bloco)
        municipio = ", ".join(cidades) if cidades else (campos.get("CIDADE", "").strip() or "Bloco C")

        unidade = campos.get("ID_LOCAL", "").strip()
        if not unidade:
            unidade = campos.get("CIDADE", "").strip() or (campos.get("VEICULO", "").strip() or "N/I")

        executor = campos.get("EXECUTOR", "").strip()
        motorista = campos.get("MOTORISTA", "").strip()
        if executor and motorista and remover_acentos(executor) != remover_acentos(motorista):
            responsavel = f"{executor} (Mot.: {motorista})"
        else:
            responsavel = executor or motorista or "N/I"

        partes_info = []
        if campos.get("CLASSIFICACAO"):
            partes_info.append(campos["CLASSIFICACAO"].strip())
        if campos.get("ATIVIDADE"):
            partes_info.append(campos["ATIVIDADE"].strip())
        if campos.get("VEICULO"):
            partes_info.append(f"Veículo: {campos['VEICULO'].strip()}")
        if campos.get("PASSAGEIROS"):
            partes_info.append(f"Passag.: {campos['PASSAGEIROS'].strip()}")

        servico = " | ".join(partes_info) if partes_info else texto_bloco[:180]
        material = campos.get("MATERIAL_UTILIZADO", "").strip() or "N/I"

        registros.append({
            "Data": dt_obj.strftime("%d/%m/%Y") if dt_obj else "N/I",
            "Saída da Base": _formatar_hora_col(t_saida_base),
            "Chegada Serviço": _formatar_hora_col(t_chegada_serv),
            "Saída Serviço": _formatar_hora_col(t_saida_serv),
            "Chegada Base": _formatar_hora_col(t_chegada_base),
            "Categoria": categoria,
            "Município": municipio,
            "Unidade / Estação": unidade,
            "Motorista / Executor": responsavel,
            "Serviço / Info": servico,
            "Material Utilizado": material,
            "dt_date": dt_obj,
            "t_saida_base": t_saida_base,
            "t_chegada_servico": t_chegada_serv,
            "t_saida_servico": t_saida_serv,
            "t_chegada_base": t_chegada_base,
        })

    return normalizar_df(pd.DataFrame(registros)), len(blocos)


def _render_cabecalho_com_logo():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    caminho_logo = os.path.join(base_dir, "logo.png")

    if os.path.exists(caminho_logo):
        with open(caminho_logo, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode("utf-8")

        st.markdown(
            f"""
            <div style="display: flex; align-items: center; justify-content: center; gap: 18px; padding: 10px 0 6px 0;">
                <img src="data:image/png;base64,{logo_b64}" alt="Logo CASAL" style="height: 76px; width: auto; object-fit: contain;" />
                <h1 style="margin: 0; font-size: 2.25rem; font-weight: 700; line-height: 1.2;">
                    Ordens de Serviço - ZML / CASAL
                </h1>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <h1 style="text-align: center; margin: 0; padding: 10px 0 6px 0;">
                Ordens de Serviço - ZML / CASAL
            </h1>
            """,
            unsafe_allow_html=True,
        )


# --- TELA ÚNICA ---
_render_cabecalho_com_logo()

col_arq, col_btn = st.columns([3.5, 1.5])
with col_arq:
    arquivo_txt = st.file_uploader("Enviar arquivo .txt para o BigQuery", type=["txt"])
with col_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    upload_clicado = st.button("☁️ Upload para o BigQuery", use_container_width=True)

if upload_clicado:
    if arquivo_txt is None:
        st.warning("Selecione um arquivo .txt antes de fazer o upload para o BigQuery.")
    else:
        conteudo = arquivo_txt.getvalue().decode("utf-8", errors="replace")
        df_txt, total_blocos = parsear_arquivo_txt(conteudo)
        if df_txt.empty:
            st.warning(
                f"Nenhum registro do Bloco C foi identificado no arquivo .txt "
                f"({total_blocos} bloco(s) analisado(s))."
            )
        else:
            with st.spinner("Enviando novos registros para o BigQuery..."):
                salvos = salvar_no_bq(df_txt)
            st.success(
                f"Concluído: {salvos} novo(s) registro(s) salvo(s) no BigQuery "
                f"({len(df_txt)} ficha(s) identificada(s) em {total_blocos} bloco(s))."
            )

st.markdown("---")
st.markdown("### Filtros")

hoje = date.today()
d1, d2 = st.columns(2)
with d1:
    data_ini = st.date_input("Data Inicial", value=hoje - timedelta(days=1), format="DD/MM/YYYY", key="flt_data_ini")
with d2:
    data_fim = st.date_input("Data Final", value=hoje, format="DD/MM/YYYY", key="flt_data_fim")

h1, h2, h3, h4 = st.columns(4)
with h1:
    h_saida_base = st.time_input("Saída da Base", value=time(0, 0), key="flt_h_saida_base")
with h2:
    h_chegada_serv = st.time_input("Chegada Serviço", value=time(0, 0), key="flt_h_chegada_serv")
with h3:
    h_saida_serv = st.time_input("Saída Serviço", value=time(0, 0), key="flt_h_saida_serv")
with h4:
    h_chegada_base = st.time_input("Chegada Base", value=time(0, 0), key="flt_h_chegada_base")

f1, f2, f3 = st.columns([1.5, 1.5, 1.5])
with f1:
    filtro_pessoa = st.text_input("Motorista / Executor", key="flt_pessoa")
with f2:
    filtro_unidade = st.text_input("Unidade / Estação", key="flt_unidade")
with f3:
    filtro_busca = st.text_input("Busca livre (Categoria, Município, Serviço, Material)", key="flt_busca")

datas_padrao = (hoje - timedelta(days=1), hoje)
if "filtro_data_ativo" not in st.session_state:
    st.session_state["filtro_data_ativo"] = False
if (data_ini, data_fim) != datas_padrao:
    st.session_state["filtro_data_ativo"] = True

filtro_data_ativo = st.session_state["filtro_data_ativo"]
periodo_ativo = (filtro_data_ativo, data_ini, data_fim)

if (
    "df_painel" not in st.session_state
    or st.session_state.get("periodo_ativo") != periodo_ativo
    or upload_clicado
):
    with st.spinner("Carregando dados do BigQuery..."):
        if filtro_data_ativo:
            st.session_state["df_painel"] = ler_dados_bq(data_ini, data_fim)
        else:
            st.session_state["df_painel"] = ler_dados_bq()
        st.session_state["periodo_ativo"] = periodo_ativo

df_geral = st.session_state.get("df_painel", pd.DataFrame())

if df_geral is not None and not df_geral.empty:
    df_view = df_geral.copy()

    if filtro_data_ativo:
        df_view = df_view[
            df_view["dt_date"].apply(lambda d: True if pd.isna(d) else (data_ini <= d <= data_fim))
        ]

    for h_alvo, col_t in [
        (h_saida_base, "t_saida_base"),
        (h_chegada_serv, "t_chegada_servico"),
        (h_saida_serv, "t_saida_servico"),
        (h_chegada_base, "t_chegada_base"),
    ]:
        if (h_alvo.hour, h_alvo.minute) != (0, 0):
            df_view = df_view[
                df_view[col_t].apply(
                    lambda t: False if pd.isna(t) else (t.hour, t.minute) == (h_alvo.hour, h_alvo.minute)
                )
            ]

    if filtro_pessoa:
        df_view = df_view[
            df_view["Motorista / Executor"].astype(str).str.contains(filtro_pessoa, case=False, na=False)
        ]

    if filtro_unidade:
        df_view = df_view[
            df_view["Unidade / Estação"].astype(str).str.contains(filtro_unidade, case=False, na=False)
        ]

    if filtro_busca:
        df_view = df_view[
            df_view["Categoria"].astype(str).str.contains(filtro_busca, case=False, na=False)
            | df_view["Município"].astype(str).str.contains(filtro_busca, case=False, na=False)
            | df_view["Serviço / Info"].astype(str).str.contains(filtro_busca, case=False, na=False)
            | df_view["Material Utilizado"].astype(str).str.contains(filtro_busca, case=False, na=False)
        ]

    qtd_servicos = int((df_view["Categoria"] == "OS de Serviços").sum())
    qtd_vazamento = int((df_view["Categoria"] == "Vazamento").sum())
    qtd_adm = int((df_view["Categoria"] == "OS ADM (Deslocamento)").sum())

    st.markdown("---")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("OS de Serviços", qtd_servicos)
    m2.metric("Vazamento", qtd_vazamento)
    m3.metric("OS ADM (Deslocamento)", qtd_adm)
    m4.metric("Total exibido", len(df_view))

    modo_label = "último dia salvo" if not filtro_data_ativo else f"{data_ini.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
    st.caption(f"Mostrando {len(df_view)} de {len(df_geral)} registro(s) carregado(s) ({modo_label}).")
    st.dataframe(df_view[COLUNAS_TABELA], use_container_width=True, hide_index=True, height=600)
else:
    st.info(
        "Nenhum registro encontrado no BigQuery para o critério atual. "
        "Envie um arquivo .txt e clique em 'Upload para o BigQuery'."
    )