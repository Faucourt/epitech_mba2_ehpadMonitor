# Preuve de compilation ESP32 — 2 octobre 2026

Compilation locale réussie du fichier `sketch.ino` fourni, sans changement de son contenu. Arduino exige le même nom pour le dossier et le sketch : la copie de compilation s'appelle `m1_compile/m1_compile.ino`.

- Arduino CLI : 1.5.1
- Core Espressif : esp32:esp32 2.0.17
- Bibliothèque : PubSubClient 2.8.0
- Carte : esp32:esp32:esp32
- SHA-256 du sketch : `5CC9CF7907BD7EFF00F5B6DDADA3FD0063AC977F7056BDADBCF19D7B2FD126BC`
- Code de sortie : 0

Commande (après installation du core et de la bibliothèque) :

```sh
arduino-cli compile --fqbn esp32:esp32:esp32 --output-dir build m1_compile
```

Sortie du compilateur :

```text
Sketch uses 791241 bytes (60%) of program storage space. Maximum is 1310720 bytes.
Global variables use 46968 bytes (14%) of dynamic memory, leaving 280712 bytes for local variables. Maximum is 327680 bytes.
```

Cette preuve porte sur la compilation locale. L'exécution dans Wokwi a ensuite été vérifiée avec le binaire complet local, les serveurs de compilation étant saturés. Le [README](../README.md) donne le lien du projet, les résultats des essais et la vidéo des vues Firefox côte à côte.
