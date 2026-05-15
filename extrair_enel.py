import re
import pandas as pd
from pathlib import Path
from datetime import datetime


def normalizar_mes_ref(texto):
    """
    Ex.: 'FEV 2026' -> 'FEV/26'
    """
    texto = str(texto).strip().upper()
    partes = texto.split()
    if len(partes) == 2:
        mes, ano = partes
        return f"{mes}/{ano[-2:]}"
    return ""


def limpar_numero(texto):
    """
    Converte:
    '5.059,80' -> '5059.80'
    '445,000'  -> '445.000'
    """
    texto = str(texto).strip()
    if not texto:
        return ""

    negativo = texto.endswith("-")
    texto = texto.replace("-", "")
    texto = texto.replace(".", "").replace(",", ".")

    if negativo:
        texto = "-" + texto

    return texto


def verificar_atraso_por_mes(mes_ref_texto):
    """
    Regra:
    - mês atual e mês anterior = NÃO
    - dois meses ou mais para trás = SIM

    Exemplos:
    hoje = abril/2026
    MAR 2026 -> NÃO
    FEV 2026 -> SIM
    JAN 2026 -> SIM
    ABR 2026 -> NÃO
    """
    try:
        hoje = datetime.today()
        mes_atual = hoje.month
        ano_atual = hoje.year

        partes = str(mes_ref_texto).strip().upper().split()
        if len(partes) != 2:
            return "Não"

        mes_str, ano_str = partes

        mapa_meses = {
            "JAN": 1,
            "FEV": 2,
            "MAR": 3,
            "ABR": 4,
            "MAI": 5,
            "JUN": 6,
            "JUL": 7,
            "AGO": 8,
            "SET": 9,
            "OUT": 10,
            "NOV": 11,
            "DEZ": 12,
        }

        mes_ref = mapa_meses.get(mes_str)
        ano_ref = int(ano_str)

        if not mes_ref:
            return "Não"

        diff_meses = (ano_atual - ano_ref) * 12 + (mes_atual - mes_ref)

        if diff_meses <= 1:
            return "Não"
        return "Sim"

    except Exception:
        return "Não"


def escolher_kw(registro):
    """
    Prioridade:
    1) achar o consumo cujo mês bate com mes_ref
    2) usar CONSP01/CONS01 se existir
    3) usar CONSUMO_TOTAL
    """
    mes_ref_norm = normalizar_mes_ref(registro.get("MesReferente_cadastroConsumoFatura", ""))

    meses = registro.get("_meses_consumo", {})
    consumos = registro.get("_valores_consumo", {})

    for idx, mes_txt in meses.items():
        if str(mes_txt).strip().upper() == mes_ref_norm:
            valor = consumos.get(idx, "")
            if valor:
                return valor

    for idx in ("01", "1"):
        valor = consumos.get(idx, "")
        if valor:
            return valor

    valor_total = registro.get("_consumo_total", "")
    if valor_total:
        return valor_total

    return ""


def finalizar_registro(registro):
    """
    Fecha um registro e prepara campos finais.
    """
    if not registro:
        return None

    codigo = "".join(
        registro.get("_codigo_barras", {}).get(str(i), "")
        for i in range(1, 5)
    )

    registro["CodigoBarrasCon_cadastroConsumoFatura"] = codigo
    registro["CodBarrasRed_cadastroConsumoFatura"] = codigo[-8:] if codigo else ""

    if not registro.get("Kw_cadastroConsumoFatura"):
        registro["Kw_cadastroConsumoFatura"] = escolher_kw(registro)

    partes_venc = str(registro.get("MesVencimento_cadastroConsumoFatura", "")).split()
    registro["DataCadastro_cadastroConsumoFatura"] = partes_venc[0] if len(partes_venc) >= 1 else ""
    registro["Ano_cadastroConsumoFatura"] = partes_venc[-1] if len(partes_venc) >= 3 else ""

    registro["Atrasadas_cadastroConsumoFatura"] = verificar_atraso_por_mes(
        registro.get("MesReferente_cadastroConsumoFatura", "")
    )

    if "Atrasadas_Acordo" not in registro:
        registro["Atrasadas_Acordo"] = "Não"

    registro.pop("_codigo_barras", None)
    registro.pop("_meses_consumo", None)
    registro.pop("_valores_consumo", None)
    registro.pop("_consumo_total", None)

    return registro


