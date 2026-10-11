#!/usr/bin/python3
# ==================== PROGRAM ==============================
# Program: gerar_graficos_completo
# Description: Valida e visualiza as estatisticas calculadas pelo firmware
#              Arduino (SensorArduino). O script faz duas coisas:
#
#              1) VALIDACAO: recalcula em Python, a partir das leituras
#                 brutas gravadas no CSV, exatamente o que o firmware
#                 calculou (janela circular de 8 amostras, variancia
#                 amostral, quartis por indice, criterio de Tukey,
#                 Pearson em blocos de 12 amostras) e compara com os
#                 valores gravados.
#              2) VISUALIZACAO: gera graficos e relatorios por variavel e
#                 por par de variaveis, usando as colunas do firmware e
#                 analises globais complementares.
#
# Uso: python3 gerar_graficos_completo.py <arquivo.csv>
#
# Estrutura de saida (uma pasta por analise, cada uma com relatorio.md):
#   resultados/
#     relatorio_geral.md
#     01_validacao_firmware/      graficos, divergencias.csv, relatorio.md
#     02_UmidadeAr_estatisticas/  grafico.png, distribuicao.png
#     03_Temp_estatisticas/       grafico.png, distribuicao.png
#     04_USolo_estatisticas/      grafico.png, distribuicao.png
#     05_desvio_padrao/
#     06_correlacao_firmware/
#     07_correlacao_global/
#     08_par_Temp_x_UmidadeAr/    dispersao, janelas, correlacao defasada
#     09_par_Temp_x_USolo/
#     10_par_UmidadeAr_x_USolo/
# ===========================================================

import os
import sys

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

try:
    from scipy import stats as sps
except ImportError:  # p-valores ficam indisponiveis sem SciPy
    sps = None

# ----------------------------------------------------------
# PARAMETROS (devem coincidir com o firmware)
# ----------------------------------------------------------
SAMPLE_SIZE = 8            # SAMPLE_SIZE do firmware (janela das estatisticas)
CORR_BUFFER_SIZE = 12      # CORR_BUFFER_SIZE do firmware (bloco da correlacao)
CORR_THRESHOLD = 0.5       # CORR_THRESHOLD do firmware
IQR_FACTOR = 1.5           # IQR_FACTOR do firmware (criterio de Tukey)

TOL_ESTAT = 0.006          # tolerancia: o firmware grava 2 casas decimais
TOL_CORR = 0.001           # tolerancia: o firmware grava 4 casas decimais
LAG_MAX = 24               # defasagem maxima (em amostras) na correlacao defasada
ALPHA = 0.05               # nivel de significancia dos testes

PASTA_SAIDA = "resultados"
MAX_OUTLIERS_TABELA = 20   # outliers listados na tabela de cada relatorio
MAX_DIVERGENCIAS = 1000    # divergencias gravadas em divergencias.csv

# O cabecalho do firmware repete nomes (MedUAr, MedT, MedUS aparecem
# duas vezes: media e mediana). Renomeamos por posicao.
COLUNAS = [
    "Data", "Hora",
    "UmidadeAr", "MediaUAr", "DesvUAr", "Q1UAr", "MedianaUAr", "Q3UAr", "OutUAr",
    "Temp", "MediaT", "DesvT", "Q1T", "MedianaT", "Q3T", "OutT",
    "USolo", "MediaUS", "DesvUS", "Q1US", "MedianaUS", "Q3US", "OutUS",
    "Corr1", "Corr2", "Corr3",
]

VARIAVEIS = {
    "UmidadeAr": {"rotulo": "Umidade do Ar (%)", "suf": "UAr", "cor": "tab:blue"},
    "Temp": {"rotulo": "Temperatura (°C)", "suf": "T", "cor": "tab:red"},
    "USolo": {"rotulo": "Umidade do Solo (%)", "suf": "US", "cor": "tab:green"},
}

# Ordem no firmware: Corr1 = Temp x UAr, Corr2 = Temp x USolo, Corr3 = UAr x USolo
CORRELACOES = {
    "Corr1": ("Temperatura", "Umidade do Ar"),
    "Corr2": ("Temperatura", "Umidade do Solo"),
    "Corr3": ("Umidade do Ar", "Umidade do Solo"),
}

# Colunas brutas de cada par (mesma ordem de CORRELACOES)
PARES = {
    "Corr1": ("Temp", "UmidadeAr"),
    "Corr2": ("Temp", "USolo"),
    "Corr3": ("UmidadeAr", "USolo"),
}

# Estatisticas da janela comparadas na validacao: (chave, prefixo da coluna, rotulo)
ESTATS = [
    ("media", "Media", "Média"),
    ("desv", "Desv", "Desvio padrão"),
    ("q1", "Q1", "Q1"),
    ("med", "Mediana", "Mediana"),
    ("q3", "Q3", "Q3"),
]

# ----------------------------------------------------------
# ENTRADA E PREPARO DOS DADOS
# ----------------------------------------------------------
if len(sys.argv) < 2:
    print("Uso: python3 gerar_graficos_completo.py <arquivo.csv>")
    sys.exit(1)

ARQUIVO_CSV = sys.argv[1]
if not os.path.isfile(ARQUIVO_CSV):
    print(f"Arquivo não encontrado: {ARQUIVO_CSV}")
    sys.exit(1)

try:
    df = pd.read_csv(ARQUIVO_CSV, comment="#")  # ignora as linhas de comentario
except Exception as e:
    print(f"Erro ao ler o CSV: {e}")
    sys.exit(1)

if df.shape[1] != len(COLUNAS):
    print(f"O CSV tem {df.shape[1]} colunas; esperado: {len(COLUNAS)}.")
    sys.exit(1)

df.columns = COLUNAS

for c in COLUNAS[2:]:
    if c.startswith("Out"):
        df[c] = df[c].astype(str).str.strip().str.upper()
    else:
        df[c] = pd.to_numeric(df[c], errors="coerce")

df["DataHoraOriginal"] = pd.to_datetime(df["Data"].astype(str) + " " + df["Hora"].astype(str),
                                        errors="coerce")
df = df.dropna(subset=["DataHoraOriginal"]).reset_index(drop=True)
if df.empty:
    print("Nenhum registro com data e hora válidas.")
    sys.exit(1)

# A placa nao tem RTC: a hora vem de millis() e volta ao inicio a cada reinicio.
# Um retrocesso (ou repeticao) de horario indica reinicio da placa. Cada
# reinicio zera os buffers do firmware (voltam a conter zeros).
dt = df["DataHoraOriginal"].diff().dt.total_seconds()
df["Reinicio"] = (dt <= 0).fillna(False)
INTERVALO_S = dt[dt > 0].median()
df["Seg"] = df["Reinicio"].cumsum()                    # segmento de operacao continua
df["Pos"] = df.groupby("Seg").cumcount()               # posicao da linha no segmento

# Linha do tempo reconstruida: nos reinicios, assume-se o intervalo tipico
dt_adj = dt.where(~df["Reinicio"], INTERVALO_S).fillna(0)
df["DataHora"] = df["DataHoraOriginal"].iloc[0] + pd.to_timedelta(dt_adj.cumsum(), unit="s")

N_REINICIOS = int(df["Reinicio"].sum())
N_SEGMENTOS = int(df["Seg"].nunique())
N_REPETIDOS = int(df["DataHoraOriginal"].duplicated().sum())
N_LACUNAS = int((dt > 1.5 * INTERVALO_S).sum()) if not np.isnan(INTERVALO_S) else 0

df_bruto = df.copy()          # todas as linhas, usadas na validacao
total_bruto = len(df_bruto)

# Descarta o aquecimento: as primeiras SAMPLE_SIZE leituras de cada segmento
# (o buffer do firmware ainda contem zeros nesse trecho)
df = df[df["Pos"] >= SAMPLE_SIZE].reset_index(drop=True)
if df.empty:
    print("Dados insuficientes após descartar o período de aquecimento.")
    sys.exit(1)
N_AQUECIMENTO = total_bruto - len(df)

df["Horas"] = (df["DataHora"] - df["DataHora"].min()).dt.total_seconds() / 3600

os.makedirs(PASTA_SAIDA, exist_ok=True)

marcador = "o" if len(df) < 200 else None


# ----------------------------------------------------------
# FUNCOES AUXILIARES
# ----------------------------------------------------------
def formatar_eixo_tempo(ax):
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=12))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
    ax.grid(True, linestyle="--", alpha=0.5)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")


def nova_pasta(ordem, nome):
    """Cria e retorna a pasta dedicada a uma analise."""
    caminho = os.path.join(PASTA_SAIDA, f"{ordem:02d}_{nome}")
    os.makedirs(caminho, exist_ok=True)
    return caminho


