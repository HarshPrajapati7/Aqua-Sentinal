#include <Wire.h>
#include <SPI.h>
#include <math.h>
#include <ArduinoJson.h>
#include <Adafruit_ADS1X15.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>

constexpr uint8_t PIN_PUMP_PWM = 4;
constexpr uint8_t PIN_PUMP_DIR1 = 5;
constexpr uint8_t PIN_PUMP_DIR2 = 6;
constexpr uint8_t PIN_LED_PWM = 7;
constexpr uint8_t PIN_I2C_SDA = 8;
constexpr uint8_t PIN_I2C_SCL = 9;
constexpr uint8_t PIN_TFT_CS = 10;
constexpr uint8_t PIN_TFT_MOSI = 11;
constexpr uint8_t PIN_TFT_CLK = 12;
constexpr uint8_t PIN_TFT_MISO = 13;
constexpr uint8_t PIN_TFT_DC = 14;
constexpr uint8_t PIN_TFT_RST = 15;
constexpr uint8_t PIN_BATT_ADC = 1;

constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t PWM_FREQ_HZ = 5000;
constexpr uint8_t PWM_RES_BITS = 8;
constexpr uint32_t PUMP_MAX_MS = 300000;
constexpr float DEFAULT_FLOW_ML_MIN = 120.0f;

struct CalibrationConfig {
  float flowRateMlPerMin = DEFAULT_FLOW_ML_MIN;
  float blankBaselineMv = 0.0f;
  float pfasSlopePptPerMv = 0.85f;
  float pfasInterceptPpt = 0.0f;
  float maxBlankDriftMv = 8.0f;
  float maxNoiseStdMv = 4.5f;
  bool blankVerified = false;
};

struct SystemState {
  bool pumpRunning = false;
  bool pumpReverse = false;
  uint8_t pumpDuty = 0;
  uint32_t pumpStartMs = 0;
  uint32_t pumpTargetMs = 0;
  float targetVolumeMl = 0.0f;
  uint8_t ledDuty = 0;
  float lastPfasPpt = -1.0f;
  float lastPfasUncPpt = 0.0f;
  String cartridgeId = "UNASSIGNED";
  String qcStatus = "IDLE";
};

Adafruit_ADS1115 ads;
Adafruit_ILI9341 tft(PIN_TFT_CS, PIN_TFT_DC, PIN_TFT_RST);
CalibrationConfig cal;
SystemState state;
bool adsAvailable = false;
String serialBuffer;

float readBatteryVoltage() {
  uint32_t mv = analogReadMilliVolts(PIN_BATT_ADC);
  return (mv / 1000.0f) * 5.545f;
}

void setPumpOutput(uint8_t duty, bool reverse) {
  if (duty == 0) {
    digitalWrite(PIN_PUMP_DIR1, LOW);
    digitalWrite(PIN_PUMP_DIR2, LOW);
    ledcWrite(PIN_PUMP_PWM, 0);
    state.pumpRunning = false;
    state.pumpDuty = 0;
    return;
  }
  digitalWrite(PIN_PUMP_DIR1, reverse ? LOW : HIGH);
  digitalWrite(PIN_PUMP_DIR2, reverse ? HIGH : LOW);
  ledcWrite(PIN_PUMP_PWM, duty);
  state.pumpRunning = true;
  state.pumpReverse = reverse;
  state.pumpDuty = duty;
}

void setLedBrightness(uint8_t duty) {
  state.ledDuty = duty;
  ledcWrite(PIN_LED_PWM, duty);
}

void updateDisplay() {
  tft.fillScreen(ILI9341_BLACK);
  tft.setTextWrap(false);
  tft.fillRect(0, 0, 320, 34, ILI9341_NAVY);
  tft.setTextColor(ILI9341_WHITE);
  tft.setTextSize(2);
  tft.setCursor(10, 9);
  tft.print("AQUA-SENTINEL");

  tft.setTextSize(1);
  tft.setCursor(245, 13);
  tft.printf("%.1fV", readBatteryVoltage());

  tft.setTextSize(2);
  tft.setCursor(10, 48);
  tft.setTextColor(ILI9341_CYAN);
  tft.print("Cart: ");
  tft.setTextColor(ILI9341_WHITE);
  tft.print(state.cartridgeId);

  uint16_t qcColor = ILI9341_LIGHTGREY;
  if (state.qcStatus == "VALID") qcColor = ILI9341_GREEN;
  else if (state.qcStatus == "WARNING") qcColor = ILI9341_YELLOW;
  else if (state.qcStatus == "INCONCLUSIVE") qcColor = ILI9341_RED;

  tft.setCursor(10, 78);
  tft.setTextColor(ILI9341_CYAN);
  tft.print("QC:   ");
  tft.setTextColor(qcColor);
  tft.print(state.qcStatus);

  tft.setCursor(10, 118);
  tft.setTextColor(ILI9341_CYAN);
  tft.print("PFAS: ");
  tft.setTextColor(ILI9341_WHITE);
  if (state.lastPfasPpt >= 0.0f) {
    tft.printf("%.2f +/- %.2f ppt", state.lastPfasPpt, state.lastPfasUncPpt);
  } else {
    tft.print("--");
  }

  tft.setTextSize(1);
  tft.setCursor(10, 165);
  tft.setTextColor(ILI9341_LIGHTGREY);
  tft.printf("Pump: %s (PWM %u) | Target: %.0f mL",
             state.pumpRunning ? "RUN" : "STOP", state.pumpDuty, state.targetVolumeMl);
  tft.setCursor(10, 185);
  tft.printf("LED Ring: %u/255 | Blank: %s (%.2f mV)",
             state.ledDuty, cal.blankVerified ? "OK" : "PENDING", cal.blankBaselineMv);
  tft.setCursor(10, 210);
  tft.printf("ADS1115: %s | SIH26252 Star Busters", adsAvailable ? "READY" : "OFFLINE");
}

