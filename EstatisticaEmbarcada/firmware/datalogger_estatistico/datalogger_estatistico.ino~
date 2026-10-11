/*
 * Autor: Jefferson Bezerra dos Santos
 *
 * Sistema de Estatisticas para Embarcados
 *
 * Dispositivo: Arduino Nano
 * Sensores: DHT11 (Temperatura/Umidade), Higrômetro Resistivo (Solo)
 * Armazenamento: Cartão SD (FAT32)
 *
 * Funcionalidades:
 * 1. Leitura periódica de sensores (5 minutos)
 * 2. Cálculo estatístico completo (média, desvio padrão, quartis)
 * 3. Detecção de anomalias usando método IQR
 * 4. Análise de correlação entre variáveis
 * 5. Armazenamento em CSV com data/hora relativa
 * 6. Mudança automática de dias após 24 horas
 * 7. Debug visual com LEDs
 */

#include <DHT.h>
#include <SD.h>
#include <SPI.h>
#include <math.h>

// ================= CONFIGURAÇÕES DE HARDWARE =================
#define DHTPIN A1               // Pino para DHT11
#define DHTTYPE DHT11
#define SOIL_PIN A0             // Pino analógico do sensor de solo
#define SD_CS_PIN 10            // ChipSelect do SD

#define LED_VERDE 2
#define LED_AMARELO 3
#define LED_VERMELHO 4

// ================= PARÂMETROS DE AMOSTRAGEM =================
#define LOG_INTERVAL 300000       // Intervalo de leitura em ms (5 min = 300000)
#define SAMPLE_SIZE 8           // Tamanho do buffer de amostras para estatísticas
#define CORR_BUFFER_SIZE 12     // Tamanho do buffer para correlação

#define IQR_FACTOR 1.5          // Fator para detecção de outliers
#define CORR_THRESHOLD 0.5      // Correlação significativa

#define SOIL_DRY_VALUE 1023     // Valor lido quando solo seco
#define SOIL_WET_VALUE 300      // Valor lido quando solo saturado

#define REFERENCE_YEAR 2025
#define REFERENCE_MONTH 8
#define REFERENCE_DAY 10

#define START_HOUR 11
#define START_MINUTE 00

// ================= ESTRUTURAS DE DADOS =================
struct Estatisticas {
  float media;
  float desvio_padrao;
  float variancia;
  float q1;
  float mediana;
  float q3;
  float iqr;
  bool is_outlier;
};

struct ResultadoCorrelacao {
  float coeficiente;
  bool significativa;
  const char* variavel1;
  const char* variavel2;
};

struct DadosSensores {
  float temperatura;
  float umidade_ar;
  float umidade_solo_percent;
};

// ================= VARIÁVEIS GLOBAIS =================
DHT dht(DHTPIN, DHTTYPE);
File dataFile;

float temp_samples[SAMPLE_SIZE] = {0};
float umid_ar_samples[SAMPLE_SIZE] = {0};
float umid_solo_samples[SAMPLE_SIZE] = {0};
byte sample_index = 0;

float temp_buffer_corr[CORR_BUFFER_SIZE] = {0};
float umid_ar_buffer_corr[CORR_BUFFER_SIZE] = {0};
float umid_solo_buffer_corr[CORR_BUFFER_SIZE] = {0};
byte corr_index = 0;

// ================= FUNÇÕES AUXILIARES =================
void bubbleSort(float arr[], int n) {
  for (int i = 0; i < n - 1; i++) {
    bool swapped = false;
    for (int j = 0; j < n - i - 1; j++) {
      if (arr[j] > arr[j + 1]) {
        float temp = arr[j];
        arr[j] = arr[j + 1];
        arr[j + 1] = temp;
        swapped = true;
      }
    }
    if (!swapped) break;
  }
}

float mapSoilMoistureToPercent(int raw_value) {
  raw_value = constrain(raw_value, SOIL_WET_VALUE, SOIL_DRY_VALUE);
  return 100.0 - map(raw_value, SOIL_WET_VALUE, SOIL_DRY_VALUE, 0, 100);
}

