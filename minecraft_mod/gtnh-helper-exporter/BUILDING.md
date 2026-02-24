# Building the GTNH Helper Content Exporter (Forge 1.7.10)

This project uses an old Forge toolchain (`ForgeGradle 1.2`) and requires:

- **Java 8 JDK** (not only a JRE)
- **Gradle 2.14.1**

## 1) Confirm Java 8 is active

Check current java path/version (Java 8 uses `-version`, not `--version`):

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

If `sdk` is not installed (common on Ubuntu) or your `gradle` is not 2.14.1, use the included bootstrap script:

```bash
./build_with_gradle_2_14_1.sh --version
./build_with_gradle_2_14_1.sh clean build
```

This downloads Gradle 2.14.1 into `./.tools/` and runs that exact binary.

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


## Common error: `downloadClient` 404 on old S3 URL

If build fails with:

```
Execution failed for task ':downloadClient'.
java.io.FileNotFoundException: http://s3.amazonaws.com/Minecraft.Download/versions/1.7.10/1.7.10.jar
```

ForgeGradle 1.2 still references a retired Mojang S3 endpoint. Seed the required jars into your Gradle cache using the helper script, then run the build again:

```bash
python3 ./scripts_seed_minecraft_jars.py
./build_with_gradle_2_14_1.sh clean build
```

The script pulls official 1.7.10 client/server artifacts from Mojang `launchermeta` and writes them to the cache paths ForgeGradle expects.


## Known-good sequence for your current error output

From `minecraft_mod/gtnh-helper-exporter/` run exactly:

```bash
java -version
python3 ./scripts_seed_minecraft_jars.py
./build_with_gradle_2_14_1.sh clean build
```

If `java -version` does not report `1.8.0_xxx`, set Java 8 first and re-run.
