# Firmware Arduino XRV22

`xrv22_sensor_node/` — sketch de référence implémentant le protocole série
attendu par `xrv22/hardware/arduino_bridge.py` (IDENTIFY / stream / SET / RUN+ACK).

## Flasher
1. Ouvrir `xrv22_sensor_node/xrv22_sensor_node.ino` dans l'IDE Arduino.
2. Sélectionner la carte (ex. Arduino Mega 2560) et le port (`/dev/ttyACM0` sur le Pi).
3. Téléverser.

## Adapter à ton montage
- Modifier `sendIdentify()` : déclarer tes vrais capteurs/actionneurs/actions.
- Ajouter la lecture de tes capteurs dans `loop()` (émettre `{"nom":valeur,...}`).
- Gérer tes SET/RUN dans `handleLine()`.

Sans réponse à IDENTIFY, seuls les capteurs qui streament apparaissent côté web ;
les actionneurs et actions exigent le manifest IDENTIFY.

## Pièges à connaître
- **Baudrate** : le sketch ouvre à `115200` (`Serial.begin(115200)`). Cette valeur
  doit correspondre au baud déclaré côté web au moment d'ajouter l'appareil (et à
  `BAUDRATE_ARDUINO_DEFAULT` côté Python si tu changes le défaut). Un baud incohérent
  = caractères illisibles, aucun capteur détecté.
- **Parsing `indexOf` volontairement simpliste** : `handleLine()` reconnaît les
  commandes par recherche de sous-chaîne (`indexOf("relay")`, etc.), pas par un vrai
  parseur JSON. Avec UN actionneur nommé exactement `relay` c'est correct, mais si tu
  ajoutes des noms qui se chevauchent (`relay_fan`…) ou des actionneurs PWM (valeurs
  numériques), passe à une lecture explicite de la clé `"v"` ou à une bibliothèque
  JSON (ArduinoJson).
- **Actionneur PWM** : le backend peut envoyer une valeur flottante
  (`{"SET":"fan","v":128.0}`). Convertis-la en entier dans ton `handleLine()`
  (`atoi`/`(int)`) avant `analogWrite()`.