// ================= FUNÇÕES ESTATÍSTICAS =================
Estatisticas calcularEstatisticas(float samples[], float new_val) {
  Estatisticas res;
  float sum = 0, sum_sq = 0;
  byte valid_count = 0;

  for (byte i = 0; i < SAMPLE_SIZE; i++) {
    if (!isnan(samples[i])) {
      sum += samples[i];
      sum_sq += samples[i] * samples[i];
      valid_count++;
    }
  }

  res.media = sum / valid_count;
  res.variancia = (sum_sq - valid_count * pow(res.media, 2)) / (valid_count - 1);
  res.desvio_padrao = sqrt(res.variancia);

  float sorted[SAMPLE_SIZE];
  memcpy(sorted, samples, SAMPLE_SIZE * sizeof(float));
  bubbleSort(sorted, SAMPLE_SIZE);

  res.q1 = sorted[SAMPLE_SIZE / 4];
  res.mediana = sorted[SAMPLE_SIZE / 2];
  res.q3 = sorted[3 * SAMPLE_SIZE / 4];
  res.iqr = res.q3 - res.q1;

  float lower_bound = res.q1 - IQR_FACTOR * res.iqr;
  float upper_bound = res.q3 + IQR_FACTOR * res.iqr;
  res.is_outlier = (new_val < lower_bound) || (new_val > upper_bound);

  return res;
}

float calcularPearson(float x[], float y[], byte n) {
  float sum_x = 0, sum_y = 0, sum_xy = 0;
  float sum_x2 = 0, sum_y2 = 0;

  for (byte i = 0; i < n; i++) {
    sum_x += x[i];
    sum_y += y[i];
    sum_xy += x[i] * y[i];
    sum_x2 += x[i] * x[i];
    sum_y2 += y[i] * y[i];
  }

  float numerador = n * sum_xy - sum_x * sum_y;
  float denominador = sqrt((n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y));

  return (denominador != 0) ? numerador / denominador : 0;
}

// ================= FUNÇÕES DE TEMPO E DATA =================
bool isLeapYear(int year) {
  return (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0));
}

byte daysInMonth(int month, int year) {
  switch (month) {
    case 1: case 3: case 5: case 7: case 8: case 10: case 12: return 31;
    case 4: case 6: case 9: case 11: return 30;
    case 2: return isLeapYear(year) ? 29 : 28;
    default: return 30;
  }
}

// Função que calcula data e hora completa em char[]
void calcularDataHora(unsigned long milliseconds, char* dataBuffer, char* horaBuffer) {
  unsigned long totalSeconds = milliseconds / 1000;
  totalSeconds += START_HOUR * 3600UL + START_MINUTE * 60UL; // soma hora/minuto inicial

  int year = REFERENCE_YEAR;
  int month = REFERENCE_MONTH;
  int day = REFERENCE_DAY;

  // Calcula dias completos
  day += totalSeconds / 86400UL;
  unsigned long remainingSeconds = totalSeconds % 86400UL;

  // Ajusta meses e anos
  while (true) {
    byte dim = daysInMonth(month, year);
    if (day <= dim) break;
    day -= dim;
    month++;
    if (month > 12) { month = 1; year++; }
  }

  // Calcula horas, minutos e segundos
  unsigned long hours = remainingSeconds / 3600UL;
  unsigned long minutes = (remainingSeconds % 3600UL) / 60UL;
  unsigned long seconds = remainingSeconds % 60UL;

  snprintf(dataBuffer, 11, "%04d-%02d-%02d", year, month, day);
  snprintf(horaBuffer, 9, "%02lu:%02lu:%02lu", hours, minutes, seconds);
}

// ================= FUNÇÕES PRINCIPAIS =================
ResultadoCorrelacao* atualizarCorrelacao(float temp, float umid_ar, float umid_solo) {
  static ResultadoCorrelacao resultados[3] = {
    {0, false, "Temp", "UAr"},
    {0, false, "Temp", "USolo"},
    {0, false, "UAr", "USolo"}
  };

  temp_buffer_corr[corr_index] = temp;
  umid_ar_buffer_corr[corr_index] = umid_ar;
  umid_solo_buffer_corr[corr_index] = umid_solo;
  corr_index = (corr_index + 1) % CORR_BUFFER_SIZE;

  if (corr_index == 0) {
    resultados[0].coeficiente = calcularPearson(temp_buffer_corr, umid_ar_buffer_corr, CORR_BUFFER_SIZE);
    resultados[0].significativa = fabs(resultados[0].coeficiente) > CORR_THRESHOLD;

    resultados[1].coeficiente = calcularPearson(temp_buffer_corr, umid_solo_buffer_corr, CORR_BUFFER_SIZE);
    resultados[1].significativa = fabs(resultados[1].coeficiente) > CORR_THRESHOLD;

    resultados[2].coeficiente = calcularPearson(umid_ar_buffer_corr, umid_solo_buffer_corr, CORR_BUFFER_SIZE);
    resultados[2].significativa = fabs(resultados[2].coeficiente) > CORR_THRESHOLD;
  }

  return resultados;
}

