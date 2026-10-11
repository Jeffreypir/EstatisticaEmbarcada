# Relatório do par: Temperatura x Umidade do Solo

- **Arquivo de origem:** DadosAnalise.CSV
- **Período analisado:** 2025-10-08 11:45:00 a 2025-10-10 07:40:00
- **Registros analisados:** 528 (de 536; descartadas 8 leituras de aquecimento, as 8 primeiras de cada um dos 1 segmento(s) de operação contínua)
- **Reinícios da placa detectados:** 0
- **Intervalo típico entre amostras:** 300 s

![Dispersão com reta de regressão](dispersao.png)

![Correlação por bloco do firmware](janelas_firmware.png)

![Correlação defasada](correlacao_defasada.png)

## 1. Descrição dos gráficos

- **Dispersão:** cada ponto é uma leitura simultânea de Temperatura (°C) (eixo x) e Umidade do Solo (%) (eixo y), colorida pelo tempo decorrido. A reta vermelha é a regressão linear por mínimos quadrados.
- **Blocos do firmware:** evolução do coeficiente de Pearson calculado pelo firmware a cada bloco de 12 amostras, comparado ao coeficiente global.
- **Correlação defasada:** correlação entre Temperatura (°C) e Umidade do Solo (%) deslocada de k amostras. Defasagens positivas comparam a variável x no instante t com a variável y em t+k; revela se uma variável responde à outra com atraso.

## 2. Correlação global

| Medida | Valor |
|---|---|
| Pearson (r) | 0.037 |
| p-valor (Pearson) | 0,4012 |
| Spearman (ρ) | 0.028 |
| p-valor (Spearman) | 0,5240 |
| Coeficiente de determinação (R²) | 0.001 |
| Classificação (Pearson) | fraca ou desprezível (positiva) |
| Observações pareadas | 528 |

## 3. Regressão linear simples

Modelo ajustado: **Umidade do Solo (%) = 0.3589 × (Temperatura (°C)) + 71.570**

| Parâmetro | Valor |
|---|---|
| Inclinação (coeficiente angular) | 0.3589 |
| Intercepto | 71.570 |
| R² | 0.001 |

Para cada aumento de 1 unidade em Temperatura (°C), o modelo estima uma variação de +0.359 em Umidade do Solo (%). O modelo explica 0.1% da variabilidade de Umidade do Solo (%).

## 4. Correlação por bloco do firmware (blocos de 12 amostras)

| Métrica | Valor |
|---|---|
| Número de blocos | 41 |
| Média dos coeficientes | 0.077 |
| Mediana dos coeficientes | 0.071 |
| Desvio padrão dos coeficientes | 0.318 |
| Mínimo | -0.663 |
| Máximo | 0.802 |
| Último bloco | -0.069 |
| Blocos com r > 0.5 | 7.3% |
| Blocos com r < -0.5 | 4.9% |
| Blocos com \|r\| > 0.5 | 12.2% |
| Inversões de sinal entre blocos consecutivos | 17 |

## 5. Correlação defasada

| Defasagem (amostras) | Tempo aproximado | Correlação |
|---|---|---|
| -24 | -7200 s | 0.084 |
| -12 | -3600 s | 0.056 |
| -1 | -300 s | 0.037 |
| 0 | 0 s | 0.037 |
| 1 | 300 s | 0.028 |
| 12 | 3600 s | -0.031 |
| 24 | 7200 s | -0.099 |

A maior correlação absoluta ocorre na defasagem de **24** amostra(s) (~7200 s), com r = -0.099.

## 6. Interpretação

- A correlação global entre Temperatura (°C) e Umidade do Solo (%) é fraca ou desprezível (positiva), com r = 0.037.
- Não há evidência estatística de correlação linear ao nível de 0.05 (p = 0,4012).
- Apenas 12.2% dos blocos atingem |r| > 0.5, o que indica relação instável em escala curta.
- A correlação aumenta com defasagem de 24 amostra(s), sugerindo resposta com atraso entre as variáveis.
- Correlação não implica causalidade: variáveis ambientais podem variar em conjunto por influência de um terceiro fator, como o ciclo diário.
