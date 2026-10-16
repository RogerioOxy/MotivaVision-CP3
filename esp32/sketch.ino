/* Motiva Vision — somente demonstração, nunca aciona serviço real.
 * Rede roda em tarefa própria; connect() do PubSubClient é síncrono e
 * não bloqueia o laço de atuação. Todas as temporizações usam millis().
 */
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <time.h>
#include <initializer_list>

const char* HOST = "broker.hivemq.com";
const uint16_t PORT = 1883;
const char* PREFIX = "motiva/561942/";
const int RED = 25, GREEN = 26, BLUE = 27, BUZZER = 14, FAULT_BUTTON = 15;
const uint32_t HEARTBEAT_TIMEOUT = 7000;
WiFiClient socketClient;
PubSubClient mqtt(socketClient);
LiquidCrystal_I2C lcd(0x27, 16, 2);
Preferences prefs;
QueueHandle_t incoming, outgoing;
struct Packet {
  char topic[96];
  char body[768];
  bool retained;
};
volatile bool mqttOnline = false;
volatile uint32_t heartbeatAt = 0, faultUntil = 0;
volatile bool heartbeatSeen = false;
bool storageFault = false;
String desired = "NORMAL", effective = "FALHA", activeEvent = "";
String lastPhase = "INICIO";
JsonDocument ledger;
uint32_t actions = 0, lastStatus = 0;

