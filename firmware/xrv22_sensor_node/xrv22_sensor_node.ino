/*
 * xrv22_sensor_node — Noeud capteurs/actionneurs de référence pour XRV22.
 *
 * Protocole série (115200 baud, lignes JSON) attendu par xrv22 ArduinoBridge :
 *   - Reçoit {"CMD":"IDENTIFY"}  -> répond un manifest IDENTIFY
 *   - Reçoit {"SET":"<name>","v":<val>}  -> pilote un actionneur
 *   - Reçoit {"CMD":"RUN","action":"<name>","params":{...}} -> exécute + ACK
 *   - Émet en continu les valeurs capteurs : {"temp":23.5,"dist":140}
 *
 * Exemple générique : 1 capteur analogique (A0), 1 relais (D7), 1 action "blink".
 * À ADAPTER à ton montage réel (broches, capteurs, actionneurs).
 */

const unsigned long STREAM_MS = 500;
unsigned long lastStream = 0;

const int PIN_SENSOR = A0;   // capteur analogique générique
const int PIN_RELAY  = 7;    // actionneur relais
const int PIN_LED    = 13;   // action "blink"

void sendIdentify() {
  // Manifest : sensors / actuators / actions
  Serial.print(F("{\"IDENTIFY\":{\"firmware\":\"xrv22-node v1.0\","));
  Serial.print(F("\"sensors\":[{\"name\":\"a0\",\"unit\":\"\",\"min\":0,\"max\":1023}],"));
  Serial.print(F("\"actuators\":[{\"name\":\"relay\",\"kind\":\"relay\",\"label\":\"Relais\"}],"));
  Serial.print(F("\"actions\":[{\"name\":\"blink\",\"label\":\"Clignoter\",\"duration_ms\":1000,\"has_ack\":true}]}}"));
  Serial.print('\n');
}

void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line.indexOf("\"IDENTIFY\"") >= 0) { sendIdentify(); return; }

  // SET relais : {"SET":"relay","v":"1"}
  if (line.indexOf("\"SET\"") >= 0 && line.indexOf("relay") >= 0) {
    int vi = line.indexOf("\"v\"");
    int on = (vi >= 0 && line.indexOf('1', vi) >= 0) ? HIGH : LOW;
    digitalWrite(PIN_RELAY, on);
    return;
  }

  // RUN blink : {"CMD":"RUN","action":"blink",...}
  if (line.indexOf("\"RUN\"") >= 0 && line.indexOf("blink") >= 0) {
    for (int i = 0; i < 3; i++) { digitalWrite(PIN_LED, HIGH); delay(150); digitalWrite(PIN_LED, LOW); delay(150); }
    Serial.print(F("{\"STATUS\":\"OK\",\"action\":\"blink\"}\n"));
    return;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
}

void loop() {
  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    handleLine(line);
  }
  unsigned long now = millis();
  if (now - lastStream >= STREAM_MS) {
    lastStream = now;
    int raw = analogRead(PIN_SENSOR);
    Serial.print(F("{\"a0\":")); Serial.print(raw); Serial.print(F("}\n"));
  }
}
