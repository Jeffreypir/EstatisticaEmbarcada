# Relatório geral de análise de dados

- **Arquivo:** DadosAnalise.CSV
- **Marcas de tempo gravadas:** 2025-10-08 11:05:00 a 2025-10-10 07:40:00
- **Registros no arquivo:** 536
- **Registros analisados:** 528 (descartadas 8 leituras de aquecimento do buffer do firmware)
- **Reinícios da placa detectados:** 0
- **Intervalo típico entre amostras:** 300 s

## Validação do cálculo embarcado

O recálculo em Python, a partir das leituras brutas, reproduz o algoritmo do firmware e é comparado aos valores gravados no CSV.

| Variável | Menor concordância das estatísticas | Concordância do outlier | Outliers no aquecimento | Desvios NaN |
|---|---|---|---|---|
| Umidade do Ar (%) | 100.00% | 100.00% | 1 | 0 |
| Temperatura (°C) | 100.00% | 100.00% | 1 | 75 |
| Umidade do Solo (%) | 100.00% | 100.00% | 1 | 0 |

| Par | Blocos de Pearson | Blocos concordantes | Erro máximo (32 bits) |
|---|---|---|---|
| Temperatura x Umidade do Ar | 44 | 100.00% | 0.0000 |
| Temperatura x Umidade do Solo | 44 | 100.00% | 0.0000 |
| Umidade do Ar x Umidade do Solo | 44 | 100.00% | 0.0000 |

## Síntese das variáveis

| Variável | Média | Mediana | Desvio | Mínimo | Máximo | Outliers (firmware, sem aquecimento) |
|---|---|---|---|---|---|---|
| Umidade do Ar (%) | 46.99 | 47.00 | 1.58 | 41.00 | 50.00 | 33 |
| Temperatura (°C) | 25.45 | 25.40 | 0.41 | 24.80 | 26.20 | 69 |
| Umidade do Solo (%) | 80.70 | 82.00 | 4.05 | 64.00 | 87.00 | 24 |

## Síntese das correlações entre pares (série completa)

| Par | Pearson | Spearman | R² | Classificação | Melhor defasagem (amostras) |
|---|---|---|---|---|---|
| Temperatura x Umidade do Ar | -0.417 | -0.471 | 0.174 | fraca a moderada (negativa) | 24 |
| Temperatura x Umidade do Solo | 0.037 | 0.028 | 0.001 | fraca ou desprezível (positiva) | 24 |
| Umidade do Ar x Umidade do Solo | 0.313 | 0.065 | 0.098 | fraca a moderada (positiva) | 0 |

## Gráficos e relatórios individuais

- **Validação do cálculo embarcado (recálculo em Python)**: [`01_validacao_firmware/relatorio.md`](01_validacao_firmware/relatorio.md)
- **Umidade do Ar (%): leitura, janela e distribuição**: [`02_UmidadeAr_estatisticas/relatorio.md`](02_UmidadeAr_estatisticas/relatorio.md)
- **Temperatura (°C): leitura, janela e distribuição**: [`03_Temp_estatisticas/relatorio.md`](03_Temp_estatisticas/relatorio.md)
- **Umidade do Solo (%): leitura, janela e distribuição**: [`04_USolo_estatisticas/relatorio.md`](04_USolo_estatisticas/relatorio.md)
- **Desvio padrão da janela ao longo do tempo**: [`05_desvio_padrao/relatorio.md`](05_desvio_padrao/relatorio.md)
- **Correlação de Pearson por bloco de 12 amostras**: [`06_correlacao_firmware/relatorio.md`](06_correlacao_firmware/relatorio.md)
- **Correlação global (Pearson e Spearman)**: [`07_correlacao_global/relatorio.md`](07_correlacao_global/relatorio.md)
- **Par Temperatura x Umidade do Ar: dispersão, regressão, blocos e defasagem**: [`08_par_Temp_x_UmidadeAr/relatorio.md`](08_par_Temp_x_UmidadeAr/relatorio.md)
- **Par Temperatura x Umidade do Solo: dispersão, regressão, blocos e defasagem**: [`09_par_Temp_x_USolo/relatorio.md`](09_par_Temp_x_USolo/relatorio.md)
- **Par Umidade do Ar x Umidade do Solo: dispersão, regressão, blocos e defasagem**: [`10_par_UmidadeAr_x_USolo/relatorio.md`](10_par_UmidadeAr_x_USolo/relatorio.md)