def processar_arquivo(caminho):
    registros = []
    atual = None

    with open(caminho, "r", encoding="latin-1", errors="ignore") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue

            # ========= INSTALAÇÃO =========
            m_inst = re.search(r"DW_CLIENTE-INSTALACAO\s+(\d+)", linha)
            if m_inst:
                instalacao_lida = m_inst.group(1)

                if atual is None:
                    atual = {
                        "_codigo_barras": {},
                        "_meses_consumo": {},
                        "_valores_consumo": {},
                        "_consumo_total": "",
                        "instalacao": instalacao_lida,
                    }
                else:
                    if atual.get("instalacao") != instalacao_lida:
                        reg_final = finalizar_registro(atual)
                        if reg_final:
                            registros.append(reg_final)

                        atual = {
                            "_codigo_barras": {},
                            "_meses_consumo": {},
                            "_valores_consumo": {},
                            "_consumo_total": "",
                            "instalacao": instalacao_lida,
                        }

                continue

            if atual is None:
                continue

            # ========= CAMPOS PRINCIPAIS =========
            m_venc = re.search(r"DW_NOTA_FISCAL-VENCIMENTO\s+(.+)", linha)
            if m_venc and not atual.get("MesVencimento_cadastroConsumoFatura"):
                atual["MesVencimento_cadastroConsumoFatura"] = m_venc.group(1).strip()

            m_ref = re.search(
                r"DW_NOTA_FISCAL-REFERENCIA\s+([A-Z]{3}\s+\d{4}|[A-Za-z]{3}\s+\d{4})",
                linha,
                re.I,
            )
            if m_ref and not atual.get("MesReferente_cadastroConsumoFatura"):
                atual["MesReferente_cadastroConsumoFatura"] = m_ref.group(1).upper()

            m_valor = re.search(r"(?:DW_NOTA_FISCAL-TOTAL_PAGAR|DV_TOTAL_PAGAR)\s+([\d.,-]+)", linha)
            if m_valor and not atual.get("Valor_cadastroConsumoFatura"):
                atual["Valor_cadastroConsumoFatura"] = m_valor.group(1).strip()

            # ========= CÓDIGO DE BARRAS =========
            m_barra = re.search(r"DW_CODBARRAS-ITEM([1-4])\s+(\d+)", linha)
            if m_barra:
                parte = m_barra.group(1)
                valor = m_barra.group(2)
                atual["_codigo_barras"][parte] = valor

            # ========= CONSUMO TOTAL =========
            m_total = re.search(r"DW_NOTA_FISCAL-CONSUMO_TOTAL\s+([\d.,]+)", linha)
            if m_total and not atual.get("_consumo_total"):
                atual["_consumo_total"] = m_total.group(1).strip()

            # ========= MAPA DE MÊS DO CONSUMO =========
            m_mes = re.search(r"DW_CONSUMO-MES(\d{2})\s+([A-Za-z]{3}/\d{2})", linha, re.I)
            if m_mes:
                idx = m_mes.group(1)
                mes_txt = m_mes.group(2).upper()
                atual["_meses_consumo"][idx] = mes_txt

            # ========= VALORES DE CONSUMO =========
            m_consp = re.search(r"DW_CONSUMO-CONSP(\d{2})\s+([\d.,]+)", linha)
            if m_consp:
                idx = m_consp.group(1)
                valor = m_consp.group(2).strip()
                atual["_valores_consumo"][idx] = valor

            m_cons = re.search(r"DW_CONSUMO-CONS(\d{2})\s+([\d.,]+)", linha)
            if m_cons:
                idx = m_cons.group(1)
                valor = m_cons.group(2).strip()
                atual["_valores_consumo"][idx] = valor

    if atual:
        reg_final = finalizar_registro(atual)
        if reg_final:
            registros.append(reg_final)

    df = pd.DataFrame(registros)

    colunas_esperadas = [
        "CodigoBarrasCon_cadastroConsumoFatura",
        "Valor_cadastroConsumoFatura",
        "Kw_cadastroConsumoFatura",
        "MesVencimento_cadastroConsumoFatura",
        "MesReferente_cadastroConsumoFatura",
        "DataCadastro_cadastroConsumoFatura",
        "Ano_cadastroConsumoFatura",
        "CodBarrasRed_cadastroConsumoFatura",
        "Atrasadas_cadastroConsumoFatura",
        "Atrasadas_Acordo",
    ]

    for col in colunas_esperadas:
        if col not in df.columns:
            df[col] = ""

    df = df.drop_duplicates(
        subset=[
            "CodigoBarrasCon_cadastroConsumoFatura",
            "MesReferente_cadastroConsumoFatura",
            "Valor_cadastroConsumoFatura",
        ],
        keep="first"
    )

    return df[colunas_esperadas]


# ========= PROCESSAMENTO DE TODOS OS ARQUIVOS =========
pasta = Path("arquivos")
todos = []

for arquivo in pasta.iterdir():
    if arquivo.is_file():
        try:
            df = processar_arquivo(arquivo)
            if not df.empty:
                todos.append(df)
                print(f"OK: {arquivo.name}")
        except Exception as e:
            print(f"Erro em {arquivo.name}: {e}")

if todos:
    resultado = pd.concat(todos, ignore_index=True)

    resultado["Valor_cadastroConsumoFatura"] = pd.to_numeric(
        resultado["Valor_cadastroConsumoFatura"].apply(limpar_numero),
        errors="coerce"
    )

    resultado["Kw_cadastroConsumoFatura"] = pd.to_numeric(
        resultado["Kw_cadastroConsumoFatura"].apply(limpar_numero),
        errors="coerce"
    )

    resultado["Ano_cadastroConsumoFatura"] = pd.to_numeric(
        resultado["Ano_cadastroConsumoFatura"],
        errors="coerce"
    )

    resultado.to_excel("faturas_enel.xlsx", index=False)
    print("Excel gerado com sucesso!")
else:
    print("Nenhum dado encontrado nos arquivos.")