String topic(const char* suffix) {
  return String(PREFIX) + suffix;
}
String stamp() {
  time_t raw = time(nullptr);
  struct tm utc;
  gmtime_r(&raw, &utc);
  char out[32];
  strftime(out, sizeof(out), "%Y-%m-%dT%H:%M:%S+00:00", &utc);
  return String(out);
}
bool healthy() {
  return !storageFault && mqttOnline && heartbeatSeen &&
         uint32_t(millis() - heartbeatAt) <= HEARTBEAT_TIMEOUT;
}
void enqueue(const char* suffix, JsonDocument& doc, bool retained = false) {
  Packet packet{};
  topic(suffix).toCharArray(packet.topic, sizeof(packet.topic));
  serializeJson(doc, packet.body, sizeof(packet.body));
  packet.retained = retained;
  if (xQueueSend(outgoing, &packet, 0) != pdTRUE) {
    Serial.println("Fila de saída cheia; central retransmitirá comando sem ACK.");
  }
}
void sendAck(const String& event, const String& command, const String& phase, const String& state) {
  lastPhase = phase;
  JsonDocument doc;
  doc["event_id"] = event;
  doc["command_id"] = command;
  doc["fase"] = phase;
  doc["estado"] = state;
  doc["timestamp"] = stamp();
  doc["clock_sync"] = time(nullptr) > 1700000000;
  enqueue("ack", doc);
}
void actuator() {
  effective = healthy() ? desired : "FALHA";
  bool suspicionPulse = (millis() / 400) % 2;
  bool faultPulse = (millis() / 150) % 2;
  bool suspicionOn = effective == "SUSPEITA" && suspicionPulse;
  // Amarelo (R+G) lento é preliminar; roxo rápido representa falha.
  digitalWrite(RED, effective == "CONFIRMADO" || suspicionOn ||
                  (effective == "FALHA" && faultPulse));
  digitalWrite(GREEN, effective == "NORMAL" || suspicionOn);
  digitalWrite(BLUE, effective == "FALHA" && faultPulse);
  // Transdutor piezo: onda de 1 kHz; não usa delay/tone bloqueante.
  digitalWrite(BUZZER, effective == "CONFIRMADO" && (millis()%1200 < 150) && (micros()/500)%2);
}
void updateDisplay() {
  static uint32_t lastDisplay = 0;
  if (millis() - lastDisplay < 200) return;
  lastDisplay = millis();
  String firstLine = effective + " " + (activeEvent.length() ? activeEvent.substring(0, 5) : String("-"));
  String secondLine = lastPhase;
  if (effective == "FALHA") {
    // Fases abreviadas deixam o motivo legível nas 16 colunas.
    String phase = lastPhase == "APLICADO" ? "AP" :
                   lastPhase == "RECEBIDO" ? "RC" :
                   lastPhase == "RECUSADO" ? "NG" : "IN";
    secondLine = phase + " " + (storageFault ? "NVS" : !mqttOnline ? "sem MQTT" : "sem heartbeat");
  }
  lcd.setCursor(0, 0);
  lcd.print((firstLine + "                ").substring(0, 16));
  lcd.setCursor(0, 1);
  lcd.print((secondLine + "                ").substring(0, 16));
}
bool saveLedger() {
  ledger["desired"] = desired;
  ledger["active"] = activeEvent;
  ledger["actions"] = actions;
  String serialized;
  serializeJson(ledger, serialized);
  // Blob evita o limite de aproximadamente 4 KB de uma string NVS.
  return prefs.putBytes("ledger", serialized.c_str(), serialized.length()+1) == serialized.length()+1;
}
void processCommand(const char* body) {
  JsonDocument doc;
  if (deserializeJson(doc, body)) return;
  String event = doc["event_id"] | "";
  String command = doc["command_id"] | "";
  String state = doc["estado"] | "";
  if (!event.length() || event.length() > 64 || !command.length() ||
      command.length() > 64 || !doc["timestamp"].is<const char*>()) return;
  sendAck(event, command, "RECEBIDO", state);
  if (!healthy()) return;
  JsonArray seen = ledger["seen"].as<JsonArray>();
  JsonArray closed = ledger["closed"].as<JsonArray>();
  for (JsonObject entry : seen) {
    if (entry["command_id"].as<String>() == command) {
      bool same = entry["event_id"].as<String>() == event && entry["estado"].as<String>() == state;
      sendAck(event, command, same ? entry["fase"].as<String>() : String("RECUSADO"), state);
      return;
    }
  }
  bool wasClosed = false;
  for (JsonVariant id : closed) if (id.as<String>() == event) wasClosed = true;
  bool allowed = (state == "NORMAL" || state == "SUSPEITA" || state == "CONFIRMADO") &&
                (state == "NORMAL" || !wasClosed) &&
                (!activeEvent.length() || activeEvent == event);
  String phase = allowed ? "APLICADO" : "RECUSADO";
  String before;
  serializeJson(ledger, before);
  String oldDesired = desired, oldActive = activeEvent;
  uint32_t oldActions = actions;
  if (allowed) {
    desired = state;
    if (state == "NORMAL") {
      if (!wasClosed) closed.add(event);
      activeEvent = "";
    } else {
      activeEvent = event;
    }
    actions++;
  }
  // Anel: expulsa apenas command_ids antigos. Tombstones NÃO são expulsos.
  uint8_t head = ledger["seen_head"] | 0;
  JsonObject entry;
  if (seen.size() < 64) entry = seen.add<JsonObject>();
  else {
    entry = seen[head].as<JsonObject>();
    entry.clear();
  }
  entry["command_id"] = command;
  entry["event_id"] = event;
  entry["estado"] = state;
  entry["fase"] = phase;
  ledger["seen_head"] = (head + 1) % 64;
  if (!saveLedger()) {
    deserializeJson(ledger, before);
    desired = oldDesired;
    activeEvent = oldActive;
    actions = oldActions;
    storageFault = true;
    actuator();
    sendAck(event, command, "RECUSADO", state);
    Serial.println("FALHA: gravação NVS recusada; reiniciar após inspeção.");
    return;
  }
  actuator();
  sendAck(event, command, phase, state);
}
void callback(char* name, byte* payload, unsigned int length) {
  if (String(name) == topic("heartbeat")) {
    JsonDocument doc;
    if (!deserializeJson(doc, payload, length) && doc["timestamp"].is<const char*>()) {
      heartbeatAt = millis();
      heartbeatSeen = true;
    }
    return;
  }
  if (String(name) != topic("comandos") || length >= 768) return;
  Packet packet{};
  memcpy(packet.body, payload, length);
  packet.body[length] = 0;
  xQueueSend(incoming, &packet, 0);
}
void networkTask(void*) {
  uint32_t retryAt = 0, backoff = 1000;
  bool wifiConnecting = false;
  uint32_t wifiStartedAt = 0;
  mqtt.setServer(HOST, PORT);
  mqtt.setCallback(callback);
  mqtt.setBufferSize(2048);
  mqtt.setSocketTimeout(1);
  mqtt.setKeepAlive(10);
  for (;;) {
    uint32_t current = millis();
    if (int32_t(faultUntil-current) > 0) {
      // TCP fechado sem MQTT DISCONNECT: o broker pode publicar o LWT.
      socketClient.stop();
      mqttOnline = false;
      heartbeatSeen = false;
    } else if (WiFi.status() != WL_CONNECTED) {
      mqttOnline = false;
      heartbeatSeen = false;
      // Um único dono do Wi-Fi. Nunca begin() sobre uma tentativa em curso.
      if (wifiConnecting && uint32_t(current-wifiStartedAt) >= 15000) {
        WiFi.disconnect();
        wifiConnecting = false;
        retryAt = current + 1000;
      }
      if (!wifiConnecting && int32_t(current-retryAt) >= 0) {
        WiFi.begin("Wokwi-GUEST", "");
        wifiConnecting = true;
        wifiStartedAt = current;
      }
    } else if (!mqtt.connected()) {
      wifiConnecting = false;
      mqttOnline = false;
      heartbeatSeen = false;
      if (int32_t(current-retryAt) >= 0) {
        String id = "mv-esp32-" + String((uint32_t)ESP.getEfuseMac(), HEX) + "-" + String(esp_random(), HEX);
        String statusTopic = topic("status");
        const char* will = "{\"estado\":\"FALHA\",\"online\":false,\"origem\":\"LWT\"}";
        if (mqtt.connect(id.c_str(), statusTopic.c_str(), 1, true, will)) {
          mqtt.subscribe(topic("comandos").c_str(), 1);
          mqtt.subscribe(topic("heartbeat").c_str(), 1);
          mqttOnline = true;
          backoff = 1000;
        } else {
          retryAt = millis() + backoff;
          backoff = min(backoff*2, uint32_t(16000));
        }
      }
    } else {
      mqttOnline = true;
      mqtt.loop();
      Packet packet;
      if (xQueueReceive(outgoing, &packet, 0) == pdTRUE) mqtt.publish(packet.topic, packet.body, packet.retained);
    }
    // Cede apenas a tarefa de rede; loop de atuação segue livre.
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}
void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  lcd.init();
  lcd.backlight();
  for (int pin : {RED, GREEN, BLUE, BUZZER}) pinMode(pin, OUTPUT);
  pinMode(FAULT_BUTTON, INPUT_PULLUP);
  if (!prefs.begin("motiva", false)) storageFault = true;
  size_t savedLength = prefs.getBytesLength("ledger");
  if (savedLength > 0 && savedLength <= 24576) {
    char* saved = new char[savedLength];
    if (prefs.getBytes("ledger", saved, savedLength) != savedLength ||
        deserializeJson(ledger, saved, savedLength)) storageFault = true;
    delete[] saved;
  } else if (savedLength > 24576) storageFault = true;
  if (!ledger["seen"].is<JsonArray>()) ledger["seen"].to<JsonArray>();
  if (!ledger["closed"].is<JsonArray>()) ledger["closed"].to<JsonArray>();
  desired = ledger["desired"] | "NORMAL";
  activeEvent = ledger["active"] | "";
  actions = ledger["actions"] | 0;
  incoming = xQueueCreate(16, sizeof(Packet));
  outgoing = xQueueCreate(24, sizeof(Packet));
  WiFi.mode(WIFI_STA);
  configTime(0, 0, "pool.ntp.org");
  xTaskCreatePinnedToCore(networkTask, "mqtt", 8192, nullptr, 1, nullptr, 0);
}
void loop() {
  static bool previousButton = HIGH;
  static uint32_t lastButton = 0;
  bool button = digitalRead(FAULT_BUTTON);
  if (previousButton == HIGH && button == LOW && millis()-lastButton > 200) {
    faultUntil = millis()+15000;
    lastButton = millis();
    Serial.println("INJECAO_FALHA: desconexão MQTT local por 15 s");
  }
  previousButton = button;
  Packet packet;
  if (xQueueReceive(incoming, &packet, 0) == pdTRUE) processCommand(packet.body);
  actuator();
  updateDisplay();
  if (millis()-lastStatus >= 2000) {
    lastStatus = millis();
    JsonDocument doc;
    doc["estado"] = effective;
    doc["desired"] = desired;
    doc["event_id"] = activeEvent;
    doc["timestamp"] = stamp();
    doc["uptime_ms"] = millis();
    doc["clock_sync"] = time(nullptr) > 1700000000;
    doc["last_phase"] = lastPhase;
    doc["storage_fault"] = storageFault;
    doc["actions"] = actions;
    doc["online"] = mqttOnline;
    enqueue("status", doc, true);
    Serial.printf("estado=%s evento=%s atuacoes=%lu\n", effective.c_str(),
                  activeEvent.c_str(), (unsigned long)actions);
  }
}