// ================= LOG EM CSV =================
void logData(DadosSensores dados, Estatisticas stats_umid_ar,
             Estatisticas stats_temp, Estatisticas stats_umid_solo,
             ResultadoCorrelacao* correlacoes, unsigned long tempoDecorrido) {

  dataFile = SD.open("dados.csv", FILE_WRITE);

  if (dataFile) {
    if (dataFile.size() == 0) {
      dataFile.println(F("Data,Hora,UmidadeAr,MedUAr,DesvUAr,Q1UAr,MedUAr,Q3UAr,OutUAr,Temp,MedT,DesvT,Q1T,MedT,Q3T,OutT,USolo,MedUS,DesvUS,Q1US,MedUS,Q3US,OutUS,Corr1,Corr2,Corr3"));
      dataFile.println(F("# Data calculada a partir da referência"));
    }

    char dataStr[11];
    char horaStr[9];
    calcularDataHora(tempoDecorrido, dataStr, horaStr);

    dataFile.print(dataStr); dataFile.print(',');
    dataFile.print(horaStr); dataFile.print(',');

    // Umidade do ar
    dataFile.print(dados.umidade_ar); dataFile.print(',');
    dataFile.print(stats_umid_ar.media); dataFile.print(',');
    dataFile.print(stats_umid_ar.desvio_padrao); dataFile.print(',');
    dataFile.print(stats_umid_ar.q1); dataFile.print(',');
    dataFile.print(stats_umid_ar.mediana); dataFile.print(',');
    dataFile.print(stats_umid_ar.q3); dataFile.print(',');
    dataFile.print(stats_umid_ar.is_outlier ? F("SIM") : F("NAO")); dataFile.print(',');

    // Temperatura
    dataFile.print(dados.temperatura); dataFile.print(',');
    dataFile.print(stats_temp.media); dataFile.print(',');
    dataFile.print(stats_temp.desvio_padrao); dataFile.print(',');
    dataFile.print(stats_temp.q1); dataFile.print(',');
    dataFile.print(stats_temp.mediana); dataFile.print(',');
    dataFile.print(stats_temp.q3); dataFile.print(',');
    dataFile.print(stats_temp.is_outlier ? F("SIM") : F("NAO")); dataFile.print(',');

    // Umidade do solo
    dataFile.print(dados.umidade_solo_percent); dataFile.print(',');
    dataFile.print(stats_umid_solo.media); dataFile.print(',');
    dataFile.print(stats_umid_solo.desvio_padrao); dataFile.print(',');
    dataFile.print(stats_umid_solo.q1); dataFile.print(',');
    dataFile.print(stats_umid_solo.mediana); dataFile.print(',');
    dataFile.print(stats_umid_solo.q3); dataFile.print(',');
    dataFile.print(stats_umid_solo.is_outlier ? F("SIM") : F("NAO")); dataFile.print(',');

    // Correlações
    for (byte i = 0; i < 3; i++) {
      dataFile.print(correlacoes[i].coeficiente, 4);
      if (i < 2) dataFile.print(',');
    }

    dataFile.println();
    dataFile.close();
  }
}

// ================= FUNÇÃO DE PRINT =================
void printDados(DadosSensores dados,
                Estatisticas stats_umid_ar,
                Estatisticas stats_temp,
                Estatisticas stats_umid_solo,
                ResultadoCorrelacao* correlacoes,
                unsigned long tempoDecorrido) {

  char dataStr[11];
  char horaStr[9];
  calcularDataHora(tempoDecorrido, dataStr, horaStr);

  Serial.println(F("=== Registro de sensores ==="));
  Serial.print(F("Data: ")); Serial.println(dataStr);
  Serial.print(F("Hora: ")); Serial.println(horaStr);

  // (restante da função permanece igual ao seu código)
  // Umidade do ar
  Serial.println(F("--- Umidade do ar ---"));
  Serial.print(F("Atual: ")); Serial.println(dados.umidade_ar);
  Serial.print(F("Média: ")); Serial.println(stats_umid_ar.media);
  Serial.print(F("Desvio: ")); Serial.println(stats_umid_ar.desvio_padrao);
  Serial.print(F("Q1: ")); Serial.println(stats_umid_ar.q1);
  Serial.print(F("Mediana: ")); Serial.println(stats_umid_ar.mediana);
  Serial.print(F("Q3: ")); Serial.println(stats_umid_ar.q3);
  Serial.print(F("Outlier: ")); Serial.println(stats_umid_ar.is_outlier ? F("SIM") : F("NAO"));

  // Temperatura
  Serial.println(F("--- Temperatura ---"));
  Serial.print(F("Atual: ")); Serial.println(dados.temperatura);
  Serial.print(F("Média: ")); Serial.println(stats_temp.media);
  Serial.print(F("Desvio: ")); Serial.println(stats_temp.desvio_padrao);
  Serial.print(F("Q1: ")); Serial.println(stats_temp.q1);
  Serial.print(F("Mediana: ")); Serial.println(stats_temp.mediana);
  Serial.print(F("Q3: ")); Serial.println(stats_temp.q3);
  Serial.print(F("Outlier: ")); Serial.println(stats_temp.is_outlier ? F("SIM") : F("NAO"));

  // Umidade do solo
  Serial.println(F("--- Umidade do solo ---"));
  Serial.print(F("Atual: ")); Serial.println(dados.umidade_solo_percent);
  Serial.print(F("Média: ")); Serial.println(stats_umid_solo.media);
  Serial.print(F("Desvio: ")); Serial.println(stats_umid_solo.desvio_padrao);
  Serial.print(F("Q1: ")); Serial.println(stats_umid_solo.q1);
  Serial.print(F("Mediana: ")); Serial.println(stats_umid_solo.mediana);
  Serial.print(F("Q3: ")); Serial.println(stats_umid_solo.q3);
  Serial.print(F("Outlier: ")); Serial.println(stats_umid_solo.is_outlier ? F("SIM") : F("NAO"));

  // Correlações
  Serial.println(F("--- Correlações ---"));
  for (byte i = 0; i < 3; i++) {
    Serial.print(correlacoes[i].variavel1);
    Serial.print(F(" x "));
    Serial.print(correlacoes[i].variavel2);
    Serial.print(F(": "));
    Serial.print(correlacoes[i].coeficiente, 4);
    Serial.print(F(" ("));
    Serial.print(correlacoes[i].significativa ? F("Significativa") : F("Não significativa"));
    Serial.println(F(")"));
  }
  Serial.println(F("============================\n"));
}