struct SensorReading {
  float meanMv;
  float stdMv;
  bool valid;
};

SensorReading acquirePfasChannel(uint8_t samples = 32) {
  SensorReading result{0.0f, 0.0f, false};
  if (!adsAvailable) return result;

  float values[64];
  if (samples > 64) samples = 64;

  double sum = 0.0;
  for (uint8_t i = 0; i < samples; i++) {
    int16_t raw = ads.readADC_SingleEnded(0);
    float mv = ads.computeVolts(raw) * 1000.0f;
    values[i] = mv;
    sum += mv;
    delay(8);
  }

  float mean = static_cast<float>(sum / samples);
  double varSum = 0.0;
  for (uint8_t i = 0; i < samples; i++) {
    float diff = values[i] - mean;
    varSum += diff * diff;
  }
  result.meanMv = mean;
  result.stdMv = sqrtf(static_cast<float>(varSum / samples));
  result.valid = true;
  return result;
}

void sendResponse(JsonDocument& doc) {
  serializeJson(doc, Serial);
  Serial.println();
}

void handleCommand(const String& line) {
  JsonDocument req;
  DeserializationError err = deserializeJson(req, line);
  JsonDocument res;

  if (err) {
    res["ok"] = false;
    res["error"] = "invalid_json";
    sendResponse(res);
    return;
  }

  const char* cmd = req["cmd"] | "";
  res["cmd"] = cmd;

  if (strcmp(cmd, "PING") == 0) {
    res["ok"] = true;
    res["device"] = "Aqua-Sentinel-ESP32S3";
    res["ads_ready"] = adsAvailable;
    res["battery_v"] = readBatteryVoltage();
  } else if (strcmp(cmd, "SET_CARTRIDGE") == 0) {
    state.cartridgeId = req["cartridge_id"] | "UNASSIGNED";
    cal.blankVerified = false;
    state.qcStatus = "BLANK_REQ";
    updateDisplay();
    res["ok"] = true;
    res["cartridge_id"] = state.cartridgeId;
  } else if (strcmp(cmd, "START_PUMP") == 0) {
    float volumeMl = req["volume_ml"] | 500.0f;
    uint8_t duty = req["pwm"] | 200;
    bool reverse = req["reverse"] | false;
    float durationMs = (volumeMl / cal.flowRateMlPerMin) * 60000.0f;
    if (durationMs > PUMP_MAX_MS) durationMs = PUMP_MAX_MS;
    state.targetVolumeMl = volumeMl;
    state.pumpStartMs = millis();
    state.pumpTargetMs = static_cast<uint32_t>(durationMs);
    setPumpOutput(duty, reverse);
    updateDisplay();
    res["ok"] = true;
    res["volume_ml"] = volumeMl;
    res["estimated_ms"] = state.pumpTargetMs;
  } else if (strcmp(cmd, "STOP_PUMP") == 0) {
    setPumpOutput(0, false);
    updateDisplay();
    res["ok"] = true;
  } else if (strcmp(cmd, "SET_LED") == 0) {
    uint8_t duty = req["pwm"] | 0;
    setLedBrightness(duty);
    updateDisplay();
    res["ok"] = true;
    res["led_pwm"] = duty;
  } else if (strcmp(cmd, "RUN_BLANK") == 0) {
    SensorReading r = acquirePfasChannel(40);
    if (!r.valid) {
      res["ok"] = false;
      res["error"] = "ads1115_offline";
    } else {
      cal.blankBaselineMv = r.meanMv;
      cal.blankVerified = r.stdMv <= cal.maxNoiseStdMv;
      state.qcStatus = cal.blankVerified ? "BLANK_OK" : "WARNING";
      updateDisplay();
      res["ok"] = true;
      res["blank_mv"] = r.meanMv;
      res["noise_std_mv"] = r.stdMv;
      res["blank_verified"] = cal.blankVerified;
    }
  } else if (strcmp(cmd, "READ_PFAS") == 0) {
    SensorReading r = acquirePfasChannel(48);
    if (!r.valid) {
      res["ok"] = false;
      res["error"] = "ads1115_offline";
    } else {
      float netMv = r.meanMv - cal.blankBaselineMv;
      float ppt = fmaxf(0.0f, cal.pfasSlopePptPerMv * netMv + cal.pfasInterceptPpt);
      float uncPpt = fabsf(cal.pfasSlopePptPerMv * r.stdMv * 2.0f);
      String qc = "VALID";
      if (!cal.blankVerified) qc = "INCONCLUSIVE";
      else if (r.stdMv > cal.maxNoiseStdMv) qc = "WARNING";
      state.lastPfasPpt = ppt;
      state.lastPfasUncPpt = uncPpt;
      state.qcStatus = qc;
      updateDisplay();
      res["ok"] = true;
      res["raw_mv"] = r.meanMv;
      res["net_mv"] = netMv;
      res["noise_std_mv"] = r.stdMv;
      res["pfas_ppt"] = ppt;
      res["uncertainty_ppt"] = uncPpt;
      res["qc_status"] = qc;
      res["blank_verified"] = cal.blankVerified;
    }
  } else if (strcmp(cmd, "SET_CALIBRATION") == 0) {
    if (req["flow_ml_min"].is<float>())
      cal.flowRateMlPerMin = req["flow_ml_min"];
    if (req["slope"].is<float>())
      cal.pfasSlopePptPerMv = req["slope"];
    if (req["intercept"].is<float>())
      cal.pfasInterceptPpt = req["intercept"];
    res["ok"] = true;
    res["flow_ml_min"] = cal.flowRateMlPerMin;
    res["slope"] = cal.pfasSlopePptPerMv;
    res["intercept"] = cal.pfasInterceptPpt;
  } else if (strcmp(cmd, "STATUS") == 0) {
    uint32_t elapsed = state.pumpRunning ? millis() - state.pumpStartMs : 0;
    res["ok"] = true;
    res["pump_running"] = state.pumpRunning;
    res["pump_elapsed_ms"] = elapsed;
    res["pump_target_ms"] = state.pumpTargetMs;
    res["led_pwm"] = state.ledDuty;
    res["cartridge_id"] = state.cartridgeId;
    res["qc_status"] = state.qcStatus;
    res["battery_v"] = readBatteryVoltage();
  } else if (strcmp(cmd, "ABORT") == 0) {
    setPumpOutput(0, false);
    setLedBrightness(0);
    state.qcStatus = "ABORTED";
    updateDisplay();
    res["ok"] = true;
  } else {
    res["ok"] = false;
    res["error"] = "unknown_command";
  }

  sendResponse(res);
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  pinMode(PIN_PUMP_DIR1, OUTPUT);
  pinMode(PIN_PUMP_DIR2, OUTPUT);
  digitalWrite(PIN_PUMP_DIR1, LOW);
  digitalWrite(PIN_PUMP_DIR2, LOW);
  ledcAttach(PIN_PUMP_PWM, PWM_FREQ_HZ, PWM_RES_BITS);
  ledcAttach(PIN_LED_PWM, PWM_FREQ_HZ, PWM_RES_BITS);
  ledcWrite(PIN_PUMP_PWM, 0);
  ledcWrite(PIN_LED_PWM, 0);
  analogReadResolution(12);
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  adsAvailable = ads.begin(0x48);
  if (adsAvailable) ads.setGain(GAIN_TWOTHIRDS);
  SPI.begin(PIN_TFT_CLK, PIN_TFT_MISO, PIN_TFT_MOSI, PIN_TFT_CS);
  tft.begin();
  tft.setRotation(1);
  updateDisplay();
}

void loop() {
  if (state.pumpRunning && millis() - state.pumpStartMs >= state.pumpTargetMs) {
    setPumpOutput(0, false);
    updateDisplay();
    JsonDocument evt;
    evt["event"] = "PUMP_COMPLETE";
    evt["volume_ml"] = state.targetVolumeMl;
    sendResponse(evt);
  }

  while (Serial.available()) {
    char c = static_cast<char>(Serial.read());
    if (c == '\n') {
      serialBuffer.trim();
      if (serialBuffer.length() > 0) handleCommand(serialBuffer);
      serialBuffer = "";
    } else if (serialBuffer.length() < 512) {
      serialBuffer += c;
    }
  }
}