def salvar_relatorio(pasta, linhas):
    with open(os.path.join(pasta, "relatorio.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")


def tabela_md(cabecalho, linhas):
    out = ["| " + " | ".join(cabecalho) + " |",
           "|" + "|".join(["---"] * len(cabecalho)) + "|"]
    for l in linhas:
        out.append("| " + " | ".join(str(c) for c in l) + " |")
    return out


def fn(x, d=3):
    """Formata numero tratando NaN e None."""
    if x is None:
        return "-"
    x = float(x)
    return "-" if np.isnan(x) else f"{x:.{d}f}"


def fmt_p(p):
    if p is None or np.isnan(p):
        return "n/d (SciPy ausente)"
    return "< 0,001" if p < 0.001 else f"{p:.4f}".replace(".", ",")


def classificar_correlacao(r):
    if r is None or np.isnan(r):
        return "indefinida"
    a = abs(r)
    if a < 0.3:
        forca = "fraca ou desprezível"
    elif a < 0.5:
        forca = "fraca a moderada"
    elif a < 0.7:
        forca = "moderada"
    elif a < 0.9:
        forca = "forte"
    else:
        forca = "muito forte"
    sentido = "positiva" if r > 0 else "negativa" if r < 0 else "nula"
    return f"{forca} ({sentido})"


def cabecalho_relatorio(titulo, imagens=None):
    imagens = imagens or [("Gráfico", "grafico.png")]
    linhas = [
        f"# {titulo}",
        "",
        f"- **Arquivo de origem:** {os.path.basename(ARQUIVO_CSV)}",
        f"- **Período analisado:** {df['DataHora'].min()} a {df['DataHora'].max()} "
        "(linha do tempo reconstruída)" if N_REINICIOS else
        f"- **Período analisado:** {df['DataHora'].min()} a {df['DataHora'].max()}",
        f"- **Registros analisados:** {len(df)} (de {total_bruto}; descartadas "
        f"{N_AQUECIMENTO} leituras de aquecimento, as {SAMPLE_SIZE} primeiras de cada um "
        f"dos {N_SEGMENTOS} segmento(s) de operação contínua)",
        f"- **Reinícios da placa detectados:** {N_REINICIOS}",
        f"- **Intervalo típico entre amostras:** {fn(INTERVALO_S, 0)} s",
        "",
    ]
    for legenda, arq in imagens:
        linhas += [f"![{legenda}]({arq})", ""]
    return linhas


def pearson(a, b):
    """Retorna (r, p) de Pearson; p e None se SciPy nao estiver disponivel."""
    d = pd.concat([a, b], axis=1).dropna()
    if len(d) < 3 or d.iloc[:, 0].std() == 0 or d.iloc[:, 1].std() == 0:
        return float("nan"), None
    if sps is not None:
        r, p = sps.pearsonr(d.iloc[:, 0], d.iloc[:, 1])
        return float(r), float(p)
    return float(d.iloc[:, 0].corr(d.iloc[:, 1])), None


def spearman(a, b):
    d = pd.concat([a, b], axis=1).dropna()
    if len(d) < 3 or d.iloc[:, 0].std() == 0 or d.iloc[:, 1].std() == 0:
        return float("nan"), None
    if sps is not None:
        r, p = sps.spearmanr(d.iloc[:, 0], d.iloc[:, 1])
        return float(r), float(p)
    return float(d.iloc[:, 0].corr(d.iloc[:, 1], method="spearman")), None


def correlacoes_atualizadas():
    """Retorna, por coluna Corr, apenas as linhas em que o firmware recalculou
    o coeficiente: ao completar cada bloco de CORR_BUFFER_SIZE amostras de um
    segmento (nas demais linhas o valor apenas se repete)."""
    atualiza = ((df["Pos"] + 1) % CORR_BUFFER_SIZE == 0)
    return {c: df.loc[atualiza, ["DataHora", c]].dropna(subset=[c]) for c in CORRELACOES}


# ----------------------------------------------------------
# REPRODUCAO DO CALCULO DO FIRMWARE (aritmetica float de 32 bits)
# ----------------------------------------------------------
def emular_estatisticas(x):
    """Reproduz calcularEstatisticas() do firmware para uma sequencia de
    leituras de um segmento (desde o reinicio). O buffer circular comeca
    com zeros, a leitura atual entra no buffer ANTES do calculo, a variancia
    e amostral (n-1) e os quartis sao elementos do vetor ordenado nas posicoes
    N/4, N/2 e 3N/4 (sem interpolacao). Tambem devolve o desvio padrao
    calculado em 64 bits, como referencia numerica."""
    f = np.float32
    n = len(x)
    xs = np.asarray(x, dtype=np.float32)
    buf = np.zeros(SAMPLE_SIZE, dtype=np.float32)
    r = {k: np.full(n, np.nan) for k in ("media", "desv", "q1", "med", "q3", "desv64")}
    r["out"] = np.zeros(n, dtype=bool)
    with np.errstate(all="ignore"):
        for j in range(n):
            buf[j % SAMPLE_SIZE] = xs[j]
            soma = f(0)
            soma_q = f(0)
            for v in buf:
                soma = f(soma + v)
                soma_q = f(soma_q + f(v * v))
            media = f(soma / f(SAMPLE_SIZE))
            var = f(f(soma_q - f(f(SAMPLE_SIZE) * f(media * media))) / f(SAMPLE_SIZE - 1))
            desv = f(np.sqrt(var))
            ordenado = np.sort(buf)
            q1 = ordenado[SAMPLE_SIZE // 4]
            med = ordenado[SAMPLE_SIZE // 2]
            q3 = ordenado[(3 * SAMPLE_SIZE) // 4]
            iqr = f(q3 - q1)
            inf = f(q1 - f(f(IQR_FACTOR) * iqr))
            sup = f(q3 + f(f(IQR_FACTOR) * iqr))
            r["media"][j] = media
            r["desv"][j] = desv
            r["q1"][j] = q1
            r["med"][j] = med
            r["q3"][j] = q3
            r["out"][j] = bool(xs[j] < inf or xs[j] > sup)
            r["desv64"][j] = float(np.std(buf.astype(np.float64), ddof=1))
    return r


def pearson_firmware(x, y):
    """Reproduz calcularPearson() do firmware (float de 32 bits)."""
    f = np.float32
    n = f(len(x))
    sx = sy = sxy = sx2 = sy2 = f(0)
    with np.errstate(all="ignore"):
        for a, c in zip(x, y):
            a = f(a)
            c = f(c)
            sx = f(sx + a)
            sy = f(sy + c)
            sxy = f(sxy + f(a * c))
            sx2 = f(sx2 + f(a * a))
            sy2 = f(sy2 + f(c * c))
        num = f(f(n * sxy) - f(sx * sy))
        den = f(np.sqrt(f(f(f(n * sx2) - f(sx * sx)) * f(f(n * sy2) - f(sy * sy)))))
        if den != 0:  # NaN != 0 e verdadeiro, como no C
            return float(f(num / den))
    return 0.0


def pearson_referencia(x, y):
    """Pearson em 64 bits; 0 quando uma das series e constante (como o firmware)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.std() == 0 or y.std() == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


# ----------------------------------------------------------
# ANALISE 1: VALIDACAO DO CALCULO EMBARCADO
# ----------------------------------------------------------
def validacao_firmware(ordem):
    pasta = nova_pasta(ordem, "validacao_firmware")
    b = df_bruto
    n = len(b)
    diverg = []
    res_var = {}

    # --- estatisticas da janela ---
    for col, cfg in VARIAVEIS.items():
        suf = cfg["suf"]
        em = {k: np.full(n, np.nan) for k in ("media", "desv", "q1", "med", "q3", "desv64")}
        em["out"] = np.zeros(n, dtype=bool)
        for _, g in b.groupby("Seg"):
            r = emular_estatisticas(g[col].to_numpy(dtype=float))
            idx = g.index.to_numpy()
            for k in em:
                em[k][idx] = r[k]

        res = {}
        for k, pref, rot in ESTATS:
            csvv = b[f"{pref}{suf}"].to_numpy(dtype=float)
            diff = np.abs(csvv - em[k])
            ok = (diff <= TOL_ESTAT) | (np.isnan(csvv) & np.isnan(em[k]))
            fin = diff[np.isfinite(diff)]
            res[k] = {"ok": 100 * ok.mean(), "max": float(fin.max()) if len(fin) else float("nan"),
                      "n_div": int((~ok).sum())}
            for i in np.where(~ok)[0][:200]:
                diverg.append({"Linha": i + 1, "DataHoraOriginal": b.loc[i, "DataHoraOriginal"],
                               "Variavel": cfg["rotulo"], "Estatistica": rot,
                               "Firmware": csvv[i], "Recalculo": em[k][i]})

        csv_out = (b[f"Out{suf}"] == "SIM").to_numpy()
        ok_out = csv_out == em["out"]
        res["out"] = {"ok": 100 * ok_out.mean(), "n_div": int((~ok_out).sum())}
        for i in np.where(~ok_out)[0][:200]:
            diverg.append({"Linha": i + 1, "DataHoraOriginal": b.loc[i, "DataHoraOriginal"],
                           "Variavel": cfg["rotulo"], "Estatistica": "Outlier",
                           "Firmware": "SIM" if csv_out[i] else "NAO",
                           "Recalculo": "SIM" if em["out"][i] else "NAO"})

        csv_d = b[f"Desv{suf}"].to_numpy(dtype=float)
        err64 = np.abs(csv_d - em["desv64"])
        fin64 = err64[np.isfinite(err64)]
        res["err64_medio"] = float(fin64.mean()) if len(fin64) else float("nan")
        res["err64_max"] = float(fin64.max()) if len(fin64) else float("nan")
        res["n_nan_desv"] = int(np.isnan(csv_d).sum())

        aquec = (b["Pos"] < SAMPLE_SIZE).to_numpy()
        res["out_total"] = int(csv_out.sum())
        res["out_aquec"] = int((csv_out & aquec).sum())
        res_var[col] = res

    # --- correlacao de Pearson (blocos consecutivos de CORR_BUFFER_SIZE) ---
    res_corr = {}
    graf_corr = {}
    for c, (ca, cb) in PARES.items():
        csvc = b[c].to_numpy(dtype=float)
        esperado = np.zeros(n)
        emu = []
        ref = []
        csv_upd = []
        for _, g in b.groupby("Seg"):
            idx = g.index.to_numpy()
            xa = g[ca].to_numpy(dtype=float)
            xb = g[cb].to_numpy(dtype=float)
            atual = 0.0
            for j in range(len(g)):
                if (j + 1) % CORR_BUFFER_SIZE == 0:
                    sl = slice(j - CORR_BUFFER_SIZE + 1, j + 1)
                    atual = pearson_firmware(xa[sl], xb[sl])
                    emu.append(atual)
                    ref.append(pearson_referencia(xa[sl], xb[sl]))
                    csv_upd.append(csvc[idx[j]])
                esperado[idx[j]] = atual
        emu = np.array(emu, dtype=float)
        ref = np.array(ref, dtype=float)
        csv_upd = np.array(csv_upd, dtype=float)

        d_emu = np.abs(csv_upd - emu)
        ok_upd = (d_emu <= TOL_CORR) | (np.isnan(csv_upd) & np.isnan(emu))
        d_ref = np.abs(csv_upd - ref)
        d_all = np.abs(csvc - esperado)
        ok_all = (d_all <= TOL_CORR) | (np.isnan(csvc) & np.isnan(esperado))
        fe = d_emu[np.isfinite(d_emu)]
        fr = d_ref[np.isfinite(d_ref)]
        res_corr[c] = {
            "blocos": len(emu),
            "ok_blocos": 100 * ok_upd.mean() if len(emu) else float("nan"),
            "ok_coluna": 100 * ok_all.mean(),
            "max_emu": float(fe.max()) if len(fe) else float("nan"),
            "max_ref": float(fr.max()) if len(fr) else float("nan"),
            "n_nan": int(np.isnan(csv_upd).sum()),
        }
        graf_corr[c] = (ref, csv_upd)
        for i in np.where(~ok_upd)[0][:100]:
            diverg.append({"Linha": "-", "DataHoraOriginal": "-",
                           "Variavel": f"{CORRELACOES[c][0]} x {CORRELACOES[c][1]}",
                           "Estatistica": f"Pearson (bloco {i + 1})",
                           "Firmware": csv_upd[i], "Recalculo": emu[i]})

    if diverg:
        pd.DataFrame(diverg).head(MAX_DIVERGENCIAS).to_csv(
            os.path.join(pasta, "divergencias.csv"), index=False)

    # --- grafico 1: concordancia das estatisticas ---
    rotulos = [rot for _, _, rot in ESTATS] + ["Outlier"]
    chaves = [k for k, _, _ in ESTATS] + ["out"]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    larg = 0.27
    xs = np.arange(len(rotulos))
    for i, (col, cfg) in enumerate(VARIAVEIS.items()):
        vals = [res_var[col][k]["ok"] for k in chaves]
        ax.bar(xs + (i - 1) * larg, vals, larg, color=cfg["cor"], label=cfg["rotulo"])
    ax.set_xticks(xs)
    ax.set_xticklabels(rotulos)
    ax.set_ylim(0, 105)
    ax.axhline(100, color="black", lw=0.6)
    ax.set_ylabel("Linhas concordantes (%)")
    ax.set_title("Concordância entre o CSV gravado pelo firmware e o recálculo em Python")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(True, axis="y", linestyle="--", alpha=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, "concordancia_estatisticas.png"), dpi=300)
    plt.close(fig)

    # --- grafico 2: correlacao gravada x recalculada ---
    tem_corr = any(len(v[0]) for v in graf_corr.values())
    if tem_corr:
        fig, ax = plt.subplots(figsize=(6.5, 6))
        for c, (ref, csv_upd) in graf_corr.items():
            if len(ref):
                ax.scatter(ref, csv_upd, s=22, alpha=0.7,
                           label=f"{CORRELACOES[c][0]} x {CORRELACOES[c][1]}")
        ax.plot([-1, 1], [-1, 1], color="black", lw=0.8, ls="--", label="Concordância perfeita")
        ax.set_xlim(-1.05, 1.05)
        ax.set_ylim(-1.05, 1.05)
        ax.set_xlabel("Pearson recalculado em Python (64 bits)")
        ax.set_ylabel("Pearson gravado pelo firmware")
        ax.set_title(f"Correlação por bloco de {CORR_BUFFER_SIZE} amostras")
        ax.legend(fontsize=8)
        ax.grid(True, linestyle="--", alpha=0.5)
        fig.tight_layout()
        fig.savefig(os.path.join(pasta, "correlacao_firmware_vs_python.png"), dpi=300)
        plt.close(fig)

    # --- grafico 3: integridade temporal ---
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(b.index + 1, b["DataHoraOriginal"], ".", ms=2, color="tab:blue",
            label="Marca de tempo gravada")
    for k, i in enumerate(b.index[b["Reinicio"]]):
        ax.axvline(i + 1, color="red", lw=0.8, alpha=0.7,
                   label="Reinício detectado" if k == 0 else None)
    ax.set_xlabel("Número da linha no CSV")
    ax.set_ylabel("Data e hora gravadas")
    ax.yaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
    ax.set_title("Integridade temporal: a hora é derivada de millis() e volta ao início a cada reinício")
    ax.legend(fontsize=8)
    ax.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, "integridade_temporal.png"), dpi=300)
    plt.close(fig)

    # --- relatorio ---
    imagens = [("Concordância das estatísticas", "concordancia_estatisticas.png")]
    if tem_corr:
        imagens.append(("Correlação gravada x recalculada", "correlacao_firmware_vs_python.png"))
    imagens.append(("Integridade temporal", "integridade_temporal.png"))
    r = cabecalho_relatorio("Relatório: validação do cálculo embarcado", imagens)

    q1i, medi, q3i = SAMPLE_SIZE // 4, SAMPLE_SIZE // 2, (3 * SAMPLE_SIZE) // 4
    r += [
        "## 1. Objetivo e método", "",
        "A validação verifica se os valores gravados no CSV correspondem ao que o algoritmo "
        "do firmware deveria produzir. O Python recalcula cada estatística a partir das "
        "**leituras brutas gravadas no próprio CSV**, reproduzindo a aritmética de 32 bits "
        "(float) do ATmega328P e, como referência numérica, a aritmética de 64 bits. "
        "As características do algoritmo embarcado que foram reproduzidas são:", "",
        f"- **Janela das estatísticas:** buffer circular de {SAMPLE_SIZE} amostras, que começa "
        "preenchido com zeros e é reiniciado a cada reinício da placa.",
        "- **Leitura atual na janela:** a leitura entra no buffer antes do cálculo, de modo que "
        "o critério de outlier é aplicado a uma janela que já contém a própria leitura.",
        "- **Variância:** amostral (divisor n-1), calculada pela fórmula das somas "
        "(soma dos quadrados menos n vezes a média ao quadrado).",
        f"- **Quartis:** elementos do vetor ordenado nas posições {q1i} (Q1), {medi} (mediana) "
        f"e {q3i} (Q3), contadas a partir de zero, sem interpolação. Para janela de tamanho par, "
        "a mediana é o elemento superior, e não a média dos dois centrais.",
        f"- **Outlier (critério de Tukey):** leitura abaixo de Q1 - {IQR_FACTOR} x IQR "
        f"ou acima de Q3 + {IQR_FACTOR} x IQR.",
        f"- **Pearson:** calculado sobre blocos consecutivos e sem sobreposição de "
        f"{CORR_BUFFER_SIZE} amostras, ao completar cada bloco, e mantido nas linhas seguintes.",
        "",
        "## 2. Integridade temporal", "",
        "A placa não possui relógio de tempo real (RTC): data e hora são calculadas a partir de "
        "millis() somado a um horário inicial fixo no código. Em cada reinício, a contagem volta "
        "ao horário inicial, o que produz horários repetidos ou retrocessos.", "",
    ]
    r += tabela_md(["Indicador", "Valor"], [
        ["Linhas no arquivo", total_bruto],
        ["Reinícios detectados (retrocesso ou repetição de horário)", N_REINICIOS],
        ["Segmentos de operação contínua", N_SEGMENTOS],
        ["Horários repetidos", N_REPETIDOS],
        ["Lacunas maiores que 1,5 vez o intervalo típico", N_LACUNAS],
        ["Intervalo típico entre amostras", f"{fn(INTERVALO_S, 0)} s"],
        ["Primeira marca de tempo gravada", df_bruto["DataHoraOriginal"].iloc[0]],
        ["Última marca de tempo gravada", df_bruto["DataHoraOriginal"].iloc[-1]],
        ["Duração com linha do tempo reconstruída",
         f"{(df_bruto['DataHora'].max() - df_bruto['DataHora'].min()).total_seconds() / 3600:.1f} h"],
    ])
    r += ["", "Segmentos de operação contínua:", ""]
    linhas = []
    for s, g in df_bruto.groupby("Seg"):
        linhas.append([int(s) + 1, len(g), g["DataHoraOriginal"].iloc[0],
                       g["DataHoraOriginal"].iloc[-1]])
    r += tabela_md(["Segmento", "Linhas", "Primeira marca", "Última marca"], linhas)
    if N_LACUNAS:
        r += ["", "As lacunas costumam indicar leituras inválidas do DHT11 (o firmware descarta "
              "a amostra inteira, sem registrar o erro) ou interrupções de energia."]

    r += ["", "## 3. Concordância das estatísticas da janela", "",
          f"Uma linha é considerada concordante quando o valor gravado difere do recalculado "
          f"em até {TOL_ESTAT} (o firmware grava duas casas decimais). Para o outlier, "
          "a marcação deve ser idêntica.", ""]
    linhas = []
    for col, cfg in VARIAVEIS.items():
        for k, _, rot in ESTATS:
            v = res_var[col][k]
            linhas.append([cfg["rotulo"], rot, f"{v['ok']:.2f}%", fn(v["max"], 4), v["n_div"]])
        v = res_var[col]["out"]
        linhas.append([cfg["rotulo"], "Outlier (SIM/NAO)", f"{v['ok']:.2f}%", "-", v["n_div"]])
    r += tabela_md(["Variável", "Estatística", "Linhas concordantes", "Erro máximo absoluto",
                    "Divergências"], linhas)

    r += ["", "## 4. Erro numérico do desvio padrão (32 bits contra 64 bits)", "",
          "O firmware calcula a variância pela fórmula das somas em precisão simples. Quando "
          "a variância é pequena em relação ao valor médio, o cancelamento numérico pode "
          "distorcer o resultado ou até gerar valores negativos, cuja raiz resulta em NaN.", ""]
    linhas = []
    for col, cfg in VARIAVEIS.items():
        v = res_var[col]
        linhas.append([cfg["rotulo"], fn(v["err64_medio"], 4), fn(v["err64_max"], 4),
                       v["n_nan_desv"]])
    r += tabela_md(["Variável", "Erro médio do desvio", "Erro máximo do desvio",
                    "Linhas com desvio NaN"], linhas)

    r += ["", "## 5. Outliers durante o aquecimento do buffer", "",
          f"Nas primeiras {SAMPLE_SIZE} leituras de cada segmento, o buffer ainda contém zeros e "
          "as estatísticas não representam a variável medida. Marcações de outlier nesse trecho "
          "são artefato do algoritmo, e não anomalias dos sensores.", ""]
    linhas = []
    for col, cfg in VARIAVEIS.items():
        v = res_var[col]
        pct = 100 * v["out_aquec"] / v["out_total"] if v["out_total"] else 0.0
        linhas.append([cfg["rotulo"], v["out_total"], v["out_aquec"], f"{pct:.1f}%",
                       v["out_total"] - v["out_aquec"]])
    r += tabela_md(["Variável", "Outliers no arquivo", "No aquecimento",
                    "Parcela no aquecimento", "Outliers após descartar o aquecimento"], linhas)

    r += ["", f"## 6. Correlação de Pearson (blocos de {CORR_BUFFER_SIZE} amostras)", "",
          f"O valor gravado em cada bloco é comparado ao recálculo em 32 bits (tolerância de "
          f"{TOL_CORR}) e ao recálculo em 64 bits. Também se verifica se o valor é mantido "
          "corretamente nas linhas entre dois blocos.", ""]
    linhas = []
    for c, (v1, v2) in CORRELACOES.items():
        v = res_corr[c]
        linhas.append([f"{v1} x {v2}", v["blocos"], f"{fn(v['ok_blocos'], 2)}%",
                       fn(v["max_emu"], 4), fn(v["max_ref"], 4),
                       f"{v['ok_coluna']:.2f}%", v["n_nan"]])
    r += tabela_md(["Par", "Blocos", "Blocos concordantes (32 bits)", "Erro máx. (32 bits)",
                    "Erro máx. (64 bits)", "Coluna concordante (todas as linhas)",
                    "Blocos NaN"], linhas)

    # interpretacao automatica
    minimo = min([res_var[col][k]["ok"] for col in VARIAVEIS for k in chaves]
                 + [res_corr[c]["ok_blocos"] for c in PARES if res_corr[c]["blocos"]]
                 or [float("nan")])
    n_div_tot = len(diverg)
    r += ["", "## 7. Interpretação", ""]
    if n_div_tot == 0:
        r.append("- Os valores gravados são compatíveis com o algoritmo descrito: o recálculo "
                 "independente reproduz todas as estatísticas, os indicadores de outlier e as "
                 "correlações, sem divergências. Isso também indica que a versão do firmware "
                 "utilizada na coleta corresponde ao código analisado.")
    elif not np.isnan(minimo) and minimo >= 99.5:
        r.append(f"- O recálculo reproduz quase todos os valores (concordância mínima de "
                 f"{fn(minimo, 2)}%), com {n_div_tot} divergência(s) pontual(is). Verifique "
                 "`divergencias.csv`: podem indicar corrupção de linha no cartão SD, "
                 "reinício durante a gravação ou diferença de arredondamento.")
    else:
        r.append(f"- A concordância mínima foi de {fn(minimo, 2)}%. Há divergências entre o CSV "
                 "e o algoritmo descrito. Verifique se a versão do firmware usada na coleta "
                 "corresponde ao código analisado (constantes, tamanhos de janela, fórmulas) "
                 "e consulte `divergencias.csv`.")
    if N_REINICIOS:
        r.append(f"- Foram detectados {N_REINICIOS} reinício(s). Cada reinício zera os buffers e "
                 "reinicia a contagem de horário, de modo que a análise descarta o aquecimento "
                 "de cada segmento e usa uma linha do tempo reconstruída.")
    else:
        r.append("- Não foram detectados reinícios: a operação foi contínua do início ao fim, "
                 "segundo as marcas de tempo gravadas.")
    total_aq = sum(res_var[col]["out_aquec"] for col in VARIAVEIS)
    if total_aq:
        r.append(f"- {total_aq} marcação(ões) de outlier ocorreram durante o aquecimento do buffer "
                 "e devem ser desconsideradas na interpretação.")
    nan_tot = sum(res_var[col]["n_nan_desv"] for col in VARIAVEIS)
    if nan_tot:
        r.append(f"- Há {nan_tot} valor(es) NaN de desvio padrão, compatível com variância "
                 "negativa por cancelamento numérico em precisão simples. Convém calcular a "
                 "variância de forma estável (algoritmo de Welford) em uma versão futura.")
    r += ["",
          "## 8. Observações metodológicas", "",
          "- Os quartis do firmware são obtidos por posição no vetor ordenado, sem interpolação, "
          "e a mediana é o elemento de índice N/2. Isso difere de `pandas.quantile` e "
          "`numpy.median`, que interpolam. Por esse motivo, o critério de outlier calculado "
          "sobre a série inteira no Python não é equivalente ao do firmware.",
          "- As entradas do recálculo são as leituras gravadas com duas casas decimais; "
          "pequenas diferenças de arredondamento são cobertas pelas tolerâncias.",
          f"- Foram registradas {n_div_tot} divergência(s)"
          + (" em `divergencias.csv`." if diverg else ".")]
    salvar_relatorio(pasta, r)
    return pasta, "Validação do cálculo embarcado (recálculo em Python)", res_var, res_corr


# ----------------------------------------------------------
# ANALISE 2: cada variavel (leitura, estatisticas da janela, distribuicao)
# ----------------------------------------------------------
def grafico_variavel(ordem, col, cfg):
    suf, cor = cfg["suf"], cfg["cor"]
    pasta = nova_pasta(ordem, f"{col}_estatisticas")
    x = df["DataHora"]
    s = df[col]

    # --- grafico 1: serie temporal + estatisticas da janela + outliers ---
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.fill_between(x, df[f"Q1{suf}"], df[f"Q3{suf}"], color=cor, alpha=0.18,
                    label="Faixa Q1-Q3 (janela)")
    ax.plot(x, df[col], color=cor, lw=1, marker=marcador, ms=3, label="Leitura")
    ax.plot(x, df[f"Media{suf}"], color="black", lw=1.2, ls="--", label="Média (janela)")
    ax.plot(x, df[f"Mediana{suf}"], color="gray", lw=1.2, ls=":", label="Mediana (janela)")
    out = df[df[f"Out{suf}"] == "SIM"]
    ax.scatter(out["DataHora"], out[col], color="red", s=35, zorder=5,
               label=f"Outlier ({len(out)})")
    ax.set_title(f"{cfg['rotulo']} - leitura e estatísticas da janela")
    ax.set_xlabel("Tempo")
    ax.set_ylabel(cfg["rotulo"])
    ax.legend(loc="best", fontsize=8)
    formatar_eixo_tempo(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, "grafico.png"), dpi=300)
    plt.close(fig)

    # --- grafico 2: histograma + boxplot ---
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5),
                                   gridspec_kw={"width_ratios": [2, 1]})
    ax1.hist(s, bins="auto", color=cor, alpha=0.7, edgecolor="white")
    ax1.axvline(s.mean(), color="black", ls="--", lw=1.2, label=f"Média ({s.mean():.2f})")
    ax1.axvline(s.median(), color="gray", ls=":", lw=1.2, label=f"Mediana ({s.median():.2f})")
    ax1.set_title(f"Distribuição de {cfg['rotulo']}")
    ax1.set_xlabel(cfg["rotulo"])
    ax1.set_ylabel("Frequência")
    ax1.legend(fontsize=8)
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax2.boxplot(s, patch_artist=True, boxprops={"facecolor": cor, "alpha": 0.4})
    ax2.set_title("Boxplot")
    ax2.set_xticks([])
    ax2.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, "distribuicao.png"), dpi=300)
    plt.close(fig)

    # --- calculos para o relatorio ---
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    out_global = int(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).sum())
    cv = (s.std() / s.mean() * 100) if s.mean() != 0 else float("nan")
    assim, curt = s.skew(), s.kurt()
    n_out = len(out)
    pct = 100 * n_out / len(df)

    # resolucao observada (valores discretos do sensor)
    distintos = np.sort(s.dropna().unique())
    n_dist = len(distintos)
    passo = float(np.diff(distintos).min()) if n_dist > 1 else float("nan")

    # outliers em janelas com IQR nulo (qualquer variacao e marcada)
    iqr_zero = int(((out[f"Q3{suf}"] - out[f"Q1{suf}"]) == 0).sum()) if n_out else 0
    pct_iqr0 = 100 * iqr_zero / n_out if n_out else 0.0

    # tendencia linear no tempo
    coef = np.polyfit(df["Horas"], s, 1)
    pred = np.polyval(coef, df["Horas"])
    ss_res = ((s - pred) ** 2).sum()
    ss_tot = ((s - s.mean()) ** 2).sum()
    r2_trend = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    horas_total = df["Horas"].iloc[-1]
    variacao_total = coef[0] * horas_total

    n10 = max(1, len(df) // 10)
    ini, fim = s.iloc[:n10].mean(), s.iloc[-n10:].mean()

    r = cabecalho_relatorio(
        f"Relatório: {cfg['rotulo']}",
        [("Leitura e estatísticas da janela", "grafico.png"),
         ("Distribuição e boxplot", "distribuicao.png")])

    r += [
        "## 1. Descrição dos gráficos", "",
        f"O primeiro gráfico apresenta a série temporal de **{cfg['rotulo']}** junto às "
        f"estatísticas calculadas pelo firmware em janelas deslizantes de {SAMPLE_SIZE} amostras: "
        "média (tracejada), mediana (pontilhada) e faixa interquartil Q1-Q3 (área sombreada). "
        "Leituras sinalizadas como outliers pelo firmware aparecem em vermelho. "
        "O segundo gráfico mostra a distribuição de frequências e o boxplot da série completa.", "",
        "## 2. Estatísticas globais (série completa)", "",
    ]
    r += tabela_md(["Métrica", "Valor"], [
        ["Média", f"{s.mean():.2f}"],
        ["Mediana", f"{s.median():.2f}"],
        ["Desvio padrão", f"{s.std():.2f}"],
        ["Variância", f"{s.var():.2f}"],
        ["Coeficiente de variação", f"{cv:.1f}%"],
        ["Mínimo", f"{s.min():.2f}"],
        ["Percentil 5", f"{s.quantile(0.05):.2f}"],
        ["Q1 (percentil 25)", f"{q1:.2f}"],
        ["Q3 (percentil 75)", f"{q3:.2f}"],
        ["Percentil 95", f"{s.quantile(0.95):.2f}"],
        ["Máximo", f"{s.max():.2f}"],
        ["Amplitude", f"{s.max() - s.min():.2f}"],
        ["Intervalo interquartil (IQR)", f"{iqr:.2f}"],
        ["Assimetria", f"{assim:.3f}"],
        ["Curtose (excesso)", f"{curt:.3f}"],
        ["Valores distintos observados", n_dist],
        ["Menor degrau entre valores distintos", fn(passo, 3)],
        ["Outliers (critério IQR global, quartis interpolados)", out_global],
    ])

    r += ["", "## 3. Tendência temporal", ""]
    r += tabela_md(["Métrica", "Valor"], [
        ["Inclinação da reta de tendência", f"{coef[0]:.4f} por hora"],
        ["Variação estimada no período", f"{variacao_total:+.2f}"],
        ["R² da tendência linear", f"{r2_trend:.3f}"],
        [f"Média do primeiro décimo da série ({n10} leituras)", f"{ini:.2f}"],
        [f"Média do último décimo da série ({n10} leituras)", f"{fim:.2f}"],
        ["Diferença entre último e primeiro décimo", f"{fim - ini:+.2f}"],
    ])

    r += ["", f"## 4. Estatísticas do firmware (janela de {SAMPLE_SIZE} amostras)", ""]
    r += tabela_md(["Métrica", "Valor"], [
        ["Média das médias de janela", f"{df[f'Media{suf}'].mean():.2f}"],
        ["Média das medianas de janela", f"{df[f'Mediana{suf}'].mean():.2f}"],
        ["Desvio padrão médio da janela", f"{df[f'Desv{suf}'].mean():.2f}"],
        ["Desvio padrão máximo da janela", f"{df[f'Desv{suf}'].max():.2f}"],
        ["Amplitude interquartil média (Q3-Q1)",
         f"{(df[f'Q3{suf}'] - df[f'Q1{suf}']).mean():.2f}"],
        ["Outliers marcados pelo firmware (sem aquecimento)",
         f"{n_out} ({pct:.1f}% das leituras)"],
        ["Outliers em janelas com IQR nulo",
         f"{iqr_zero} ({pct_iqr0:.1f}% dos outliers)"],
    ])

    r += ["", "## 5. Outliers detectados pelo firmware", ""]
    if n_out == 0:
        r.append("Nenhum outlier foi sinalizado no período analisado.")
    else:
        r.append(f"Primeiro outlier em {out['DataHora'].iloc[0]} e último em "
                 f"{out['DataHora'].iloc[-1]}.")
        r.append("")
        linhas = [[row["DataHora"], f"{row[col]:.2f}", f"{row[f'Media{suf}']:.2f}",
                   f"{row[f'Desv{suf}']:.2f}"]
                  for _, row in out.head(MAX_OUTLIERS_TABELA).iterrows()]
        r += tabela_md(["Data e hora", "Leitura", "Média da janela", "Desvio da janela"], linhas)
        if n_out > MAX_OUTLIERS_TABELA:
            r += ["", f"*Exibidos os {MAX_OUTLIERS_TABELA} primeiros de {n_out} outliers.*"]

    # --- interpretacao automatica ---
    if cv < 10:
        txt_cv = "baixa variabilidade relativa"
    elif cv < 30:
        txt_cv = "variabilidade relativa moderada"
    else:
        txt_cv = "alta variabilidade relativa"
    if abs(assim) < 0.5:
        txt_as = "distribuição aproximadamente simétrica"
    elif assim > 0:
        txt_as = "distribuição assimétrica à direita (cauda de valores altos)"
    else:
        txt_as = "distribuição assimétrica à esquerda (cauda de valores baixos)"
    if np.isnan(r2_trend) or r2_trend < 0.05:
        txt_tr = "não há tendência linear relevante ao longo do período"
    else:
        sentido = "crescente" if coef[0] > 0 else "decrescente"
        txt_tr = (f"há tendência linear {sentido} (R² = {r2_trend:.2f}), com variação estimada "
                  f"de {variacao_total:+.2f} no período")
    r += [
        "", "## 6. Interpretação", "",
        f"- A série apresenta {txt_cv} (coeficiente de variação de {cv:.1f}%).",
        f"- A {txt_as} (assimetria de {assim:.2f}).",
        f"- Quanto à tendência, {txt_tr}.",
        f"- O firmware sinalizou {n_out} outlier(s) por janela ({pct:.1f}% das leituras), "
        f"enquanto o critério IQR global identificou {out_global}. A diferença decorre de o "
        "firmware avaliar cada leitura contra a janela local (com quartis por posição, sem "
        "interpolação), e o critério global comparar com toda a série.",
    ]
    if n_dist > 1:
        r.append(f"- O sensor apresentou {n_dist} valores distintos, com menor degrau de "
                 f"{fn(passo, 2)}. Essa resolução discreta deve ser comparada à exatidão do "
                 "sensor antes de interpretar pequenas variações como fenômeno físico.")
    if n_out and pct_iqr0 >= 50:
        r.append(f"- {pct_iqr0:.0f}% dos outliers ocorreram em janelas com IQR nulo, situação em que "
                 "qualquer variação da leitura é marcada. Isso indica efeito da resolução "
                 "discreta do sensor combinada ao critério de Tukey em janela curta, e não "
                 "necessariamente anomalia.")
    elif n_out and pct_iqr0 > 0:
        r.append(f"- {pct_iqr0:.0f}% dos outliers ocorreram em janelas com IQR nulo, em que "
                 "qualquer variação é marcada; esses casos merecem ser tratados separadamente.")
    r += [
        "", "## 7. Observações metodológicas", "",
        f"- As {SAMPLE_SIZE} primeiras leituras de cada segmento de operação contínua foram "
        "descartadas, pois o buffer do firmware ainda continha zeros.",
        "- Estatísticas globais foram calculadas no Python; estatísticas de janela foram "
        "calculadas e gravadas pelo firmware. A conferência do cálculo embarcado está em "
        "`01_validacao_firmware`.",
    ]
    salvar_relatorio(pasta, r)
    return pasta, f"{cfg['rotulo']}: leitura, janela e distribuição"


# ----------------------------------------------------------
# ANALISE 3: desvio padrao da janela ao longo do tempo
# ----------------------------------------------------------
def grafico_desvios(ordem):
    pasta = nova_pasta(ordem, "desvio_padrao")
    fig, axes = plt.subplots(len(VARIAVEIS), 1, figsize=(11, 8), sharex=True)
    for ax, (col, cfg) in zip(axes, VARIAVEIS.items()):
        ax.plot(df["DataHora"], df[f"Desv{cfg['suf']}"], color=cfg["cor"], lw=1)
        ax.set_ylabel(f"Desvio\n{cfg['rotulo']}", fontsize=8)
        ax.grid(True, linestyle="--", alpha=0.5)
    axes[0].set_title("Desvio padrão da janela ao longo do tempo")
    axes[-1].set_xlabel("Tempo")
    formatar_eixo_tempo(axes[-1])
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, "grafico.png"), dpi=300)
    plt.close(fig)

    r = cabecalho_relatorio("Relatório: desvio padrão da janela")
    r += [
        "## 1. Descrição do gráfico", "",
        f"O gráfico mostra o desvio padrão amostral calculado pelo firmware em janelas de "
        f"{SAMPLE_SIZE} amostras para cada variável. Valores elevados indicam maior "
        "instabilidade das leituras naquele intervalo; valores próximos de zero indicam "
        "estabilidade.", "",
        "## 2. Resumo por variável", "",
    ]
    linhas = []
    for col, cfg in VARIAVEIS.items():
        d = df[f"Desv{cfg['suf']}"]
        linhas.append([cfg["rotulo"], f"{d.mean():.2f}", f"{d.median():.2f}",
                       f"{d.std():.2f}", f"{d.quantile(0.95):.2f}", f"{d.max():.2f}",
                       df.loc[d.idxmax(), "DataHora"]])
    r += tabela_md(["Variável", "Média", "Mediana", "Desvio do desvio", "Percentil 95",
                    "Máximo", "Instante do máximo"], linhas)

    r += ["", "## 3. Estabilidade relativa", "",
          "O desvio relativo corresponde ao desvio padrão da janela dividido pela média da "
          "janela, o que permite comparar variáveis de escalas distintas.", ""]
    linhas = []
    rel_med = {}
    for col, cfg in VARIAVEIS.items():
        suf = cfg["suf"]
        med = df[f"Media{suf}"].replace(0, np.nan)
        rel = (df[f"Desv{suf}"] / med * 100).dropna()
        rel_med[cfg["rotulo"]] = rel.mean()
        linhas.append([cfg["rotulo"], f"{rel.mean():.2f}%", f"{rel.max():.2f}%"])
    r += tabela_md(["Variável", "Desvio relativo médio", "Desvio relativo máximo"], linhas)

    mais_inst = max(rel_med, key=rel_med.get)
    mais_est = min(rel_med, key=rel_med.get)
    r += ["", "## 4. Interpretação", "",
          f"- Em termos relativos, a variável mais instável nas janelas foi **{mais_inst}**.",
          f"- A variável mais estável foi **{mais_est}**."]
    salvar_relatorio(pasta, r)
    return pasta, "Desvio padrão da janela ao longo do tempo"


# ----------------------------------------------------------
# ANALISE 4: correlacoes do firmware (visao conjunta)
# ----------------------------------------------------------
def grafico_correlacoes(ordem, atualizadas):
    pasta = nova_pasta(ordem, "correlacao_firmware")
    fig, ax = plt.subplots(figsize=(11, 5))
    for c, (v1, v2) in CORRELACOES.items():
        d = atualizadas[c]
        if d.empty:
            continue
        ax.plot(d["DataHora"], d[c], marker="o", ms=3, lw=1, label=f"{v1} x {v2}")
    ax.axhline(CORR_THRESHOLD, color="gray", ls="--", lw=0.8)
    ax.axhline(-CORR_THRESHOLD, color="gray", ls="--", lw=0.8,
               label=f"Limite de significância (±{CORR_THRESHOLD})")
    ax.axhline(0, color="black", lw=0.6)
    ax.set_ylim(-1.05, 1.05)
    ax.set_title(f"Correlação de Pearson por bloco de {CORR_BUFFER_SIZE} amostras (firmware)")
    ax.set_xlabel("Tempo")
    ax.set_ylabel("Coeficiente de correlação")
    ax.legend(fontsize=8)
    formatar_eixo_tempo(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, "grafico.png"), dpi=300)
    plt.close(fig)

    r = cabecalho_relatorio("Relatório: correlação por bloco (firmware)")
    r += [
        "## 1. Descrição do gráfico", "",
        f"O gráfico exibe o coeficiente de correlação de Pearson calculado pelo firmware a cada "
        f"bloco de {CORR_BUFFER_SIZE} amostras consecutivas (sem sobreposição), para cada par de "
        f"variáveis. As linhas tracejadas indicam o limite de significância adotado "
        f"(|r| > {CORR_THRESHOLD}). A análise detalhada de cada par está nas pastas `*_par_*`.", "",
        "## 2. Resumo por par de variáveis", "",
    ]
    linhas = []
    for c, (v1, v2) in CORRELACOES.items():
        d = atualizadas[c][c]
        if d.empty:
            linhas.append([f"{v1} x {v2}", 0, "-", "-", "-", "-", "-", "-", "sem blocos completos"])
            continue
        sig = (d.abs() > CORR_THRESHOLD).mean() * 100
        linhas.append([f"{v1} x {v2}", len(d), f"{d.mean():.3f}", f"{d.std():.3f}",
                       f"{d.min():.3f}", f"{d.max():.3f}", f"{d.iloc[-1]:.3f}",
                       f"{sig:.1f}%", classificar_correlacao(d.mean())])
    r += tabela_md(["Par", "Blocos", "Média", "Desvio", "Mínimo", "Máximo", "Último",
                    f"Blocos com \\|r\\| > {CORR_THRESHOLD}", "Classificação da média"], linhas)
    r += ["", "## 3. Observação", "",
          f"Blocos de {CORR_BUFFER_SIZE} amostras produzem coeficientes instáveis. Por isso, a "
          "correlação global e a análise por par (com dispersão e correlação defasada) "
          "complementam esta visão. A conferência do cálculo do firmware está em "
          "`01_validacao_firmware`."]
    salvar_relatorio(pasta, r)
    return pasta, f"Correlação de Pearson por bloco de {CORR_BUFFER_SIZE} amostras"


# ----------------------------------------------------------
# ANALISE 5: correlacao global (Pearson e Spearman)
# ----------------------------------------------------------
def heatmap_global(ordem):
    pasta = nova_pasta(ordem, "correlacao_global")
    cols = list(VARIAVEIS)
    nomes = {c: VARIAVEIS[c]["rotulo"] for c in cols}
    corr_p = df[cols].corr(method="pearson")
    corr_s = df[cols].corr(method="spearman")
    corr_p.to_csv(os.path.join(pasta, "correlacao_pearson.csv"), float_format="%.3f")
    corr_s.to_csv(os.path.join(pasta, "correlacao_spearman.csv"), float_format="%.3f")

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, m, titulo in ((axes[0], corr_p, "Pearson (linear)"),
                          (axes[1], corr_s, "Spearman (monotônica)")):
        sns.heatmap(m, annot=True, cmap="coolwarm", fmt=".2f", vmin=-1, vmax=1, ax=ax)
        ax.set_title(f"Correlação global - {titulo}")
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, "grafico.png"), dpi=300)
    plt.close(fig)

    r = cabecalho_relatorio("Relatório: correlação global")
    r += [
        "## 1. Descrição do gráfico", "",
        "Os mapas de calor apresentam as matrizes de correlação entre as três variáveis, "
        "calculadas pelo Python sobre a série completa de leituras brutas (e não por blocos, "
        "como no firmware). À esquerda, o coeficiente de Pearson, que mede associação linear; "
        "à direita, o de Spearman, que mede associação monotônica e é menos sensível a "
        "outliers.", "",
        "## 2. Matriz de Pearson", "",
    ]
    r += tabela_md([""] + [nomes[c] for c in cols],
                   [[nomes[a]] + [f"{corr_p.loc[a, b]:.3f}" for b in cols] for a in cols])
    r += ["", "## 3. Matriz de Spearman", ""]
    r += tabela_md([""] + [nomes[c] for c in cols],
                   [[nomes[a]] + [f"{corr_s.loc[a, b]:.3f}" for b in cols] for a in cols])

    r += ["", "## 4. Interpretação por par", ""]
    linhas = []
    for c, (a, b) in PARES.items():
        rp, pp = pearson(df[a], df[b])
        rs, ps = spearman(df[a], df[b])
        linhas.append([f"{nomes[a]} x {nomes[b]}", f"{rp:.3f}", fmt_p(pp), f"{rs:.3f}",
                       fmt_p(ps), classificar_correlacao(rp)])
    r += tabela_md(["Par", "Pearson", "p (Pearson)", "Spearman", "p (Spearman)",
                    "Classificação (Pearson)"], linhas)
    r += ["", "A análise detalhada de cada par (dispersão, regressão e correlação defasada) "
          "está nas pastas `*_par_*`."]
    salvar_relatorio(pasta, r)
    return pasta, "Correlação global (Pearson e Spearman)", corr_p, corr_s


# ----------------------------------------------------------
# ANALISE 6: cada par de variaveis (dispersao, regressao, blocos, defasagem)
# ----------------------------------------------------------
def analise_par(ordem, chave, atualizadas):
    a, b = PARES[chave]
    la, lb = VARIAVEIS[a]["rotulo"], VARIAVEIS[b]["rotulo"]
    nome_par = f"{CORRELACOES[chave][0]} x {CORRELACOES[chave][1]}"
    pasta = nova_pasta(ordem, f"par_{a}_x_{b}")
    xa, yb = df[a], df[b]

    rp, pp = pearson(xa, yb)
    rs, ps = spearman(xa, yb)
    r2 = rp ** 2 if not np.isnan(rp) else float("nan")

    if xa.std() > 0:
        inc, inter = np.polyfit(xa, yb, 1)
    else:
        inc, inter = float("nan"), float("nan")

    # --- grafico 1: dispersao com reta de regressao, colorida pelo tempo ---
    fig, ax = plt.subplots(figsize=(8, 6))
    sc = ax.scatter(xa, yb, c=df["Horas"], cmap="viridis", s=14, alpha=0.7)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("Tempo decorrido (h)")
    if not np.isnan(inc):
        xs = np.linspace(xa.min(), xa.max(), 100)
        ax.plot(xs, inc * xs + inter, color="red", lw=1.8,
                label=f"y = {inc:.3f}x + {inter:.2f}")
        ax.legend(fontsize=9)
    ax.set_xlabel(la)
    ax.set_ylabel(lb)
    ax.set_title(f"{nome_par}\nPearson r = {rp:.3f} | Spearman = {rs:.3f} | R² = {r2:.3f}")
    ax.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, "dispersao.png"), dpi=300)
    plt.close(fig)

    # --- grafico 2: correlacao por bloco do firmware (apenas este par) ---
    d_fw = atualizadas[chave]
    tem_fw = not d_fw.empty
    if tem_fw:
        fig, ax = plt.subplots(figsize=(11, 4.5))
        ax.plot(d_fw["DataHora"], d_fw[chave], marker="o", ms=3, lw=1, color="tab:purple",
                label=f"r por bloco de {CORR_BUFFER_SIZE} amostras")
        ax.axhline(rp, color="red", ls="-.", lw=1, label=f"r global ({rp:.3f})")
        ax.axhline(CORR_THRESHOLD, color="gray", ls="--", lw=0.8)
        ax.axhline(-CORR_THRESHOLD, color="gray", ls="--", lw=0.8,
                   label=f"Limite de significância (±{CORR_THRESHOLD})")
        ax.axhline(0, color="black", lw=0.6)
        ax.set_ylim(-1.05, 1.05)
        ax.set_title(f"{nome_par}: correlação por bloco (firmware)")
        ax.set_xlabel("Tempo")
        ax.set_ylabel("Coeficiente de correlação")
        ax.legend(fontsize=8)
        formatar_eixo_tempo(ax)
        fig.tight_layout()
        fig.savefig(os.path.join(pasta, "janelas_firmware.png"), dpi=300)
        plt.close(fig)

    # --- grafico 3: correlacao defasada ---
    lag_max = int(min(LAG_MAX, max(1, len(df) // 4)))
    lags = list(range(-lag_max, lag_max + 1))
    corr_lag = [xa.corr(yb.shift(k)) for k in lags]
    serie_lag = pd.Series(corr_lag, index=lags)
    melhor_lag = int(serie_lag.abs().idxmax()) if serie_lag.notna().any() else 0
    melhor_r = float(serie_lag.loc[melhor_lag]) if serie_lag.notna().any() else float("nan")

    fig, ax = plt.subplots(figsize=(10, 4.5))
    cores = ["tab:red" if k == melhor_lag else "tab:blue" for k in lags]
    ax.bar(lags, corr_lag, color=cores)
    ax.axhline(0, color="black", lw=0.6)
    ax.set_ylim(-1.05, 1.05)
    ax.set_xlabel(f"Defasagem (amostras de ~{fn(INTERVALO_S, 0)} s)")
    ax.set_ylabel("Correlação")
    ax.set_title(f"{nome_par}: correlação defasada (melhor defasagem em vermelho)")
    ax.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    fig.savefig(os.path.join(pasta, "correlacao_defasada.png"), dpi=300)
    plt.close(fig)

    # --- relatorio do par ---
    imagens = [("Dispersão com reta de regressão", "dispersao.png")]
    if tem_fw:
        imagens.append(("Correlação por bloco do firmware", "janelas_firmware.png"))
    imagens.append(("Correlação defasada", "correlacao_defasada.png"))
    r = cabecalho_relatorio(f"Relatório do par: {nome_par}", imagens)

    r += [
        "## 1. Descrição dos gráficos", "",
        f"- **Dispersão:** cada ponto é uma leitura simultânea de {la} (eixo x) e {lb} "
        "(eixo y), colorida pelo tempo decorrido. A reta vermelha é a regressão linear por "
        "mínimos quadrados.",
        f"- **Blocos do firmware:** evolução do coeficiente de Pearson calculado pelo firmware "
        f"a cada bloco de {CORR_BUFFER_SIZE} amostras, comparado ao coeficiente global.",
        f"- **Correlação defasada:** correlação entre {la} e {lb} deslocada de k amostras. "
        "Defasagens positivas comparam a variável x no instante t com a variável y em t+k; "
        "revela se uma variável responde à outra com atraso.", "",
        "## 2. Correlação global", "",
    ]
    r += tabela_md(["Medida", "Valor"], [
        ["Pearson (r)", f"{rp:.3f}"],
        ["p-valor (Pearson)", fmt_p(pp)],
        ["Spearman (ρ)", f"{rs:.3f}"],
        ["p-valor (Spearman)", fmt_p(ps)],
        ["Coeficiente de determinação (R²)", f"{r2:.3f}"],
        ["Classificação (Pearson)", classificar_correlacao(rp)],
        ["Observações pareadas", len(df)],
    ])

    r += ["", "## 3. Regressão linear simples", "",
          f"Modelo ajustado: **{lb} = {inc:.4f} × ({la}) + {inter:.3f}**", ""]
    r += tabela_md(["Parâmetro", "Valor"], [
        ["Inclinação (coeficiente angular)", f"{inc:.4f}"],
        ["Intercepto", f"{inter:.3f}"],
        ["R²", f"{r2:.3f}"],
    ])
    if not np.isnan(inc):
        r += ["", f"Para cada aumento de 1 unidade em {la}, o modelo estima uma variação de "
              f"{inc:+.3f} em {lb}. O modelo explica {100 * r2:.1f}% da variabilidade de {lb}."]

    r += ["", f"## 4. Correlação por bloco do firmware (blocos de {CORR_BUFFER_SIZE} amostras)", ""]
    sig = float("nan")
    media_fw = float("nan")
    if not tem_fw:
        r.append("Não há blocos completos de correlação registrados para este par.")
    else:
        d = d_fw[chave]
        sig = (d.abs() > CORR_THRESHOLD).mean() * 100
        media_fw = d.mean()
        pos = (d > CORR_THRESHOLD).mean() * 100
        neg = (d < -CORR_THRESHOLD).mean() * 100
        r += tabela_md(["Métrica", "Valor"], [
            ["Número de blocos", len(d)],
            ["Média dos coeficientes", f"{d.mean():.3f}"],
            ["Mediana dos coeficientes", f"{d.median():.3f}"],
            ["Desvio padrão dos coeficientes", f"{d.std():.3f}"],
            ["Mínimo", f"{d.min():.3f}"],
            ["Máximo", f"{d.max():.3f}"],
            ["Último bloco", f"{d.iloc[-1]:.3f}"],
            [f"Blocos com r > {CORR_THRESHOLD}", f"{pos:.1f}%"],
            [f"Blocos com r < -{CORR_THRESHOLD}", f"{neg:.1f}%"],
            [f"Blocos com \\|r\\| > {CORR_THRESHOLD}", f"{sig:.1f}%"],
            ["Inversões de sinal entre blocos consecutivos",
             int((np.sign(d).diff().abs() == 2).sum())],
        ])

    r += ["", "## 5. Correlação defasada", ""]
    linhas = []
    for k in sorted(set([-lag_max, -lag_max // 2, -1, 0, 1, lag_max // 2, lag_max, melhor_lag])):
        if k in serie_lag.index and not np.isnan(serie_lag.loc[k]):
            linhas.append([k, f"{k * INTERVALO_S:.0f} s", f"{serie_lag.loc[k]:.3f}"])
    r += tabela_md(["Defasagem (amostras)", "Tempo aproximado", "Correlação"], linhas)
    r += ["", f"A maior correlação absoluta ocorre na defasagem de **{melhor_lag}** amostra(s) "
          f"(~{melhor_lag * INTERVALO_S:.0f} s), com r = {melhor_r:.3f}."]

    r += ["", "## 6. Interpretação", ""]
    r.append(f"- A correlação global entre {la} e {lb} é {classificar_correlacao(rp)}, "
             f"com r = {rp:.3f}.")
    if pp is not None:
        if pp < ALPHA:
            r.append(f"- O teste de Pearson rejeita a hipótese de correlação nula ao nível de "
                     f"{ALPHA:.2f} (p {fmt_p(pp)}). Com séries longas e autocorrelacionadas, "
                     "porém, o p-valor tende a ser otimista; convém avaliar também a magnitude.")
        else:
            r.append(f"- Não há evidência estatística de correlação linear ao nível de "
                     f"{ALPHA:.2f} (p = {fmt_p(pp)}).")
    if not np.isnan(rs) and not np.isnan(rp) and abs(rs) - abs(rp) > 0.1:
        r.append("- A correlação de Spearman supera a de Pearson de forma notável, o que "
                 "sugere relação monotônica não linear ou influência de outliers.")
    if tem_fw and not np.isnan(media_fw):
        if np.sign(media_fw) != np.sign(rp) and abs(media_fw) > 0.1 and abs(rp) > 0.1:
            r.append("- O sinal médio dos blocos do firmware difere do sinal da correlação "
                     "global, indicando que a relação muda ao longo do tempo (efeito de "
                     "tendência ou ciclo diário).")
        elif sig < 50:
            r.append(f"- Apenas {sig:.1f}% dos blocos atingem |r| > {CORR_THRESHOLD}, "
                     "o que indica relação instável em escala curta.")
        else:
            r.append(f"- {sig:.1f}% dos blocos atingem |r| > {CORR_THRESHOLD}, o que indica "
                     "relação consistente também em escala curta.")
    if abs(melhor_lag) >= 1 and not np.isnan(melhor_r) and not np.isnan(rp) \
            and abs(melhor_r) - abs(rp) > 0.05:
        r.append(f"- A correlação aumenta com defasagem de {melhor_lag} amostra(s), "
                 "sugerindo resposta com atraso entre as variáveis.")
    r.append("- Correlação não implica causalidade: variáveis ambientais podem variar em "
             "conjunto por influência de um terceiro fator, como o ciclo diário.")

    salvar_relatorio(pasta, r)
    return pasta, f"Par {nome_par}: dispersão, regressão, blocos e defasagem", (rp, rs, r2, melhor_lag)


# ----------------------------------------------------------
# EXECUCAO
# ----------------------------------------------------------
indice = []  # (pasta, titulo) para o relatorio geral
ordem = 1

pasta_v, titulo_v, res_var, res_corr = validacao_firmware(ordem)
indice.append((pasta_v, titulo_v))
ordem += 1

for col, cfg in VARIAVEIS.items():
    indice.append(grafico_variavel(ordem, col, cfg))
    ordem += 1

indice.append(grafico_desvios(ordem))
ordem += 1

atualizadas = correlacoes_atualizadas()
if any(len(d) > 0 for d in atualizadas.values()):
    indice.append(grafico_correlacoes(ordem, atualizadas))
    ordem += 1

pasta_h, titulo_h, corr_p, corr_s = heatmap_global(ordem)
indice.append((pasta_h, titulo_h))
ordem += 1

resumo_pares = []
for chave in PARES:
    pasta_p, titulo_p, metricas = analise_par(ordem, chave, atualizadas)
    indice.append((pasta_p, titulo_p))
    resumo_pares.append((CORRELACOES[chave], metricas))
    ordem += 1

# ----------------------------------------------------------
# RELATORIO GERAL (sintese + indice dos relatorios individuais)
# ----------------------------------------------------------
caminho_geral = os.path.join(PASTA_SAIDA, "relatorio_geral.md")
linhas = [
    "# Relatório geral de análise de dados", "",
    f"- **Arquivo:** {os.path.basename(ARQUIVO_CSV)}",
    f"- **Marcas de tempo gravadas:** {df_bruto['DataHoraOriginal'].iloc[0]} a "
    f"{df_bruto['DataHoraOriginal'].iloc[-1]}",
    f"- **Registros no arquivo:** {total_bruto}",
    f"- **Registros analisados:** {len(df)} (descartadas {N_AQUECIMENTO} leituras de "
    f"aquecimento do buffer do firmware)",
    f"- **Reinícios da placa detectados:** {N_REINICIOS}",
    f"- **Intervalo típico entre amostras:** {fn(INTERVALO_S, 0)} s", "",
    "## Validação do cálculo embarcado", "",
    "O recálculo em Python, a partir das leituras brutas, reproduz o algoritmo do firmware "
    "e é comparado aos valores gravados no CSV.", "",
]
tab = []
for col, cfg in VARIAVEIS.items():
    v = res_var[col]
    tab.append([cfg["rotulo"], f"{min(v[k]['ok'] for k in ('media', 'desv', 'q1', 'med', 'q3')):.2f}%",
                f"{v['out']['ok']:.2f}%", v["out_aquec"], v["n_nan_desv"]])
linhas += tabela_md(["Variável", "Menor concordância das estatísticas",
                     "Concordância do outlier", "Outliers no aquecimento", "Desvios NaN"], tab)
linhas += [""]
tab = []
for c, (v1, v2) in CORRELACOES.items():
    v = res_corr[c]
    tab.append([f"{v1} x {v2}", v["blocos"], f"{fn(v['ok_blocos'], 2)}%", fn(v["max_emu"], 4)])
linhas += tabela_md(["Par", "Blocos de Pearson", "Blocos concordantes", "Erro máximo (32 bits)"], tab)

linhas += ["", "## Síntese das variáveis", ""]
tab = []
for col, cfg in VARIAVEIS.items():
    s = df[col]
    tab.append([cfg["rotulo"], f"{s.mean():.2f}", f"{s.median():.2f}", f"{s.std():.2f}",
                f"{s.min():.2f}", f"{s.max():.2f}", int((df[f"Out{cfg['suf']}"] == "SIM").sum())])
linhas += tabela_md(["Variável", "Média", "Mediana", "Desvio", "Mínimo", "Máximo",
                     "Outliers (firmware, sem aquecimento)"], tab)

linhas += ["", "## Síntese das correlações entre pares (série completa)", ""]
tab = []
for (v1, v2), (rp, rs, r2, lag) in resumo_pares:
    tab.append([f"{v1} x {v2}", f"{rp:.3f}", f"{rs:.3f}", f"{r2:.3f}",
                classificar_correlacao(rp), lag])
linhas += tabela_md(["Par", "Pearson", "Spearman", "R²", "Classificação",
                     "Melhor defasagem (amostras)"], tab)

linhas += ["", "## Gráficos e relatórios individuais", ""]
for pasta, titulo in indice:
    nome = os.path.basename(pasta)
    linhas.append(f"- **{titulo}**: [`{nome}/relatorio.md`]({nome}/relatorio.md)")

with open(caminho_geral, "w", encoding="utf-8") as f:
    f.write("\n".join(linhas) + "\n")

print(f"Concluído. Resultados em '{PASTA_SAIDA}/' ({len(indice)} análises, "
      f"cada uma em sua pasta com relatorio.md).")
