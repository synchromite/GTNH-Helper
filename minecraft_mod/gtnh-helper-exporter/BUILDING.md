# Building the GTNH Helper Content Exporter (Forge 1.7.10)

This project uses an old Forge toolchain (`ForgeGradle 1.2`) and requires:

- **Java 8 JDK** (not only a JRE)
- **Gradle 2.14.1**

## 1) Confirm Java 8 is active

Check current java path/version:

```bash
which java
readlink -f "$(which java)"
java -version
```

If this shows Java 11+ (for example `/usr/lib/jvm/java-11-openjdk-amd64/bin/java`), install a Java 8 JDK and switch to it.

### Ubuntu/Debian

```bash
sudo apt update
sudo apt install openjdk-8-jdk
export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
java -version
javac -version
```

> `javac` must exist and report 1.8.x, otherwise you only have a runtime and not the full JDK.

## 2) Install/use Gradle 2.14.1

If `gradle --version` is 8.x or newer, switch to 2.14.1:

```bash
# SDKMAN option
sdk install gradle 2.14.1
sdk use gradle 2.14.1
gradle --version
```

Then build from this folder (`minecraft_mod/gtnh-helper-exporter`):

```bash
gradle clean build
```

## 3) Install into GTNH

After a successful build:

```bash
ls build/libs
cp build/libs/*.jar /path/to/your/GTNH/.minecraft/mods/
```

## 4) Run export in-game

Use the command:

```text
/gtnhhelper_export_content
```

The output JSON is written to:

```text
config/gtnh-helper/content-exports/content_seed_<sender>_<timestamp>_<uuid>.json
```