// ================= LEITURA DOS SENSORES =================
DadosSensores lerSensores() {
  DadosSensores dados;
  dados.umidade_ar = dht.readHumidity();
  dados.temperatura = dht.readTemperature();
  int raw_value = analogRead(SOIL_PIN);
  dados.umidade_solo_percent = mapSoilMoistureToPercent(raw_value);
  return dados;
}

// ================= SETUP =================
void setup() {
  Serial.begin(9600);
  dht.begin();
  pinMode(SOIL_PIN, INPUT);
  pinMode(LED_VERDE, OUTPUT);
  pinMode(LED_AMARELO, OUTPUT);
  pinMode(LED_VERMELHO, OUTPUT);

  if (!SD.begin(SD_CS_PIN)) {
    Serial.println(F("Erro no SD!"));
    digitalWrite(LED_VERMELHO, HIGH);
    while (1);
  }

  Serial.println(F("Sistema iniciado"));
  Serial.print(F("Data de referência: "));
  Serial.print(REFERENCE_YEAR); Serial.print("-");
  Serial.print(REFERENCE_MONTH); Serial.print("-");
  Serial.println(REFERENCE_DAY);
  Serial.print(F("Horário de início: "));
  Serial.print(START_HOUR); Serial.print(":");
  Serial.println(START_MINUTE);
}

// ================= LOOP =================
void loop() {
  static unsigned long last_log = 0;

  if (millis() - last_log >= LOG_INTERVAL) {
    last_log = millis();

    DadosSensores dados = lerSensores();

    int raw_solo = analogRead(SOIL_PIN);
    dados.umidade_solo_percent = mapSoilMoistureToPercent(raw_solo);

    bool erro_sensor_dht = isnan(dados.umidade_ar) || isnan(dados.temperatura);
    bool erro_sensor_solo = (raw_solo < SOIL_WET_VALUE || raw_solo > SOIL_DRY_VALUE);

    digitalWrite(LED_VERDE, erro_sensor_dht ? HIGH : LOW);
    digitalWrite(LED_AMARELO, erro_sensor_solo ? HIGH : LOW);

    if (!erro_sensor_dht && !erro_sensor_solo) {
      temp_samples[sample_index] = dados.temperatura;
      umid_ar_samples[sample_index] = dados.umidade_ar;
      umid_solo_samples[sample_index] = dados.umidade_solo_percent;
      sample_index = (sample_index + 1) % SAMPLE_SIZE;

      Estatisticas stats_temp = calcularEstatisticas(temp_samples, dados.temperatura);
      Estatisticas stats_umid_ar = calcularEstatisticas(umid_ar_samples, dados.umidade_ar);
      Estatisticas stats_umid_solo = calcularEstatisticas(umid_solo_samples, dados.umidade_solo_percent);

      ResultadoCorrelacao* correlacoes = atualizarCorrelacao(dados.temperatura, dados.umidade_ar, dados.umidade_solo_percent);

      printDados(dados, stats_umid_ar, stats_temp, stats_umid_solo, correlacoes, millis());
      logData(dados, stats_umid_ar, stats_temp, stats_umid_solo, correlacoes, millis());
    }
  }
}

